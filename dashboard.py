"""TERAZİ dashboard — FastAPI, port 8787.

Ayrı süreç. Kaynak YALNIZCA dosyalar: logs/decisions.jsonl, logs/orders.jsonl, logs/micro.jsonl,
state.json, control.json. Burada MCP çağrısı YOK, borsaya temas YOK — ajan çökse bile dashboard
ayakta kalır, dashboard çökse bile ajan durmaz (docs/urun-mimari.md §3.1).

Yazdığı tek dosya `control.json` (atomik) ve `logs/decisions.jsonl`'e eklediği OPERATOR_* satırı.
Al/sat düğmesi yoktur (CLAUDE.md mutlak yasak); kontrol yüzeyi run/pause/kill/flatten ile sınırlı.

Başlatma:
    .venv/bin/uvicorn dashboard:app --port 8787
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# terazi.py ile AYNI yollar; ikisi de cwd'ye göreli (proje kökünden çalıştırılır).
LOGS = Path("logs")
DECISIONS = LOGS / "decisions.jsonl"
ORDERS = LOGS / "orders.jsonl"
STATE = Path("state.json")
CONTROL = Path("control.json")
CONFIG = Path("config.yaml")
INDEX = Path("static/index.html")

# Dosyanın sonundan okunacak en büyük blok. Bir karar satırı ~400 bayt; 1 MB ≈ 2500 satır,
# yani n=50 isteği için fazlasıyla yeterli. Eşik değil, okuma tamponu.
TAIL_BYTES = 1_000_000

MODES = ("run", "pause", "kill")
CONFIRM_REQUIRED = ("kill", "flatten")

# decisions.jsonl'de görülebilen action değerleri (docs/urun-mimari.md §3.3).
# OPERATOR_* tek kovada toplanır: ajan mode değişiminde OPERATOR_RUN yazarken spec
# OPERATOR_RESUME diyor, ayrıca OPERATOR_KILL_CLEARED var — hepsi aynı sayaca girer.
ACTIONS = ("WAIT", "SETUP", "CANDIDATE", "REJECT", "ORDER", "FILL", "EXIT", "CASH", "ERROR")


# ----------------------------------------------------------------------------
# Yapılandırma — sayısal eşik koda gömülmez (CLAUDE.md)
# ----------------------------------------------------------------------------


def load_cfg() -> dict[str, Any]:
    """config.yaml SALT OKUNUR. Dashboard buradan yalnızca okur, asla yazmaz.

    `dashboard:` bloğu config.yaml'da henüz yok; eklenene kadar spec değerlerine düşülür
    (docs/urun-mimari.md §4: 2 sn polling, 60 sn bayatlık). Blok eklenirse kod değişmeden
    oradan okunur.
    """
    try:
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"config.yaml okunamadı ({exc}); varsayılanlarla devam.", file=sys.stderr)
        cfg = {}
    dash = cfg.get("dashboard") or {}
    return {
        "tz": ZoneInfo((cfg.get("execution") or {}).get("timezone", "Europe/Istanbul")),
        "vol_ban_sec": (cfg.get("regime") or {}).get("vol_ban_sec", 1800),
        "kill_switch_daily_pct": (cfg.get("risk") or {}).get("kill_switch_daily_pct", -1.5),
        "poll_sec": dash.get("poll_sec", 2),
        "stale_sec": dash.get("stale_sec", 60),
    }


CFG = load_cfg()


# ----------------------------------------------------------------------------
# Okuma yardımcıları — bozuk satır akışı DÜŞÜRMEZ
# ----------------------------------------------------------------------------


def read_jsonl_tail(path: Path, n: int | None = None) -> tuple[list[dict[str, Any]], int]:
    """Dosyanın sonundan satırları oku, en eskiden yeniye döndür. (satırlar, atlanan) verir.

    Ajan dosyaya eklerken biz okuyoruz: son satır yarım olabilir, bir satırın JSON'u bozuk
    olabilir. Böyle bir satır akışı düşürmez — atlanır ve konsola yazılır.
    """
    if not path.exists():
        return [], 0
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()  # ilk satır yarım kalmış olabilir, at
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"{path} okunamadı: {exc}", file=sys.stderr)
        return [], 0

    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if n is not None:
        lines = lines[-n:]

    rows: list[dict[str, Any]] = []
    skipped = 0
    for ln in lines:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            skipped += 1
            print(f"{path}: bozuk JSON satırı atlandı → {ln[:120]}", file=sys.stderr)
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            skipped += 1
            print(f"{path}: sözlük olmayan satır atlandı → {ln[:120]}", file=sys.stderr)
    return rows, skipped


def read_json(path: Path) -> dict[str, Any]:
    """state.json / control.json. Yoksa veya yarım yazılmışsa boş sözlük + konsol notu."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{path} okunamadı ({exc}); bu turu boş geçiyorum.", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def write_control(patch: dict[str, Any]) -> dict[str, Any]:
    """control.json'u BİRLEŞTİREREK ve ATOMİK yaz.

    Ajan her turun başında bu dosyayı okuyor; yarım yazılmış JSON görmemeli. Geçici dosya +
    os.replace ile tek adımda yerine geçer. Birleştirme, mode yazarken flatten'ı (ve tersini)
    korur.
    """
    cur = read_json(CONTROL)
    merged = {"mode": cur.get("mode", "run"), "flatten": bool(cur.get("flatten", False))}
    merged.update(patch)
    tmp = CONTROL.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONTROL)
    return merged


