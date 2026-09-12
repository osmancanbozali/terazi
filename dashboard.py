"""TERAZİ dashboard — FastAPI, port 8787.

Ayrı süreç. Kaynak YALNIZCA dosyalar: logs/decisions.jsonl, logs/orders.jsonl, logs/micro.jsonl,
state.json, control.json. Burada MCP çağrısı YOK, borsaya temas YOK — ajan çökse bile dashboard
ayakta kalır, dashboard çökse bile ajan durmaz (docs/urun-mimari.md §3.1).

Yazdığı TEK dosya `control.json` (atomik). `decisions.jsonl`'e YAZMAZ: operatör eylemlerinin tek
kaynağı ajandır — ajan control.json'daki değişimi görünce OPERATOR_* satırını kendisi düşer (Faz 5).
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
MICRO = LOGS / "micro.jsonl"
LLM_LOG = LOGS / "llm.jsonl"
STATE = Path("state.json")
CONTROL = Path("control.json")
CONFIG = Path("config.yaml")
INDEX = Path("static/index.html")

# Dosyanın sonundan okunacak en büyük blok. Bir karar satırı ~400 bayt; 1 MB ≈ 2500 satır,
# yani n=50 isteği için fazlasıyla yeterli. Eşik değil, okuma tamponu.
TAIL_BYTES = 1_000_000

MODES = ("run", "pause", "kill")
CONFIRM_REQUIRED = ("kill", "flatten")

# Faz 6 uç varsayılanları. Eşik değil, pencere/çizim tavanı; `dashboard:` bloğuna taşınabilir
# (bkz. STATUS.md Faz 6 açık işleri) — blok yokken bunlar geçerli.
LLM_PANEL_ROWS = 5        # GET /llm varsayılanı (alt şeritteki kart 5 satır gösteriyor)
MICRO_WINDOW_MIN = 30     # GET /micro varsayılan pencere (strateji.md §4.3 medyan penceresi)
EQUITY_MAX_POINTS = 400   # equity eğrisinde çizilecek en fazla nokta (seyreltme tavanı)

# decisions.jsonl'de görülebilen action değerleri (docs/urun-mimari.md §3.3).
# OPERATOR_* tek kovada toplanır: ajan mode değişiminde OPERATOR_RUN yazarken spec
# OPERATOR_RESUME diyor, ayrıca OPERATOR_KILL_CLEARED var — hepsi aynı sayaca girer.
ACTIONS = ("WAIT", "SETUP", "CANDIDATE", "REJECT", "ORDER", "FILL", "EXIT", "CASH", "ERROR",
           "EOD_FLATTEN_DONE")  # gün sonu kapanışı operatör eylemi DEĞİL, kendi sayacı var (Faz 7)


# ----------------------------------------------------------------------------
# Yapılandırma — sayısal eşik koda gömülmez (CLAUDE.md)
# ----------------------------------------------------------------------------


def load_cfg() -> dict[str, Any]:
    """config.yaml SALT OKUNUR. Dashboard buradan yalnızca okur, asla yazmaz.

    `dashboard:` bloğu: `poll_ms` (yenileme) ve `alive_threshold_s` (bayatlık). Blok yoksa spec
    değerlerine düşülür (docs/urun-mimari.md §4: 2 sn polling, 60 sn bayatlık).
    """
    try:
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"config.yaml okunamadı ({exc}); varsayılanlarla devam.", file=sys.stderr)
        cfg = {}
    dash = cfg.get("dashboard") or {}
    return {
        "tz": ZoneInfo((cfg.get("execution") or {}).get("timezone", "Europe/Istanbul")),
        "kill_switch_daily_pct": (cfg.get("risk") or {}).get("kill_switch_daily_pct", -1.5),
        "poll_sec": float(dash.get("poll_ms", 2000)) / 1000.0,
        "stale_sec": float(dash.get("alive_threshold_s", 60)),
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


def derive_regime(rows: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    """Rejim rozeti. Seviye karar akışından (son satırın `regime` alanı); giriş yasağı
    `state.vol_ban_until_ms`'ten (Faz 5: ajan yazıyor, akıştan süre hesabı kalktı). Gerekçe
    metni son `gate="volatility"` satırından."""
    level = "MEAN_REVERSION"
    for r in reversed(rows):
        if r.get("regime"):
            level = str(r["regime"])
            break

    ban = False
    reason = ""
    until = int(state.get("vol_ban_until_ms") or 0)
    left_ms = until - now_ms()
    if left_ms > 0:
        ban = True
        reason = f"vol kesici ({left_ms // 60000} dk kaldı)"
        for r in reversed(rows):
            if r.get("gate") == "volatility":
                reason = f"{r.get('reason', 'vol kesici')} ({left_ms // 60000} dk kaldı)"
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


def to_float(value: Any) -> float | None:
    """Log alanları string gelir (fiyat/equity hassasiyeti için). Çizim için float gerekiyor;
    boş string ve None sessizce None olur, çizgi orada kopar."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def llm_summary(row: dict[str, Any]) -> dict[str, Any]:
    """`llm.jsonl` satırı → panel satırı. İki görev tek kartta: `judge` verdict taşır,
    `regime` view + güven taşır. `status` ok / fallback / failed_open olarak renklenir."""
    out = row.get("output") or {}
    if not isinstance(out, dict):
        out = {}
    return {
        "ts": row.get("ts"),
        "task": row.get("task"),
        "symbol": row.get("symbol"),
        "model": row.get("model"),
        "status": row.get("status"),
        "latency_ms": row.get("latency_ms"),
        "verdict": out.get("decision"),
        "size_multiplier": out.get("size_multiplier"),
        "news_risk": out.get("news_risk"),
        "view": out.get("view"),
        "confidence": out.get("confidence"),
        "conflict": bool(out.get("conflict")),
        "text": out.get("reason") or out.get("note") or "",
        "missing_inputs": row.get("missing_inputs") or out.get("missing_inputs") or [],
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
        "regime": derive_regime(rows, state),
        "regime_commentary": state.get("regime_commentary"),
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


@app.get("/llm")
def get_llm(n: int = LLM_PANEL_ROWS) -> dict[str, Any]:
    """LLM paneli: `llm.jsonl` son n satırı, EN YENİ ÖNCE. `attempts` ve `input_summary` kırpılır —
    panel verdict/view, status ve gecikmeyi gösteriyor, ham girdi özetini göstermiyor."""
    n = max(1, min(n, 50))
    rows, skipped = read_jsonl_tail(LLM_LOG, n)
    return {"rows": [llm_summary(r) for r in reversed(rows)], "skipped": skipped,
            "count": len(rows)}


@app.get("/equity")
def get_equity() -> dict[str, Any]:
    """Equity eğrisi. Kaynak `decisions.jsonl`: her satırda `equity` var (string!). Ardışık aynı
    değerler seyreltilir — 30 USDT'lik hesapta yüzlerce satır aynı sayıyı taşıyor."""
    rows, skipped = read_jsonl_tail(DECISIONS)
    state = read_json(STATE)

    points: list[dict[str, Any]] = []
    last: float | None = None
    pending: dict[str, Any] | None = None  # düz kesimin son noktası
    for r in rows:
        val = to_float(r.get("equity"))
        ts = r.get("ts")
        if val is None or not ts:
            continue
        point = {"ts": ts, "equity": val}
        if last is None or val != last:
            if pending is not None:
                points.append(pending)  # düz kesimin İKİ ucu da çizilir, ortası atılır
                pending = None
            points.append(point)
            last = val
        else:
            pending = point
    if pending is not None:
        points.append(pending)

    if len(points) > EQUITY_MAX_POINTS:  # çok nokta → eşit aralıklı seyreltme, son nokta korunur
        step = len(points) / EQUITY_MAX_POINTS
        thin = [points[int(i * step)] for i in range(EQUITY_MAX_POINTS)]
        if thin[-1] is not points[-1]:
            thin.append(points[-1])
        points = thin

    return {"points": points, "count": len(points),
            "day_start_equity": to_float(state.get("day_start_equity")),
            "daily_pnl_pct": state.get("daily_pnl_pct"), "skipped": skipped}


@app.get("/micro")
def get_micro(minutes: int = MICRO_WINDOW_MIN) -> dict[str, Any]:
    """Mikro sparkline'lar: `micro.jsonl`'in son `minutes` dakikası, parite başına OBI ve
    spread_bps serisi (strateji.md §4.3 — bu katman 20 sn'de bir örnekliyor)."""
    minutes = max(1, min(minutes, 240))
    rows, skipped = read_jsonl_tail(MICRO)
    cutoff = datetime.now(tz=CFG["tz"]).timestamp() - minutes * 60

    series: dict[str, dict[str, list[Any]]] = {}
    for r in rows:
        sym = str(r.get("symbol") or "")
        age = age_sec(r.get("ts"))
        if not sym or age is None or age > minutes * 60:
            continue
        s = series.setdefault(sym, {"ts": [], "obi": [], "spread_bps": []})
        s["ts"].append(r.get("ts"))
        s["obi"].append(to_float(r.get("obi")))
        s["spread_bps"].append(to_float(r.get("spread_bps")))

    out = {sym: {**s, "last_obi": s["obi"][-1] if s["obi"] else None,
                 "last_spread_bps": s["spread_bps"][-1] if s["spread_bps"] else None,
                 "samples": len(s["ts"])}
           for sym, s in series.items()}
    return {"minutes": minutes, "cutoff_ts": cutoff, "pairs": out, "skipped": skipped}


class ControlBody(BaseModel):
    mode: str | None = None
    flatten: bool | None = None
    confirm: bool = False


@app.post("/control")
def post_control(body: ControlBody) -> dict[str, Any]:
    """Operatör yüzeyi: run / pause / kill / flatten. AL-SAT YOK.

    Yalnızca `control.json` yazılır. OPERATOR_* satırını `decisions.jsonl`'e AJAN düşer (tek kaynak);
    dashboard log yazmaz — görünmez müdahale yok, çift satır da yok.
    """
    if body.mode is None and body.flatten is None:
        raise HTTPException(status_code=400, detail="Gövdede mode veya flatten olmalı.")
    if body.mode is not None and body.flatten is not None:
        raise HTTPException(status_code=400, detail="mode ve flatten aynı istekte gönderilemez.")

    if body.flatten is not None:
        if not body.flatten:
            raise HTTPException(status_code=400, detail="flatten yalnızca true olarak gönderilir.")
        action, patch = "OPERATOR_FLATTEN", {"flatten": True}
        needs_confirm = True
    else:
        mode = body.mode
        if mode not in MODES:
            raise HTTPException(status_code=400, detail=f"Geçersiz mode '{mode}'. Geçerli: {', '.join(MODES)}.")
        action, patch = f"OPERATOR_{mode.upper()}", {"mode": mode}
        needs_confirm = mode in CONFIRM_REQUIRED

    if needs_confirm and not body.confirm:
        raise HTTPException(
            status_code=400,
            detail=f"{action} için onay şart: gövdede \"confirm\": true gönderilmeli. "
                   "control.json'a hiçbir şey yazılmadı.",
        )

    control = write_control(patch)
    return {"ok": True, "action": action, "control": control}


# ----------------------------------------------------------------------------
# "Ajana sor" — ask.py TEMBEL import edilir
# ----------------------------------------------------------------------------
#
# ask.py `anthropic`, `judge`, `terazi` ve `tools`'u çekiyor. Bu zincirde bir sorun varsa
# dashboard'un geri kalanı (karar akışı, kontroller) ETKİLENMEMELİ — ajan çökse bile ayakta kalma
# ilkesinin ikizi (docs/urun-mimari.md §3.1). Bu yüzden import ilk /ask isteğinde yapılır ve
# düşerse yalnızca bu uç 503 döner.

_ask_mod: Any = None
_ask_error: str | None = None

QUESTION_MAX_CHARS = 600   # ask.py ile aynı tavan; burada erken 400 vermek için
HISTORY_MAX_MESSAGES = 20  # gövde şişirme koruması; ask.py zaten son 6'yı gönderiyor


def load_ask() -> Any:
    global _ask_mod, _ask_error
    if _ask_mod is None and _ask_error is None:
        try:
            import ask  # noqa: PLC0415 — bilerek tembel

            _ask_mod = ask
        except Exception as exc:  # noqa: BLE001 — import zincirinin tamamı
            _ask_error = f"{type(exc).__name__}: {exc}"
            print(f"ask.py yüklenemedi: {_ask_error}", file=sys.stderr)
    return _ask_mod


class AskMessage(BaseModel):
    role: str = "user"
    content: str = ""


class AskBody(BaseModel):
    question: str
    history: list[AskMessage] = []


@app.post("/ask")
async def post_ask(body: AskBody) -> dict[str, Any]:
    """Salt okunur sohbet. Emir vermez, config değiştirmez, control.json'a dokunmaz."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Soru boş.")
    if len(question) > QUESTION_MAX_CHARS:
        raise HTTPException(status_code=400,
                            detail=f"Soru çok uzun ({len(question)} > {QUESTION_MAX_CHARS} karakter).")

    mod = load_ask()
    if mod is None:
        raise HTTPException(status_code=503,
                            detail=f"Sohbet katmanı yüklenemedi: {_ask_error}")

    history = [{"role": m.role, "content": m.content}
               for m in body.history[-HISTORY_MAX_MESSAGES:] if m.content.strip()]
    try:
        return await mod.answer(question, history)
    except Exception as exc:  # noqa: BLE001 — ask.answer istisna fırlatmamalı; fırlatırsa 500
        print(f"/ask beklenmeyen hata: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise HTTPException(status_code=500,
                            detail=f"Sohbet hatası: {type(exc).__name__}: {exc}") from exc


@app.exception_handler(HTTPException)
def http_error(_request: Any, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "detail": exc.detail})