def append_decision(row: dict[str, Any]) -> None:
    LOGS.mkdir(exist_ok=True)
    with DECISIONS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def now_ms() -> int:
    return int(time.time() * 1000)


def age_sec(ts_iso: str | None) -> float | None:
    """ISO zaman damgasının kaç saniye önce olduğunu ver."""
    if not ts_iso:
        return None
    try:
        return max(0.0, datetime.now(tz=CFG["tz"]).timestamp() - datetime.fromisoformat(ts_iso).timestamp())
    except ValueError:
        return None


# ----------------------------------------------------------------------------
# Türetmeler
# ----------------------------------------------------------------------------


def count_today(rows: list[dict[str, Any]], today: str) -> dict[str, int]:
    """Bugünün karar sayaçları. `ts` yerel ISO olduğu için tarih öneki karşılaştırması yeterli."""
    counts = {"total": 0, **{a: 0 for a in ACTIONS}, "OPERATOR": 0}
    for r in rows:
        if not str(r.get("ts", "")).startswith(today):
            continue
        counts["total"] += 1
        action = str(r.get("action", ""))
        if action.startswith("OPERATOR_"):
            counts["OPERATOR"] += 1
        elif action in counts:
            counts[action] += 1
    return counts


def derive_regime(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rejim rozeti. `state.json` rejimi taşımıyor, karar akışından okunur.

    Vol kesici (giriş yasağı) için de tek kaynak akış: ajan yasağı `gate="volatility"` satırıyla
    logluyor ama `vol_ban_until_ms`'i state'e yazmıyor. Yasağın bitişi bu yüzden o satırın
    zamanı + config.regime.vol_ban_sec olarak hesaplanır — SINIR: ajan yeniden başlarsa
    yasak bellekte sıfırlanır, burada süre dolana kadar sarı görünmeye devam eder.
    """
    level = "MEAN_REVERSION"
    for r in reversed(rows):
        if r.get("regime"):
            level = str(r["regime"])
            break

    ban = False
    reason = ""
    for r in reversed(rows):
        if r.get("gate") == "volatility":
            left = CFG["vol_ban_sec"] - (age_sec(r.get("ts")) or CFG["vol_ban_sec"])
            if left > 0:
                ban, reason = True, f"{r.get('reason', 'vol kesici')} ({int(left // 60)} dk kaldı)"
            break

    if level == "CASH":
        for r in reversed(rows):
            if r.get("gate") == "regime" and r.get("reason"):
                reason = str(r["reason"])
                break
    return {"level": level, "entry_ban": ban, "reason": reason}


def derive_kill(state: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    """İki ayrı durdurma sebebi, tek gösterge.

    `state.kill_switch` = günlük zarar kill'i (kalıcı risk kararı, eşik config.yaml'da).
    `control.mode == "kill"` = operatör Acil Durdur'u (süreç kararı, yeniden başlatılabilir).
    Hotfix öncesi ikisi aynı bayrağa yazılıyordu; artık karışamazlar.
    """
    reasons: list[str] = []
    detail: list[str] = []
    if state.get("kill_switch"):
        reasons.append("daily_loss")
        detail.append(f"günlük zarar kill switch'i (eşik {CFG['kill_switch_daily_pct']}%)")
    if control.get("mode") == "kill":
        reasons.append("operator")
        detail.append("operatör Acil Durdur")
    return {
        "active": bool(reasons),
        "reason": reasons[0] if reasons else None,
        "reasons": reasons,
        "detail": " + ".join(detail),
    }


def order_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Emir satırının özeti. Başarısız emir `ok: true` zarfının İÇİNDE saklanıyor (STATUS.md #19):
    gerçek sonuç `response.sCode`'da, `"0"` dışındaki her değer redde eşit.
    """
    resp = row.get("response") or {}
    scode = str(resp.get("sCode", "")) if isinstance(resp, dict) else ""
    ok = bool(row.get("ok")) and (scode in ("", "0"))
    req = row.get("request") or {}
    return {
        "ts": row.get("ts"),
        "symbol": row.get("symbol"),
        "action": row.get("action") or (req.get("side") if isinstance(req, dict) else None) or "place",
        "ok": ok,
        "s_code": scode,
        "s_msg": (resp.get("sMsg") if isinstance(resp, dict) else None) or row.get("error") or "",
        "ord_id": row.get("ord_id") or (resp.get("ordId") if isinstance(resp, dict) else None) or "",
        "dry_run": bool(row.get("dry_run")),
        "raw": row,
    }


# ----------------------------------------------------------------------------
# Uygulama
# ----------------------------------------------------------------------------

app = FastAPI(title="TERAZİ dashboard", docs_url=None, redoc_url=None)


@app.get("/")
def index() -> FileResponse:
    if not INDEX.exists():
        raise HTTPException(status_code=500, detail=f"{INDEX} bulunamadı (cwd={Path.cwd()})")
    return FileResponse(INDEX)


@app.get("/state")
def get_state() -> dict[str, Any]:
    state = read_json(STATE)
    control = read_json(CONTROL)
    rows, skipped = read_jsonl_tail(DECISIONS)

    last_turn_ms = state.get("last_turn_ms") or 0
    if not last_turn_ms and STATE.exists():
        last_turn_ms = int(STATE.stat().st_mtime * 1000)  # damga yoksa dosya mtime'ı
    state_age = (now_ms() - last_turn_ms) / 1000 if last_turn_ms else None

    last = rows[-1] if rows else None
    cooldown_ms = state.get("cooldown_until_ms") or 0
    cooldown_left = max(0, cooldown_ms - now_ms())

    return {
        "state": state,
        "control": {"mode": control.get("mode", "run"), "flatten": bool(control.get("flatten", False))},
        "agent_alive": state_age is not None and state_age <= CFG["stale_sec"],
        "state_age_sec": None if state_age is None else round(state_age, 1),
        "stale_sec": CFG["stale_sec"],
        "poll_sec": CFG["poll_sec"],
        "last_decision_ts": last.get("ts") if last else None,
        "last_decision_age_sec": round(age_sec(last.get("ts")) or 0, 0) if last else None,
        "regime": derive_regime(rows),
        "kill_switch": derive_kill(state, control),
        "cooldown": {
            "active": cooldown_left > 0,
            "until_ms": cooldown_ms,
            "minutes_left": cooldown_left // 60000,
            "consecutive_losses": state.get("consecutive_losses", 0),
        },
        "counts": count_today(rows, datetime.now(tz=CFG["tz"]).strftime("%Y-%m-%d")),
        "positions": state.get("positions", []),
        "pending": state.get("pending", []),
        "skipped_lines": skipped,
        "server_ms": now_ms(),
    }


@app.get("/feed")
def get_feed(n: int = 50) -> dict[str, Any]:
    n = max(1, min(n, 500))
    rows, skipped = read_jsonl_tail(DECISIONS, n)
    return {"rows": list(reversed(rows)), "skipped": skipped, "count": len(rows)}


@app.get("/orders")
def get_orders() -> dict[str, Any]:
    rows, skipped = read_jsonl_tail(ORDERS)
    return {"rows": [order_summary(r) for r in reversed(rows)], "skipped": skipped, "count": len(rows)}


class ControlBody(BaseModel):
    mode: str | None = None
    flatten: bool | None = None
    confirm: bool = False


@app.post("/control")
def post_control(body: ControlBody) -> dict[str, Any]:
    """Operatör yüzeyi: run / pause / kill / flatten. AL-SAT YOK.

    Her eylem `decisions.jsonl`'e OPERATOR_* satırı olarak düşer (§2 "görünmez müdahale yok").
    Ajan mode değişimini kendi satırıyla ayrıca loglar: dashboard satırı KOMUT, ajan satırı ONAY.
    """
    if body.mode is None and body.flatten is None:
        raise HTTPException(status_code=400, detail="Gövdede mode veya flatten olmalı.")
    if body.mode is not None and body.flatten is not None:
        raise HTTPException(status_code=400, detail="mode ve flatten aynı istekte gönderilemez.")

    if body.flatten is not None:
        if not body.flatten:
            raise HTTPException(status_code=400, detail="flatten yalnızca true olarak gönderilir.")
        action, patch = "OPERATOR_FLATTEN", {"flatten": True}
        reason = "dashboard: tüm açık pozisyonlar kapatılsın"
        needs_confirm = True
    else:
        mode = body.mode
        if mode not in MODES:
            raise HTTPException(status_code=400, detail=f"Geçersiz mode '{mode}'. Geçerli: {', '.join(MODES)}.")
        action, patch = f"OPERATOR_{mode.upper()}", {"mode": mode}
        reason = f"dashboard: control.json mode={mode}"
        needs_confirm = mode in CONFIRM_REQUIRED

    if needs_confirm and not body.confirm:
        raise HTTPException(
            status_code=400,
            detail=f"{action} için onay şart: gövdede \"confirm\": true gönderilmeli. "
                   "control.json'a hiçbir şey yazılmadı.",
        )

    # Karar satırı akıştaki diğer satırlarla aynı şekli taşısın diye state'ten doldurulur.
    state = read_json(STATE)
    rows, _ = read_jsonl_tail(DECISIONS, 1)
    append_decision({
        "ts": datetime.now(tz=CFG["tz"]).isoformat(timespec="seconds"),
        "action": action,
        "equity": state.get("equity", "0"),
        "daily_pnl_pct": state.get("daily_pnl_pct", 0.0),
        "open_positions": len(state.get("positions", [])),
        "regime": (rows[0].get("regime") if rows else None) or "MEAN_REVERSION",
        "transport": state.get("transport", "mcp"),
        "source": "dashboard",
        "reason": reason,
    })
    control = write_control(patch)
    return {"ok": True, "action": action, "control": control}


@app.exception_handler(HTTPException)
def http_error(_request: Any, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "detail": exc.detail})
