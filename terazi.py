"""Terazi — ajan döngüsü (docs/urun-mimari.md §3.3). Tek dosya.

Karar mantığı `calibrate.py`'den IMPORT edilir (`SetupTracker`, `Bar`, `add_indicators`) —
canlı ile backtest'in sapması imkânsız olsun diye. Sayısal hiçbir eşik burada değil; hepsi
`config.yaml`'da (CLAUDE.md kuralı).

Emre giden tek yol: sinyal → mikro teyit → maliyet kapısı → LLM yargıç (judge.py) → risk kapısı → emir.
Bu sırayı atlayan kod yok; `_place_entry` / `close_now` dışında `tools.place_order` çağrılmaz.
Yargıç maliyet kapısından SONRA: maliyet adayların çoğunu eler, elenen aday için LLM çağrılmaz (Faz 5).

Kayıt disiplini (Faz 5): decisions.jsonl'e 20 sn'lik kalp atışı GİRMEZ (state.json last_tick_ts);
yalnızca 15m değerlendirmeleri (parite başına sayısal gerekçeli WAIT), SETUP/CANDIDATE/REJECT/ORDER/
FILL/EXIT/ERROR, rejim değişimi, operatör eylemleri (tek kaynak: ajan) ve LLM verdict özeti.

Çalıştırma:
    .venv/bin/python terazi.py --profile hackathon --dry-run --max-turns 3
    .venv/bin/python terazi.py --profile hackathondemo --demo
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

from calibrate import Bar, Ev, SetupTracker, add_indicators
from judge import Judge, Verdict
from tools import BAR_MS, OkxTools, OkxToolError, SafetyGateError

LOGS = Path("logs")
DECISIONS = LOGS / "decisions.jsonl"
ORDERS = LOGS / "orders.jsonl"
MICRO = LOGS / "micro.jsonl"
STATE = Path("state.json")
CONTROL = Path("control.json")

TRANSPORT = "mcp"  # başlangıç aktarımı; Faz 7'den beri çalışma anında değişir (CLI yedeği)


# ----------------------------------------------------------------------------
# Yapılandırma — config.yaml tek sayısal gerçek kaynağı
# ----------------------------------------------------------------------------


class Cfg(dict):
    """Nokta erişimli sözlük: cfg.risk.max_concurrent. Şema pydantic değil çünkü
    config.yaml'ın tamamı bilinçli olarak serbest; eksik anahtar KeyError ile patlar."""

    def __getattr__(self, key: str) -> Any:
        try:
            val = self[key]
        except KeyError as exc:
            raise AttributeError(f"config.yaml'da '{key}' yok") from exc
        return Cfg(val) if isinstance(val, dict) else val


def load_config(path: str) -> Cfg:
    with open(path, encoding="utf-8") as fh:
        return Cfg(yaml.safe_load(fh))


# ----------------------------------------------------------------------------
# Zaman ve kayıt
# ----------------------------------------------------------------------------


def now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def jsonable(obj: Any) -> Any:
    """Decimal ve numpy skalerlerini JSON'a çevirir. Fiyatlar string kalır (hassasiyet)."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(jsonable(row), ensure_ascii=False, default=str) + "\n")


def parse_hhmm(text: str) -> dtime:
    hh, mm = text.split(":")
    return dtime(int(hh), int(mm))


def fmt_px(value: float) -> str:
    """Fiyatı Türkçe okunur yaz: 76.000–79.900 (binlik nokta, ≥1000'de ondalıksız); küçükte 4 anlamlı."""
    if abs(value) >= 1000:
        return f"{value:,.0f}".replace(",", ".")
    return f"{value:.4g}"


# ----------------------------------------------------------------------------
# Mikro yapı — OBI, TFI, spread
# ----------------------------------------------------------------------------


def book_top(book: dict[str, Any]) -> tuple[Decimal, Decimal] | None:
    """(best_bid, best_ask). Defter tek taraflıysa None."""
    bids, asks = book.get("bids") or [], book.get("asks") or []
    if not bids or not asks:
        return None
    return Decimal(str(bids[0][0])), Decimal(str(asks[0][0]))


def spread_bps(book: dict[str, Any]) -> float | None:
    top = book_top(book)
    if top is None:
        return None
    bid, ask = top
    mid = (bid + ask) / 2
    return float((ask - bid) / mid * 10_000) if mid else None


def obi(book: dict[str, Any], band_bps: float) -> float | None:
    """Emir defteri dengesizliği: orta fiyatın ±band'ındaki alış/satış miktar farkı, −1..+1."""
    top = book_top(book)
    if top is None:
        return None
    bid, ask = top
    mid = (bid + ask) / 2
    band = mid * Decimal(str(band_bps)) / Decimal(10_000)
    lo, hi = mid - band, mid + band
    buy = sum(Decimal(str(sz)) for px, sz, *_ in book["bids"] if Decimal(str(px)) >= lo)
    sell = sum(Decimal(str(sz)) for px, sz, *_ in book["asks"] if Decimal(str(px)) <= hi)
    total = buy + sell
    return float((buy - sell) / total) if total else 0.0


def tfi(trades: list[dict[str, Any]], window_sec: int) -> float | None:
    """İşlem akışı dengesizliği: son `window_sec` içinde taker alım/satım hacmi farkı, −1..+1.

    `side` agresörün yönü (docs/mcp-araclari.md §4.7).
    """
    if not trades:
        return None
    newest = max(int(t["ts"]) for t in trades)
    cutoff = newest - window_sec * 1000
    buy = sell = Decimal(0)
    for t in trades:
        if int(t["ts"]) < cutoff:
            continue
        sz = Decimal(str(t["sz"]))
        if t["side"] == "buy":
            buy += sz
        else:
            sell += sz
    total = buy + sell
    return float((buy - sell) / total) if total else 0.0


class SpreadWindow:
    """Parite başına kayan spread penceresi; maliyet kapısı ve mikro teyit medyanı buradan.

    Medyan yoksa çağıran `spread_bps_fallback`'e düşer ve BUNU LOGLAR.
    """

    def __init__(self, window_sec: int) -> None:
        self._window_ms = window_sec * 1000
        self._samples: deque[tuple[int, float]] = deque()

    def push(self, ts_ms: int, value: float) -> None:
        self._samples.append((ts_ms, value))
        cutoff = ts_ms - self._window_ms
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def median(self) -> float | None:
        return statistics.median(v for _, v in self._samples) if self._samples else None

    def __len__(self) -> int:
        return len(self._samples)


# ----------------------------------------------------------------------------
# Fiyat / miktar yuvarlama — hepsi Decimal, API'ye string gider
# ----------------------------------------------------------------------------


def q_px(px: Decimal, tick: Decimal) -> Decimal:
    """Fiyatı tickSz'a yuvarla (en yakın). Emirde tick ihlali doğrudan red demek."""
    return (px / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick


def q_sz(sz: Decimal, lot: Decimal) -> Decimal:
    """Miktarı lotSz'a AŞAĞI yuvarla — yukarı yuvarlamak bakiyeyi aşabilir."""
    return (sz / lot).quantize(Decimal(1), rounding=ROUND_DOWN) * lot


def dstr(value: Decimal) -> str:
    """Decimal'i bilimsel gösterim olmadan string'e çevir (API 1E-8 kabul etmez)."""
    return format(value.normalize(), "f")


# ----------------------------------------------------------------------------
# Rejim ve kapılar
# ----------------------------------------------------------------------------


@dataclass
class Regime:
    level: Literal["MEAN_REVERSION", "CASH"] = "MEAN_REVERSION"
    range_low: float = 0.0
    range_high: float = 0.0
    reason: str = "başlangıç"
    computed_ms: int = 0
    vol_ban_until_ms: int = 0

    def entries_allowed(self, now: int) -> tuple[bool, str]:
        if self.level == "CASH":
            return False, f"rejim CASH: {self.reason}"
        if now < self.vol_ban_until_ms:
            return False, "vol kesici: 30 dk giriş yasağı"
        return True, ""


def fee_usdt(pair: str, fill: dict[str, Any]) -> Decimal:
    """Bir dolumun komisyonunu USDT'ye çevir.

    OKX komisyonu NEGATİF yazar ve ALIŞTA BAZ PARADAN keser — 12 Eylül'de demo hesaptaki gerçek
    dolumlarla ölçüldü, tahmin değil:
      alış : feeCcy="SOL"  fee="-0.000117889"  → USDT = 0.000117889 × fillPx
      satış: feeCcy="USDT" fee="-0.01199615406" → USDT = 0.01199615406
    Tanınmayan komisyon parasında 0 döner (net PnL'i uydurmaktansa eksik bırak).
    """
    fee = abs(Decimal(str(fill.get("fee") or 0)))
    if fee == 0:
        return Decimal(0)
    ccy, (base, quote) = str(fill.get("feeCcy") or ""), pair.split("-")
    if ccy == quote:
        return fee
    if ccy == base:
        return fee * Decimal(str(fill.get("fillPx") or 0))
    return Decimal(0)


def fill_totals(pair: str, fills: list[dict[str, Any]]) -> tuple[Decimal, Decimal, Decimal]:
    """Dolum listesinden (toplam miktar, ağırlıklı ortalama fiyat, komisyon USDT)."""
    total = cost = fee = Decimal(0)
    for f in fills:
        sz = Decimal(str(f.get("fillSz") or 0))
        total += sz
        cost += sz * Decimal(str(f.get("fillPx") or 0))
        fee += fee_usdt(pair, f)
    return total, (cost / total if total else Decimal(0)), fee


def cost_gate(target_bps: float, fee_bps: float, spread: float, mult: float) -> tuple[bool, str]:
    cost = 2 * fee_bps + spread
    need = mult * cost
    ok = target_bps >= need
    return ok, f"hedef {target_bps:.1f}bps {'≥' if ok else '<'} {mult:g}×maliyet {cost:.1f}bps = {need:.1f}bps"


# ----------------------------------------------------------------------------
# Durum
# ----------------------------------------------------------------------------


@dataclass
class Position:
    pair: str
    ord_id: str
    cl_ord_id: str
    entry_px: Decimal
    sz: Decimal  # gerçek dolan baz miktar (fills'ten)
    target: Decimal
    stop: Decimal
    opened_ms: int
    bars_held: int = 0
    algo_id: str | None = None
    fee_paid: Decimal = Decimal(0)  # girişte ödenen komisyon, USDT (Faz 7)

    def to_json(self) -> dict[str, Any]:
        return {
            "pair": self.pair, "ord_id": self.ord_id, "cl_ord_id": self.cl_ord_id,
            "entry_px": str(self.entry_px), "sz": str(self.sz),
            "target": str(self.target), "stop": str(self.stop),
            "opened_ms": self.opened_ms, "bars_held": self.bars_held, "algo_id": self.algo_id,
            "fee_paid": str(self.fee_paid),
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Position":
        return cls(
            pair=d["pair"], ord_id=d["ord_id"], cl_ord_id=d.get("cl_ord_id", ""),
            entry_px=Decimal(d["entry_px"]), sz=Decimal(d["sz"]),
            target=Decimal(d["target"]), stop=Decimal(d["stop"]),
            opened_ms=d["opened_ms"], bars_held=d.get("bars_held", 0), algo_id=d.get("algo_id"),
            fee_paid=Decimal(d.get("fee_paid", "0")),
        )


@dataclass
class PendingOrder:
    """Gönderilmiş ama dolmamış limit alış. TTL dolunca iptal edilir."""

    pair: str
    ord_id: str
    cl_ord_id: str
    px: Decimal
    sz: Decimal
    target: Decimal
    stop: Decimal
    placed_ms: int

    def to_json(self) -> dict[str, Any]:
        return {
            "pair": self.pair, "ord_id": self.ord_id, "cl_ord_id": self.cl_ord_id,
            "px": str(self.px), "sz": str(self.sz), "target": str(self.target),
            "stop": str(self.stop), "placed_ms": self.placed_ms,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "PendingOrder":
        return cls(
            pair=d["pair"], ord_id=d["ord_id"], cl_ord_id=d.get("cl_ord_id", ""),
            px=Decimal(d["px"]), sz=Decimal(d["sz"]), target=Decimal(d["target"]),
            stop=Decimal(d["stop"]), placed_ms=d["placed_ms"],
        )


@dataclass
class State:
    # Profil damgası: bu durumun HANGİ hesaba ait olduğu. Uyuşmazlık tespiti buna bakar.
    profile: str = ""
    demo: bool | None = None
    positions: list[Position] = field(default_factory=list)
    pending: list[PendingOrder] = field(default_factory=list)
    day_start_equity: Decimal | None = None
    equity: Decimal = Decimal(0)
    daily_pnl_pct: float = 0.0
    consecutive_losses: int = 0
    cooldown_until_ms: int = 0
    daily_trades: int = 0
    kill_switch: bool = False
    last_turn_ms: int = 0
    last_tick_ts: str = ""  # kalp atışı (Faz 5): decisions.jsonl yerine burada
    last_signal_bar_ts: int = 0
    trade_day: str = ""
    transport: str = TRANSPORT
    vol_ban_until_ms: int = 0  # dashboard sarı rozeti buradan okur (Faz 5)
    regime_commentary: dict[str, Any] | None = None  # LLM rejim yorumu (30 dk)
    # Kapanan işlemler, en yeni SONDA; komisyonlu net PnL ile (Faz 7). Dashboard kartı buradan okur.
    closed_positions: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "demo": self.demo,
            "positions": [p.to_json() for p in self.positions],
            "pending": [p.to_json() for p in self.pending],
            "day_start_equity": None if self.day_start_equity is None else str(self.day_start_equity),
            "equity": str(self.equity),
            "daily_pnl_pct": self.daily_pnl_pct,
            "consecutive_losses": self.consecutive_losses,
            "cooldown_until_ms": self.cooldown_until_ms,
            "daily_trades": self.daily_trades,
            "kill_switch": self.kill_switch,
            "last_turn_ms": self.last_turn_ms,
            "last_tick_ts": self.last_tick_ts,
            "last_signal_bar_ts": self.last_signal_bar_ts,
            "trade_day": self.trade_day,
            "transport": self.transport,
            "vol_ban_until_ms": self.vol_ban_until_ms,
            "regime_commentary": self.regime_commentary,
            "closed_positions": self.closed_positions,
        }

    @classmethod
    def load(cls) -> "State":
        if not STATE.exists():
            return cls()
        d = json.loads(STATE.read_text(encoding="utf-8"))
        st = cls(
            profile=d.get("profile", ""),
            demo=d.get("demo"),
            positions=[Position.from_json(p) for p in d.get("positions", [])],
            pending=[PendingOrder.from_json(p) for p in d.get("pending", [])],
            equity=Decimal(d.get("equity", "0")),
            daily_pnl_pct=d.get("daily_pnl_pct", 0.0),
            consecutive_losses=d.get("consecutive_losses", 0),
            cooldown_until_ms=d.get("cooldown_until_ms", 0),
            daily_trades=d.get("daily_trades", 0),
            kill_switch=d.get("kill_switch", False),
            last_turn_ms=d.get("last_turn_ms", 0),
            last_signal_bar_ts=d.get("last_signal_bar_ts", 0),
            trade_day=d.get("trade_day", ""),
            vol_ban_until_ms=int(d.get("vol_ban_until_ms") or 0),
            regime_commentary=d.get("regime_commentary"),
            closed_positions=list(d.get("closed_positions") or []),
        )
        dse = d.get("day_start_equity")
        st.day_start_equity = Decimal(dse) if dse else None
        return st

    def save(self) -> None:
        STATE.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")


def archive_if_profile_changed(profile: str, demo: bool | None) -> dict[str, Any] | None:
    """Profil/demo değiştiyse `state.json`'ı ve `logs/*.jsonl`'i arşivle, sıfırdan başla.

    NEDEN: demo testinin gün başı equity'si (≈100.000 USDT) canlı hesaba (30 USDT) taşınırsa
    `daily_pnl_pct` −99,97 olur ve kill switch fiilen kilitlenir — ajan canlıda hiç işlem
    açamaz. Aynı şekilde demo emirleri canlı `orders.jsonl`'e karışırsa karar günlüğü yalan söyler.
    Bu yüzden uyuşmazlık bir hata değil, TEMİZLİK TETİĞİ'dir: eskisi saklanır, yenisi temiz başlar.

    Damga yoksa (Faz 2 öncesi state) uyuşmazlık sayılır — güvenilmeyen durum taşınmaz.
    Döndürdüğü sözlük `decisions.jsonl`'e loglanır; None = temizlik gerekmedi.
    """
    if not STATE.exists():
        return None
    try:
        raw = json.loads(STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = {}
    old_profile = raw.get("profile") or ""
    old_demo = raw.get("demo")
    if old_profile == profile and old_demo == demo:
        return None  # aynı hesap, durum taşınır

    label = old_profile or ("demo" if old_demo else "unknown")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    state_archive = Path(f"state.{label}-{ts}.json")
    STATE.rename(state_archive)

    log_archive = LOGS / "archive" / f"{label}-{ts}"
    moved: list[str] = []
    for path in sorted(LOGS.glob("*.jsonl")):
        log_archive.mkdir(parents=True, exist_ok=True)
        path.rename(log_archive / path.name)
        moved.append(path.name)

    return {
        "old_profile": old_profile or "(damgasız)",
        "old_demo": old_demo,
        "new_profile": profile,
        "new_demo": demo,
        "state_archive": str(state_archive),
        "log_archive": str(log_archive) if moved else None,
        "logs_moved": moved,
    }


def read_control() -> dict[str, Any]:
    """control.json'u oku; yoksa varsayılanla oluştur (dashboard henüz yazmıyorsa)."""
    default = {"mode": "run", "flatten": False}
    if not CONTROL.exists():
        CONTROL.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return default
    try:
        data = json.loads(CONTROL.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default  # dashboard yarı yazmış olabilir; bu turu varsayılanla geç
    return {"mode": data.get("mode", "run"), "flatten": bool(data.get("flatten", False))}


def write_control(patch: dict[str, Any]) -> dict[str, Any]:
    """control.json'u BİRLEŞTİREREK ve ATOMİK yaz (dashboard ile aynı disiplin: geçici dosya + os.replace).

    Ajan yalnızca iki durumda yazar: açılışta mode=kill'i tüketirken ve flatten yürütüldükten sonra
    bayrağı düşürürken. Operatör komutu vermez; verilen komutu tüketir.
    """
    cur = read_control()
    merged = {"mode": cur["mode"], "flatten": cur["flatten"]}
    merged.update(patch)
    tmp = CONTROL.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONTROL)
    return merged


# ----------------------------------------------------------------------------
# Ajan
# ----------------------------------------------------------------------------


class Agent:
    def __init__(self, cfg: Cfg, tools: OkxTools, args: argparse.Namespace) -> None:
        self.cfg = cfg
        self.t = tools
        self.args = args
        self.tz = ZoneInfo(cfg.execution.timezone)
        # Durum `startup()` içinde yüklenir: profil/demo uyuşmazlığı önce arşivlenmeli.
        self.state = State()
        self.regime = Regime()
        self.pairs: list[str] = []
        self.inst: dict[str, dict[str, Decimal]] = {}  # pair → tickSz/lotSz/minSz
        self.trackers: dict[str, SetupTracker] = {}
        self.spreads: dict[str, SpreadWindow] = {}
        self.micro_last: dict[str, dict[str, Any]] = {}
        self.fee_bps: float = 0.0
        self.last_reconcile_ms = 0
        self.turn = 0
        self.judge = Judge(cfg, tools)  # LLM katmanı; llm.enabled=false ise pass-through
        self._h1_bars: list[dict[str, Any]] = []  # rejim yorumcusu için son 1H mumlar
        self._last_mode = "run"
        self._last_flatten = False

    # ---- kayıt yardımcıları ----

    def decide(self, action: str, **fields: Any) -> None:
        """decisions.jsonl'e §3.3 şemasıyla bir satır. WAIT dahil her tur en az bir satır."""
        row = {
            "ts": datetime.now(tz=self.tz).isoformat(timespec="seconds"),
            "action": action,
            "equity": self.state.equity,
            "daily_pnl_pct": round(self.state.daily_pnl_pct, 4),
            "open_positions": len(self.state.positions),
            "regime": self.regime.level,
            "transport": self.t.last_transport,  # son araç çağrısının aktarımı (Faz 7)
        }
        row.update(fields)
        append_jsonl(DECISIONS, row)

    def order_log(self, **fields: Any) -> None:
        """Her emir denemesi, BAŞARISIZLAR DAHİL (strateji.md §5)."""
        append_jsonl(ORDERS, {"ts": datetime.now(tz=self.tz).isoformat(timespec="seconds"), **fields})

    # ---- açılış ----

    async def startup(self) -> None:
        caps_demo = None
        fee = await self.t.get_trade_fee("SPOT")
        caps_demo = self.t.demo
        self.fee_bps = float(abs(Decimal(str(fee["maker"])))) * 10_000  # NEGATİF gelir; abs şart
        print(f"profil={self.t.profile} capabilities.demo={caps_demo} "
              f"expected_demo={self.args.expected_demo} dry_run={self.t.dry_run}")
        print(f"maker={fee['maker']} → abs={self.fee_bps:.1f} bps · "
              f"maliyet={2 * self.fee_bps + self.cfg.micro.spread_bps_fallback:.1f} bps")

        # demo_test SERT KAPI: canlıda çalışması imkânsız.
        if self.cfg.demo_test.enabled and caps_demo is not True:
            raise SystemExit(
                f"demo_test.enabled=true ama capabilities.demo={caps_demo}. "
                "Bu blok SADECE demo profilinde çalışır. Başlatma reddedildi."
            )
        if self.cfg.demo_test.enabled:
            print(f"UYARI: demo_test AÇIK — {self.cfg.demo_test.pair} için sentetik aday "
                  f"üretilecek (hiçbir kapı atlanmıyor).")

        # Profil/demo uyuşmazlığı → eski durumu ve logları arşivle. `capabilities.demo`
        # bilinmeden yapılamaz, bu yüzden durum BURADA yüklenir (__init__'te değil).
        archived = archive_if_profile_changed(self.t.profile, caps_demo)
        self.state = State.load()
        self.state.profile = self.t.profile
        self.state.demo = caps_demo
        # Vol kesici yasağı süreç ömrünü aşar: state'te duruyorsa yeniden başlatma onu SIFIRLAMAZ
        # (Faz 4'te dashboard bunu akıştan tahmin etmek zorundaydı; artık tek kaynak state).
        self.regime.vol_ban_until_ms = self.state.vol_ban_until_ms
        if archived:
            print(f"PROFİL DEĞİŞTİ: {archived['old_profile']} (demo={archived['old_demo']}) → "
                  f"{self.t.profile} (demo={caps_demo})")
            print(f"  durum arşivi: {archived['state_archive']}")
            if archived["log_archive"]:
                print(f"  log arşivi:   {archived['log_archive']} "
                      f"({', '.join(archived['logs_moved'])})")
            self.decide(
                "ERROR", gate="state_profile_mismatch",
                reason=f"state.json/loglar {archived['old_profile']} (demo={archived['old_demo']}) "
                       f"hesabına aitti, çalışma anı {self.t.profile} (demo={caps_demo}). "
                       f"Durum YOK SAYILDI, sıfırdan başlanıyor; gün başı equity canlı "
                       f"bakiyeden alınacak.",
                state_archive=archived["state_archive"], log_archive=archived["log_archive"],
                logs_moved=archived["logs_moved"],
            )

        # Evren doğrulaması gerçek boyutla çalışsın diye equity ÖNCE okunur.
        await self.refresh_equity()
        await self._validate_universe()

        # Her paritenin kendi takipçisi; canlı ile kalibrasyon aynı sınıf.
        dt = self.cfg.demo_test
        for pair in self.pairs:
            forced = bool(dt.enabled) and pair == dt.pair
            self.trackers[pair] = SetupTracker(
                rsi_threshold=self.cfg.signal.rsi_setup_threshold,
                trigger_window=self.cfg.signal.trigger_window,
                target_horizon=self.cfg.signal.time_stop_bars,
                stop_atr_mult=self.cfg.risk.stop_atr_mult,
                min_stop_bps=self.cfg.risk.min_stop_bps,
                max_stop_bps=self.cfg.risk.max_stop_bps,
                force_setup=forced,
                force_trigger=forced,
            )
            self.spreads[pair] = SpreadWindow(self.cfg.micro.spread_median_window_sec)

        await self.refresh_equity()
        if self.state.day_start_equity is None:
            # Gün başı equity HER ZAMAN o anki hesabın gerçek bakiyesinden gelir.
            self.state.day_start_equity = self.state.equity
            self.state.trade_day = datetime.now(tz=self.tz).strftime("%Y-%m-%d")
            self.state.daily_pnl_pct = 0.0
            # Kill switch günlük zarar bayrağıdır; gün başı tabanı yenilenince o da düşer.
            self.state.kill_switch = False
            print(f"gün başı equity = {self.state.equity} (profil {self.t.profile})")
            self.decide("WAIT", gate="day_start",
                        reason=f"gün başı equity {self.state.equity} olarak {self.t.profile} "
                               f"bakiyesinden alındı; günlük PnL ve kill switch sıfırlandı")

        # Acil Durdur ÇALIŞAN DÖNGÜYÜ durdurur; YENİDEN BAŞLATMAYI ENGELLEMEZ. control.json'da
        # kalan mode=kill bir kerelik tüketilir, yoksa ajan her açılışta ilk turda kendini öldürür.
        ctl = read_control()
        if ctl["mode"] == "kill":
            write_control({"mode": "run"})
            self.decide("OPERATOR_KILL_CLEARED",
                        reason="control.json'da mode=kill bulundu; bir kerelik tüketildi → run. "
                               "Acil Durdur döngüyü durdurur, yeniden başlatmayı engellemez.")
            print("control.json mode=kill tüketildi → run")
        self._last_flatten = read_control()["flatten"]

        # Borsa kaynak gerçek: state.json ne derse desin önce uzlaştır.
        await self.reconcile(startup=True)

        # Rejim açılışta hesaplanır (ilk 15m'e kadar "başlangıç" kalmasın); yorumcu da burada ilk kez çalışır.
        await self.refresh_regime(force=True)

    async def _validate_universe(self) -> None:
        """Evren doğrulaması: hacim + enstrüman kısıtları + boyutun minSz'ı geçmesi.

        Hacim iki kaynaktan ölçülür çünkü `market_filter` DEMO ORTAMINDA 0 SATIR döndürüyor
        (filtresiz bile — canlı piyasa tarama aracı, demo'ya bağlı değil). Filtre satır
        döndürürse birincil kaynak o; döndürmezse ticker'ın `volCcy24h`'i (kote cinsi hacim
        ≈ USD) kullanılır ve bu durum loglanır.
        """
        wanted = list(self.cfg.pairs)
        min_vol = Decimal(str(self.cfg.universe.min_vol_usd_24h))
        rows = await self.t.filter_instruments(
            instType="SPOT", quoteCcy="USDT",
            minVolUsd24h=self.cfg.universe.min_vol_usd_24h,
            sortBy="volUsd24h", sortOrder="desc",
            limit=self.cfg.universe.filter_limit,  # 100 tavan, metotta zorlanıyor
        )
        liquid = {r["instId"] for r in rows}
        vol_source = "market_filter" if rows else "ticker.volCcy24h"
        if not rows:
            self.decide("WAIT", gate="universe",
                        reason="market_filter 0 satır döndü (demo ortamı); hacim ticker'dan ölçülüyor")
            print("  NOT: market_filter 0 satır döndü → hacim ticker.volCcy24h'ten ölçülüyor")

        notional = self.state.equity * Decimal(str(self.cfg.risk.position_pct))
        if notional <= 0:
            notional = Decimal("9")  # equity henüz okunmadıysa strateji.md §10 referans boyutu

        for pair in wanted:
            inst = (await self.t.get_instruments("SPOT", pair))[0]
            tick = Decimal(str(inst["tickSz"]))
            lot = Decimal(str(inst["lotSz"]))
            min_sz = Decimal(str(inst["minSz"]))
            ticker = await self.t.get_ticker(pair)
            last = Decimal(str(ticker["last"]))
            quote_vol = Decimal(str(ticker.get("volCcy24h") or 0))
            sz = q_sz(notional / last, lot)

            if rows:
                enough = pair in liquid
                vol_note = f"filtrede {'var' if enough else 'YOK'}"
            else:
                enough = quote_vol >= min_vol
                vol_note = f"volCcy24h={quote_vol:,.0f}"
            if not enough:
                self.decide("WAIT", symbol=pair, gate="universe", vol_source=vol_source,
                            reason=f"hacim yetersiz ({vol_note}, min {min_vol:,.0f})")
                print(f"  {pair}: EVRENDEN DÜŞTÜ — hacim yetersiz ({vol_note})")
                continue
            if inst.get("state") != "live":
                self.decide("WAIT", symbol=pair, gate="universe", reason=f"state={inst.get('state')}")
                print(f"  {pair}: EVRENDEN DÜŞTÜ — state={inst.get('state')}")
                continue
            if sz < min_sz:
                self.decide("WAIT", symbol=pair, gate="universe",
                            reason=f"{notional} USDT → sz={dstr(sz)} < minSz={dstr(min_sz)}")
                print(f"  {pair}: EVRENDEN DÜŞTÜ — sz {dstr(sz)} < minSz {dstr(min_sz)}")
                continue
            self.inst[pair] = {"tickSz": tick, "lotSz": lot, "minSz": min_sz}
            self.pairs.append(pair)
            print(f"  {pair}: OK · tickSz={dstr(tick)} lotSz={dstr(lot)} minSz={dstr(min_sz)} "
                  f"· {notional} USDT → sz={dstr(sz)} ({float(sz / min_sz):.1f}× minSz)")

        if not self.pairs:
            raise SystemExit("Evrende hiç parite kalmadı; ajan başlatılmıyor.")
        if self.cfg.regime_pair not in self.pairs:
            print(f"UYARI: rejim göstergesi {self.cfg.regime_pair} evrende yok; "
                  f"rejim yine onun mumlarıyla ölçülür ama sinyali kapalı.")

    async def refresh_equity(self) -> None:
        """`totalEq` = PnL ve kill switch tabanı. Boyut/bakiye kapısı `availBal` kullanır."""
        bal = await self.t.get_balance()
        total = bal.get("totalEq")
        self.state.equity = Decimal(str(total)) if total not in ("", None) else Decimal(0)
        base = self.state.day_start_equity
        if base:
            self.state.daily_pnl_pct = float((self.state.equity - base) / base * 100)

    # ---- mikro katman (her tur) ----

    async def sample_micro(self) -> None:
        for pair in self.pairs:
            fb0 = self.t.fallback_count
            book = await self.t.get_orderbook(pair, sz=self.cfg.micro.orderbook_sz)
            trades = await self.t.get_trades(pair, limit=self.cfg.micro.trades_limit)
            sp = spread_bps(book)
            row = {
                "ts": datetime.now(tz=self.tz).isoformat(timespec="seconds"),
                "symbol": pair,
                # İki çağrıdan biri bile CLI'ya düştüyse örnek cli_fallback sayılır (Faz 7).
                "transport": "cli_fallback" if self.t.fallback_count > fb0 else "mcp",
                "obi": obi(book, self.cfg.micro.obi_band_bps),
                "tfi": tfi(trades, self.cfg.micro.tfi_window_sec),
                "spread_bps": None if sp is None else round(sp, 4),
            }
            top = book_top(book)
            if top:
                row["best_bid"], row["best_ask"] = top[0], top[1]
            if sp is not None:
                self.spreads[pair].push(now_ms(), sp)
                med = self.spreads[pair].median()
                row["spread_median_bps"] = None if med is None else round(med, 4)
                row["spread_samples"] = len(self.spreads[pair])
            self.micro_last[pair] = row
            append_jsonl(MICRO, row)

    def effective_spread(self, pair: str) -> tuple[float, str]:
        """Maliyet kapısının kullandığı spread: 30 dk medyan, yoksa config fallback (LOGLANIR)."""
        med = self.spreads[pair].median() if pair in self.spreads else None
        if med is None:
            return float(self.cfg.micro.spread_bps_fallback), "fallback"
        return med, "measured"

    # ---- sinyal geçişi (15m kapanış + offset) ----

    def signal_due(self) -> int | None:
        """İşlenecek yeni kapanmış mum sınırı varsa onun ts'ini (ms) döndür."""
        bar_ms = BAR_MS[self.cfg.signal.bar]
        now = now_ms()
        last_close = (now // bar_ms) * bar_ms  # en son kapanan mumun BİTİŞ anı
        bar_open = last_close - bar_ms  # o mumun açılış ts'i (OKX ts = açılış)
        if now < last_close + self.cfg.signal.close_offset_sec * 1000:
            return None
        return bar_open if bar_open > self.state.last_signal_bar_ts else None

    async def load_frame(self, pair: str, bar: str, need: int) -> pd.DataFrame:
        candles = await self.t.get_candles_history(pair, bar, need=need)
        closed = [c for c in candles if c.confirm]  # kapanmamış mum ASLA kullanılmaz
        df = pd.DataFrame({
            "ts": [c.ts for c in closed],
            "high": [float(c.h) for c in closed],
            "low": [float(c.l) for c in closed],
            "close": [float(c.c) for c in closed],
        })
        return add_indicators(df, self.cfg.signal.bb_period, self.cfg.signal.bb_std,
                              self.cfg.signal.rsi_period, self.cfg.signal.atr_period)

    async def refresh_regime(self, force: bool = False) -> None:
        """BTC 1H son 48 mum → aralık; 15m ile taban/tavan ve vol kesici (strateji.md §4.1)."""
        now = now_ms()
        if not force and now - self.regime.computed_ms < self.cfg.regime.refresh_sec * 1000:
            return
        pair = self.cfg.regime_pair
        h1 = await self.t.get_candles(pair, self.cfg.regime.bar, limit=self.cfg.regime.lookback + 2)
        closed = [c for c in h1 if c.confirm][-self.cfg.regime.lookback:]
        if not closed:
            return
        low = float(min(c.l for c in closed))
        high = float(max(c.h for c in closed))
        # Rejim yorumcusu girdisi: son N adet 1H mum (config llm.regime.h1_bars)
        self._h1_bars = [
            {"t": datetime.fromtimestamp(c.ts / 1000, tz=self.tz).strftime("%m-%d %H:%M"),
             "o": str(c.o), "h": str(c.h), "l": str(c.l), "c": str(c.c)}
            for c in closed[-int(self.cfg.llm.regime.h1_bars):]
        ]

        m15 = await self.load_frame(pair, self.cfg.signal.bar,
                                   self.cfg.signal.bb_period + self.cfg.signal.warmup_bars)
        last = m15.iloc[-1]
        level: Literal["MEAN_REVERSION", "CASH"] = "MEAN_REVERSION"
        reason = f"aralık {fmt_px(low)}–{fmt_px(high)} korunuyor"
        if float(last.close) < low * self.cfg.regime.break_low_mult:
            level, reason = "CASH", (f"taban kırıldı: {fmt_px(float(last.close))} < "
                                     f"{fmt_px(low * self.cfg.regime.break_low_mult)}")
        elif float(last.close) > high:
            level, reason = "CASH", f"yukarı kırılım: {fmt_px(float(last.close))} > {fmt_px(high)}"

        ban = self.regime.vol_ban_until_ms
        rng = float(last.high) - float(last.low)
        if not np.isnan(last.atr) and rng > self.cfg.regime.vol_atr_mult * float(last.atr):
            ban = now + self.cfg.regime.vol_ban_sec * 1000
            self.decide("WAIT", symbol=pair, gate="volatility",
                        reason=f"son mum aralığı {rng:.4g} > {self.cfg.regime.vol_atr_mult:g}×ATR "
                               f"{float(last.atr):.4g} → {self.cfg.regime.vol_ban_sec // 60} dk yasak")

        prev = self.regime
        self.regime = Regime(level=level, range_low=low, range_high=high, reason=reason,
                             computed_ms=now, vol_ban_until_ms=ban)
        self.state.vol_ban_until_ms = ban
        print(f"rejim: {level} · {reason}")

        # Rejim yorumcusu (LLM) — rejimle aynı anda, 30 dk'da bir. Fail-open; ajanı asla durdurmaz.
        view = None
        try:
            view = await self.judge.regime_commentary(
                self._h1_bars, level, low, high, reason)
        except Exception as exc:  # judge fail-open'ı aşan beklenmedik hata bile döngüyü kesmez
            self.decide("ERROR", gate="llm_regime", reason=f"{type(exc).__name__}: {exc}")
        if view is not None:
            self.state.regime_commentary = view.model_dump()
            print(f"rejim yorumu ({view.status}, {view.model}): {view.view} güven={view.confidence} "
                  f"çelişki={view.conflict} · {view.note}")

        # Rejim değişimi (ve ilk hesap) karar günlüğüne düşer; LLM özeti aynı satırda.
        if prev.computed_ms == 0 or prev.level != level:
            extra = {"llm": view.model_dump()} if view is not None else {}
            self.decide("CASH" if level == "CASH" else "WAIT", symbol=pair, gate="regime",
                        range_low=low, range_high=high,
                        reason=("rejim hesaplandı: " if prev.computed_ms == 0 else
                                f"rejim değişti {prev.level} → {level}: ") + reason, **extra)

    def _wait_detail(self, tracker: SetupTracker, row: Any) -> str:
        """15m WAIT gerekçesi — SAYISAL: hangi koşul hangi değerle tutmadı (Faz 5 kalp atışı kuralı)."""
        snap = tracker.snapshot()
        close, bbl, rsi = float(row.close), float(row.bb_lower), float(row.rsi)
        if snap["state"] == "WAITING":
            return (f"kurulum bekliyor {snap['waited']}/{snap['trigger_window']}: tetik için close > BB_lower "
                    f"{fmt_px(bbl)} ve > setup_low {fmt_px(snap['setup_low'])}; close {fmt_px(close)}")
        if snap["state"] == "HOLDING":
            return f"pozisyon açık, ufuk {snap['held']}/{snap['horizon']}"
        thr = self.cfg.signal.rsi_setup_threshold
        parts = []
        if close >= bbl:
            parts.append(f"close {fmt_px(close)} {'>' if close > bbl else '='} BB_lower {fmt_px(bbl)}")
        if rsi >= thr:
            parts.append(f"RSI {rsi:.1f} {'>' if rsi > thr else '='} {thr:g}")
        return "; ".join(parts) if parts else "ısınma: indikatör henüz yok"

    async def signal_pass(self, bar_open_ts: int, orders_allowed: bool) -> bool:
        """Kapanmış mumları takipçiye ver; aday çıkarsa kapılardan geçir. Emir oldu mu döner.

        Parite başına en az bir satır düşer: olay yoksa sayısal gerekçeli WAIT (Faz 5).
        Rejim `tick()` içinde bundan ÖNCE tazelenir (değişim aynı mumda uygulansın).
        """
        need = (self.cfg.signal.bb_period + self.cfg.signal.warmup_bars)
        acted = False

        for pair in self.pairs:
            df = await self.load_frame(pair, self.cfg.signal.bar, need)
            if df.empty:
                self.decide("WAIT", symbol=pair, gate="data", reason="kapanmış mum gelmedi")
                continue
            new = df[df["ts"] > self.state.last_signal_bar_ts] if self.state.last_signal_bar_ts else df.tail(1)

            # Açık pozisyonların mum sayacı: zaman stopu kapanmış mumla ölçülür.
            for pos in self.state.positions:
                if pos.pair == pair:
                    pos.bars_held += len(new)

            # Olaylar mum mum çözülür: tetik PENDING bırakır ve `step()` PENDING'de hata atar,
            # yani aday AYNI turda kapılardan geçirilmek ZORUNDA. Sıra hatası sessiz kalamaz.
            tracker = self.trackers[pair]
            logged = False
            row = None
            for row in new.itertuples():
                bar = Bar(int(row.ts), row.high, row.low, row.close,
                          row.bb_lower, row.bb_mid, row.rsi, row.atr)
                for ev in tracker.step(bar):
                    logged = True
                    if ev.kind is Ev.SETUP:
                        self.decide("SETUP", symbol=pair, price=float(row.close),
                                    rsi=round(float(row.rsi), 2), bb_lower=float(row.bb_lower),
                                    bb_mid=float(row.bb_mid),
                                    reason="kurulum: BB alt + RSI eşik altı")
                    elif ev.kind is Ev.CANCEL:
                        self.decide("WAIT", symbol=pair, gate="trigger",
                                    reason=f"{self.cfg.signal.trigger_window} mumda tetik gelmedi, "
                                           "kurulum iptal")
                    elif ev.kind is Ev.REJECT_STOP:
                        self.decide("REJECT", symbol=pair, gate="risk_stop_band",
                                    reason=f"stop mesafesi {ev.detail['stop_bps']:.1f}bps > "
                                           f"{self.cfg.risk.max_stop_bps}bps")
                    elif ev.kind is Ev.TRIGGER and not ev.detail.get("rejected"):
                        placed = await self._handle_candidate(pair, ev, row, df, orders_allowed)
                        # Emir gönderildiyse ufuk tüketilir; herhangi bir kapı reddettiyse
                        # tracker IDLE'a döner ve bu parite SONRAKİ mumda yeni kurulum arar.
                        if tracker.pending:
                            tracker.confirm() if placed else tracker.reject()
                        acted = acted or placed
            if not logged and row is not None and not np.isnan(row.rsi):
                self.decide("WAIT", symbol=pair, gate="signal", price=float(row.close),
                            rsi=round(float(row.rsi), 2), bb_lower=float(row.bb_lower),
                            reason=self._wait_detail(tracker, row))
        return acted

    def _recent_bars(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        """Yargıca giden son N kapanmış mum özeti (config llm.judge.recent_bars)."""
        out = []
        for r in df.tail(int(self.cfg.llm.judge.recent_bars)).itertuples():
            out.append({"t": datetime.fromtimestamp(int(r.ts) / 1000, tz=self.tz).strftime("%H:%M"),
                        "h": round(float(r.high), 6), "l": round(float(r.low), 6),
                        "c": round(float(r.close), 6),
                        "rsi": None if np.isnan(r.rsi) else round(float(r.rsi), 1)})
        return out

    async def _handle_candidate(
        self, pair: str, ev: Any, bar_row: Any, df: pd.DataFrame, orders_allowed: bool
    ) -> bool:
        """Aday: mikro teyit → maliyet kapısı → LLM yargıç → risk kapısı → emir. Sıra ATLANMAZ.

        Yargıç maliyet kapısından SONRA: elenen aday için LLM/haber çağrısı yapılmaz (Faz 5 kararı).
        True  = emir gönderildi → çağıran `tracker.confirm()` yapar, ufuk tüketilir.
        False = bir kapı reddetti → çağıran `tracker.reject()` yapar, ufuk TÜKETİLMEZ.
        """
        dt = self.cfg.demo_test
        entry_ref = Decimal(str(ev.detail["entry"]))
        target = Decimal(str(ev.detail["target"]))
        stop_bps = float(ev.detail["stop_bps"])
        if dt.enabled and pair == dt.pair:
            # Sentetik ama GEÇERLİ aday: hedef ve stop config'den. Kapılar yine çalışır.
            target = entry_ref * (Decimal(1) + Decimal(str(dt.target_bps)) / Decimal(10_000))
            stop_bps = float(dt.stop_bps)
        stop = entry_ref * (Decimal(1) - Decimal(str(stop_bps)) / Decimal(10_000))
        target_bps = float((target - entry_ref) / entry_ref * 10_000)

        micro = self.micro_last.get(pair, {})
        base = {
            "symbol": pair, "price": float(bar_row.close), "rsi": round(float(bar_row.rsi), 2),
            "bb_lower": float(bar_row.bb_lower), "bb_mid": float(bar_row.bb_mid),
            "obi": micro.get("obi"), "spread_bps": micro.get("spread_bps"),
            "target_bps": round(target_bps, 1), "stop_bps": round(stop_bps, 1),
        }
        self.decide("CANDIDATE", reason="tetik geldi, kapılara giriyor", **base)

        # 0) saat — en ucuz kapı en başta. Risk kapısında da duruyor (aşılamaz katman orası),
        # ama burada sorulmazsa 18:30 sonrası her aday boşuna LLM yargıcına gidiyor (Faz 7).
        ok, reason = self._hour_gate()
        if not ok:
            self.decide("REJECT", gate="risk_hour", reason=reason, **base)
            return False

        # 1) mikro teyit
        ok, reason = self._micro_confirm(pair)
        if not ok:
            self.decide("REJECT", gate="micro", reason=reason, **base)
            return False

        # 2) maliyet kapısı
        spread, source = self.effective_spread(pair)
        ok, reason = cost_gate(target_bps, self.fee_bps, spread, self.cfg.cost.multiplier)
        if source == "fallback":
            reason += f" (spread ÖLÇÜLMEDİ, fallback {spread:g}bps)"
        if not ok:
            self.decide("REJECT", gate="cost", reason=reason, spread_source=source, **base)
            return False

        # 3) LLM yargıç — SADECE FREN. Fail-open: LLM düşerse aday geçer, durum satıra işlenir.
        try:
            verdict: Verdict = await self.judge.judge(base, self._recent_bars(df))
        except Exception as exc:  # judge'ın kendi fail-open'ını aşan hata bile adayı durdurmaz
            verdict = Verdict(decision="APPROVE", size_multiplier=1.0, status="failed_open",
                              reason=f"FAIL-OPEN: judge istisnası {type(exc).__name__}: {exc}"[:300])
        base["llm"] = verdict.summary()  # adayın SONRAKİ satırı verdict özetini taşır
        if verdict.decision == "VETO":
            self.decide("REJECT", gate="judge", reason=f"LLM VETO ({verdict.model}): {verdict.reason}", **base)
            return False
        size_mult = float(verdict.size_multiplier) if verdict.decision == "REDUCE" else 1.0
        print(f"JUDGE {pair}: {verdict.decision} ×{size_mult:g} [{verdict.status}/{verdict.model}] "
              f"{verdict.reason}")

        # 4) risk kapısı — 10 kontrol, strateji.md §4.6 sırasıyla (REDUCE çarpanı boyuta uygulanır)
        allowed, gate, reason, sz, px = await self._risk_gate(pair, stop_bps, orders_allowed, size_mult)
        if not allowed:
            self.decide("REJECT", gate=gate, reason=reason, **base)
            return False

        return await self._place_entry(pair, px, sz, target, stop, base)

    def _micro_confirm(self, pair: str) -> tuple[bool, str]:
        m = self.micro_last.get(pair)
        if not m or m.get("obi") is None or m.get("spread_bps") is None:
            return False, "mikro örnek yok"
        if m["obi"] < self.cfg.micro.obi_min:
            return False, f"OBI {m['obi']:.3f} < {self.cfg.micro.obi_min}"
        med = self.spreads[pair].median()
        if med is not None and m["spread_bps"] > self.cfg.micro.spread_mult_max * med:
            return False, (f"spread {m['spread_bps']:.2f}bps > "
                           f"{self.cfg.micro.spread_mult_max:g}× medyan {med:.2f}bps")
        return True, f"OBI {m['obi']:.3f}, spread {m['spread_bps']:.2f}bps"

    def _hour_gate(self) -> tuple[bool, str]:
        """`last_entry_local` (18:30) sonrası yeni giriş yok. Gerekçe Türkçe ve saatli."""
        local = datetime.now(tz=self.tz)
        if local.time() >= parse_hhmm(self.cfg.execution.last_entry_local):
            return False, f"{local:%H:%M} ≥ {self.cfg.execution.last_entry_local}, yeni giriş yok"
        return True, ""

    async def _risk_gate(
        self, pair: str, stop_bps: float, orders_allowed: bool, size_mult: float = 1.0
    ) -> tuple[bool, str, str, Decimal, Decimal]:
        """strateji.md §4.6 — 10 kontrol, SIRAYLA. İlk kapanan kapı döner; sonrakiler bakılmaz.

        Aşılamaz katman: emre giden tek yol burası. `size_mult` (LLM REDUCE) yalnızca KÜÇÜLTÜR
        (0.3–1.0, judge.py kırpar); minSz kontrolü çarpandan SONRA yapılır.
        """
        r, zero = self.cfg.risk, Decimal(0)
        now = now_ms()

        if not orders_allowed:
            return False, "control", "operatör: emir yok (pause/kill)", zero, zero

        # 0 saat — EN BAŞTA (Faz 7). Eskiden 10. kontroldü. Aday akışı bunu artık yargıçtan ÖNCE
        # de soruyor (`_handle_candidate`), ama kontrol burada da duruyor: emre giden tek yol
        # risk kapısıdır, hiçbir kapı yalnızca çağıranın nezaketine bırakılmaz.
        ok, why = self._hour_gate()
        if not ok:
            return False, "risk_hour", why, zero, zero

        # 1 kill switch — YALNIZCA günlük zarar. Bayrağın tek yazarı burasıdır; operatör kill
        # (tick()) artık buraya yazmaz. İkisi ayrı kavram: bu "bugün bitti" (kalıcı risk kararı),
        # o "döngüyü durdur" (geçici süreç kararı). Karışınca operatör kill kalıcılığı miras
        # alıyor ve ajan yeniden başlatıldığında emir yolu sessizce kapalı kalıyordu.
        if self.state.daily_pnl_pct <= r.kill_switch_daily_pct:
            self.state.kill_switch = True
        if self.state.kill_switch:
            return False, "risk_kill_switch", \
                f"günlük PnL {self.state.daily_pnl_pct:.2f}% ≤ {r.kill_switch_daily_pct}%", zero, zero
        # 2 cooldown
        if now < self.state.cooldown_until_ms:
            left = (self.state.cooldown_until_ms - now) // 60000
            return False, "risk_cooldown", \
                f"{self.state.consecutive_losses} ardışık kayıp, {left} dk kaldı", zero, zero
        # 3 günlük işlem tavanı
        if self.state.daily_trades >= r.max_daily_trades:
            return False, "risk_daily_cap", \
                f"günlük işlem {self.state.daily_trades}/{r.max_daily_trades}", zero, zero
        # 4 eşzamanlı pozisyon
        busy = len(self.state.positions) + len(self.state.pending)
        if busy >= r.max_concurrent:
            return False, "risk_concurrent", f"açık+bekleyen {busy}/{r.max_concurrent}", zero, zero
        # 5 parite başına
        if any(p.pair == pair for p in self.state.positions) or \
           any(p.pair == pair for p in self.state.pending):
            return False, "risk_per_pair", f"{pair}'de zaten pozisyon/emir var", zero, zero
        # 6 boyut
        dt = self.cfg.demo_test
        if dt.enabled and pair == dt.pair:
            notional = Decimal(str(dt.notional_usdt))
        else:
            notional = self.state.equity * Decimal(str(r.position_pct))
        notional *= Decimal(str(min(1.0, max(0.0, size_mult))))  # LLM REDUCE: sadece küçültür
        # 7 stop bandı
        if stop_bps > r.max_stop_bps:
            return False, "risk_stop_band", f"stop {stop_bps:.1f}bps > {r.max_stop_bps}bps", zero, zero
        if stop_bps < r.min_stop_bps:
            return False, "risk_stop_band", f"stop {stop_bps:.1f}bps < {r.min_stop_bps}bps", zero, zero
        # 8 enstrüman kısıtı
        spec = self.inst[pair]
        micro = self.micro_last.get(pair, {})
        bid, ask = micro.get("best_bid"), micro.get("best_ask")
        if bid is None or ask is None:
            return False, "risk_instrument", "en iyi alış/satış yok (defter örneği eksik)", zero, zero
        if dt.enabled and pair == dt.pair and dt.entry_px == "ask":
            px = q_px(Decimal(str(ask)), spec["tickSz"])
        else:
            px = q_px(Decimal(str(bid)) + spec["tickSz"], spec["tickSz"])
        sz = q_sz(notional / px, spec["lotSz"])
        if sz < spec["minSz"]:
            return False, "risk_instrument", \
                f"sz {dstr(sz)} < minSz {dstr(spec['minSz'])} (yukarı yuvarlanmaz" \
                f"{f', LLM REDUCE ×{size_mult:g} sonrası' if size_mult < 1.0 else ''})", zero, zero
        # 9 bakiye
        avail = await self.t.get_avail_bal("USDT")
        if px * sz > avail:
            return False, "risk_balance", f"notional {px * sz:.2f} > availBal {avail}", zero, zero
        note = f"10 kontrol geçti" + (f" (LLM REDUCE ×{size_mult:g})" if size_mult < 1.0 else "")
        return True, "", note, sz, px

    async def _place_entry(
        self, pair: str, px: Decimal, sz: Decimal, target: Decimal, stop: Decimal,
        base: dict[str, Any]
    ) -> bool:
        """Limit alış + İLİŞTİRİLMİŞ TP/SL. Tek deneme; TP/SL borsa tarafında bekler."""
        spec = self.inst[pair]
        tick = spec["tickSz"]
        tp = q_px(target, tick)
        sl = q_px(stop, tick)
        sl_ord = q_px(sl - 2 * tick, tick)  # tetik ile emir arasında 2 tick pay
        cl_ord_id = f"terazi{now_ms() % 10_000_000_000}"

        # `tpOrdKind` GÖNDERİLMEZ: spot'ta "limit" kindi kod 51094 ile reddediliyor
        # ("You can't place TP limit orders in spot..."). Faz 2'de ölçüldü; docs/mcp-araclari.md
        # §6'nın CLI yardımından çıkardığı varsayım YANLIŞTI. Kind'sız çağrıda tpOrdPx yine
        # sabit fiyat olduğu için hedef BB_mid'de limit satış olarak duruyor.
        req = {
            "instId": pair, "side": "buy", "ordType": "limit", "tdMode": "cash",
            "px": dstr(px), "sz": dstr(sz), "clOrdId": cl_ord_id,
            "tpTriggerPx": dstr(tp), "tpOrdPx": dstr(tp),
            "slTriggerPx": dstr(sl), "slOrdPx": dstr(sl_ord),
        }
        try:
            res = await self.t.place_order(
                inst_id=pair, side="buy", ord_type="limit", sz=dstr(sz), px=dstr(px),
                td_mode="cash", cl_ord_id=cl_ord_id,
                tp_trigger_px=dstr(tp), tp_ord_px=dstr(tp),
                sl_trigger_px=dstr(sl), sl_ord_px=dstr(sl_ord),
            )
        except SafetyGateError as exc:
            self.order_log(symbol=pair, request=req, ok=False, gate="safety", error=str(exc))
            self.decide("ERROR", gate="safety", reason=str(exc), **base)
            return False
        except OkxToolError as exc:
            # Emir hatası: TEK deneme, yeniden denenmez (çift emir riski).
            self.order_log(symbol=pair, request=req, ok=False, error=str(exc.detail))
            self.decide("ERROR", gate="order", reason=f"emir reddedildi: {exc.detail}", **base)
            return False

        if res.get("dry_run"):
            self.order_log(symbol=pair, request=req, dry_run=True, ok=True,
                           note="dry-run: MCP'ye gönderilmedi")
            self.decide("ORDER", reason="dry-run: emir gönderilmedi", dry_run=True,
                        px=dstr(px), sz=dstr(sz), tp=dstr(tp), sl=dstr(sl), **base)
            return True

        ord_id = str(res.get("ordId", ""))
        self.order_log(symbol=pair, request=req, ok=True, response=res, ord_id=ord_id)
        self.state.pending.append(PendingOrder(
            pair=pair, ord_id=ord_id, cl_ord_id=cl_ord_id, px=px, sz=sz,
            target=tp, stop=sl, placed_ms=now_ms(),
        ))
        self.state.daily_trades += 1
        self.decide("ORDER", reason=f"limit alış {dstr(px)} × {dstr(sz)}, TP {dstr(tp)} / SL {dstr(sl)}",
                    ord_id=ord_id, px=dstr(px), sz=dstr(sz), tp=dstr(tp), sl=dstr(sl), **base)
        print(f"ORDER {pair} ordId={ord_id} px={dstr(px)} sz={dstr(sz)} TP={dstr(tp)} SL={dstr(sl)}")
        return True

    # ---- bekleyen emirler ve uzlaştırma ----

    def _drop_pending(self, po: PendingOrder, gate: str, reason: str) -> None:
        """Dolmayan emri düşür ve paritenin UFKUNU SERBEST BIRAK (Faz 5).

        Emir gönderilince tracker HOLDING'e geçmişti; dolum olmadıysa pozisyon yok, ufuk tüketilmemeli:
        `reject()` tracker'ı IDLE'a döndürür, parite SONRAKİ mumda yeni kurulum arayabilir.
        """
        if po in self.state.pending:
            self.state.pending.remove(po)
        tracker = self.trackers.get(po.pair)
        released = False
        if tracker is not None and tracker.state in ("HOLDING", "PENDING"):
            tracker.reject()
            released = True
        self.decide("WAIT", symbol=po.pair, gate=gate, ord_id=po.ord_id,
                    reason=reason + ("; ufuk serbest bırakıldı" if released else ""))

    async def check_pending(self) -> None:
        """Her tur: dolan var mı, TTL doldu mu. 90 sn dolmazsa iptal, aday düşer, ufuk serbest."""
        ttl = self.cfg.execution.limit_order_ttl_sec * 1000
        for po in list(self.state.pending):
            try:
                od = await self.t.get_order(po.pair, ord_id=po.ord_id)
            except Exception as exc:  # noqa: BLE001 — reconcile ile aynı gerekçe (Faz 7)
                self.decide("ERROR", symbol=po.pair, gate="reconcile",
                            reason=f"emir sorgusu başarısız: {getattr(exc, 'detail', exc)}")
                continue
            state = str(od.get("state", ""))
            filled = Decimal(str(od.get("accFillSz") or 0))

            if state == "filled" or (filled > 0 and state in ("partially_filled", "")):
                await self._promote(po, od, filled)
            elif state in ("canceled", "mmp_canceled"):
                self._drop_pending(po, "fill", f"emir iptal oldu (state={state}), aday düştü")
            elif now_ms() - po.placed_ms > ttl:
                if filled > 0:
                    await self._promote(po, od, filled)
                    continue
                try:
                    await self.t.cancel_order(po.pair, ord_id=po.ord_id)
                    self.order_log(symbol=po.pair, ord_id=po.ord_id, action="cancel", ok=True,
                                   reason=f"{self.cfg.execution.limit_order_ttl_sec} sn doldu")
                except OkxToolError as exc:
                    self.order_log(symbol=po.pair, ord_id=po.ord_id, action="cancel", ok=False,
                                   error=str(exc.detail))
                self._drop_pending(po, "fill",
                                   f"{self.cfg.execution.limit_order_ttl_sec} sn'de dolmadı, iptal edildi")

    async def _promote(self, po: PendingOrder, od: dict[str, Any], filled: Decimal) -> None:
        """Dolan emri pozisyona çevir. GERÇEK miktar fills'ten gelir (kısmi dolum olabilir)."""
        real_sz, avg_px, fee = await self._fill_summary(po.pair, po.ord_id)
        if real_sz <= 0:
            real_sz = filled
            avg_px = Decimal(str(od.get("avgPx") or po.px))
        if po in self.state.pending:
            self.state.pending.remove(po)
        pos = Position(pair=po.pair, ord_id=po.ord_id, cl_ord_id=po.cl_ord_id,
                       entry_px=avg_px, sz=real_sz, target=po.target, stop=po.stop,
                       opened_ms=now_ms(), fee_paid=fee)
        pos.algo_id = await self._find_algo_id(po.pair)
        self.state.positions.append(pos)
        partial = "" if real_sz >= po.sz else f" (KISMİ: {dstr(real_sz)}/{dstr(po.sz)})"
        self.decide("FILL", symbol=po.pair, price=float(avg_px), sz=dstr(real_sz),
                    algo_id=pos.algo_id, ord_id=po.ord_id, fee_paid=float(fee),
                    reason=f"dolum {dstr(real_sz)} @ {dstr(avg_px)}{partial}; "
                           f"komisyon {fee:.6f} USDT; algoId={pos.algo_id or 'YOK'}")
        print(f"FILL {po.pair} {dstr(real_sz)} @ {dstr(avg_px)} algoId={pos.algo_id}")

    async def _fill_summary(self, pair: str, ord_id: str) -> tuple[Decimal, Decimal, Decimal]:
        """Dolumlardan gerçek miktar, ağırlıklı ortalama fiyat ve KOMİSYON (USDT)."""
        try:
            fills = await self.t.get_fills(inst_id=pair, ord_id=ord_id)
        except OkxToolError:
            return Decimal(0), Decimal(0), Decimal(0)
        return fill_totals(pair, fills)

    async def _find_algo_id(self, pair: str) -> str | None:
        """İliştirilmiş TP/SL'in algoId'si — çıkışı iptal etmenin tek yolu."""
        try:
            rows = await self.t.get_algo_orders(status="pending", inst_id=pair)
        except OkxToolError:
            return None
        for r in rows:
            aid = r.get("algoId")
            if aid:
                return str(aid)
        return None

    async def reconcile(self, startup: bool = False) -> None:
        """Her 60 sn: borsa KAYNAK GERÇEK. state.json ile çelişirse borsa kazanır, fark loglanır."""
        self.last_reconcile_ms = now_ms()
        try:
            open_orders = await self.t.get_orders(status="open")
            algos = await self.t.get_algo_orders(status="pending")
        except Exception as exc:  # noqa: BLE001
            # OkxToolError'dan GENİŞ (Faz 7): MCP oturumu ölürse bu araçların CLI yedeği YOK
            # (emir yüzeyi) ve gelen MCPError dar `except`e takılmayıp TÜM TURU düşürüyordu —
            # mikro örnekleme yedekten çalışırken tur 30 sn'lik hata beklemesine giriyordu.
            # Uzlaştırmanın başarısızlığı turu öldürmez; bir sonraki turda yeniden denenir.
            detail = getattr(exc, "detail", exc)
            self.decide("ERROR", gate="reconcile", reason=f"uzlaştırma okunamadı: {detail}")
            return

        live_ords = {str(o.get("ordId")) for o in open_orders}
        algo_by_pair: dict[str, str] = {}
        for a in algos:
            inst, aid = a.get("instId"), a.get("algoId")
            if inst and aid:
                algo_by_pair.setdefault(str(inst), str(aid))

        # Borsada olmayan bekleyen emir: dolmuş ya da iptal olmuş.
        for po in list(self.state.pending):
            if po.ord_id and po.ord_id not in live_ords:
                try:
                    od = await self.t.get_order(po.pair, ord_id=po.ord_id)
                except OkxToolError:
                    continue
                filled = Decimal(str(od.get("accFillSz") or 0))
                if filled > 0:
                    await self._promote(po, od, filled)
                else:
                    self._drop_pending(po, "reconcile",
                                       f"emir borsada yok, dolum 0 (state={od.get('state')})")

        # Pozisyonların algoId'sini borsadan tazele; yoksa çıkış emri düşmüş demektir.
        # list(): gövde _close_position ile listeyi kısaltıyor, canlı liste üzerinde dönmek
        # bir pozisyonu atlar (Faz 7'de görüldü).
        for pos in list(self.state.positions):
            live_algo = algo_by_pair.get(pos.pair)
            if live_algo and pos.algo_id != live_algo:
                self.decide("FILL", symbol=pos.pair, algo_id=live_algo,
                            reason=f"uzlaştırma: algoId borsadan kuruldu "
                                   f"({pos.algo_id or 'YOK'} → {live_algo})")
                pos.algo_id = live_algo
            elif not live_algo and pos.algo_id:
                # TP/SL tetiklenmiş → pozisyon kapandı. Çıkış fiyatını, miktarını ve komisyonu
                # SATIŞ DOLUMLARINDAN oku; hangisinin çalıştığını (tp/sl) fiyata bakarak ayır.
                # Canlıda en sık görülecek çıkış bu; fiyatsız kapatmak net PnL'i kör bırakıyordu.
                exit_px, exit_fee, why = await self._exit_from_fills(pos)
                src = "fills" if exit_px is not None else "none"
                pnl = self._close_position(pos, exit_px, why, exit_fee, src)
                self.decide("EXIT", symbol=pos.pair, algo_id=pos.algo_id, exit_reason=why,
                            price=None if exit_px is None else float(exit_px),
                            price_source=src, fee_source=src,
                            reason=f"algo emri borsada yok: TP/SL çalıştı ({why})", **pnl)

        # Borsada algo emri var ama state'te pozisyon yok → state.json silinmiş/eski.
        known = {p.pair for p in self.state.positions}
        for pair, aid in algo_by_pair.items():
            if pair in known or pair not in self.pairs:
                continue
            rebuilt = await self._rebuild_position(pair, aid, algos)
            if rebuilt:
                self.state.positions.append(rebuilt)
                self.decide("FILL", symbol=pair, algo_id=aid, price=float(rebuilt.entry_px),
                            sz=dstr(rebuilt.sz),
                            reason="KURTARMA: pozisyon borsadan geri kuruldu (state.json'da yoktu)")
                print(f"KURTARMA {pair}: sz={dstr(rebuilt.sz)} entry={dstr(rebuilt.entry_px)} "
                      f"algoId={aid}")

        if startup:
            print(f"uzlaştırma: {len(self.state.positions)} pozisyon, "
                  f"{len(self.state.pending)} bekleyen emir, {len(algo_by_pair)} algo emri")

    async def _exit_from_fills(self, pos: Position) -> tuple[Decimal | None, Decimal, str]:
        """TP/SL çalışmış pozisyonun çıkışını dolumlardan çıkar → (fiyat, komisyon, sebep).

        Sebep, çıkış fiyatının `pos.target`'a mı `pos.stop`'a mı yakın olduğuna bakılarak
        ayrılır; borsa hangi bacağın tetiklendiğini ayrıca söylemiyor. Dolum okunamazsa
        bugünkü fiyatsız davranışa düşülür ve sebep ayrıştırılmamış `"tp_sl"` kalır.
        """
        try:
            fills = await self.t.get_fills(inst_id=pos.pair, limit=50)
        except OkxToolError:
            return None, Decimal(0), "tp_sl"
        sells = [f for f in fills
                 if f.get("side") == "sell" and int(f.get("ts") or 0) >= pos.opened_ms]
        if not sells:
            return None, Decimal(0), "tp_sl"
        _, px, fee = fill_totals(pos.pair, sells)
        if px <= 0:
            return None, fee, "tp_sl"
        why = "tp" if abs(px - pos.target) <= abs(px - pos.stop) else "sl"
        return px, fee, why

    async def _rebuild_position(
        self, pair: str, algo_id: str, algos: list[dict[str, Any]]
    ) -> Position | None:
        """Borsadaki algo emri + son dolumlardan pozisyonu yeniden kur (kurtarma yolu)."""
        row = next((a for a in algos if str(a.get("algoId")) == algo_id), {})
        sz = Decimal(str(row.get("sz") or 0))
        try:
            fills = await self.t.get_fills(inst_id=pair, limit=50)
        except OkxToolError:
            fills = []
        buys = sorted((f for f in fills if f.get("side") == "buy"),
                      key=lambda f: int(f.get("ts") or 0), reverse=True)
        if not buys and sz <= 0:
            return None
        if sz > 0:
            # BU pozisyonun dolumları: en yeniden geriye, algo emrinin miktarı dolana kadar.
            # Paritedeki tüm alışları toplamak hem giriş fiyatını hem komisyonu şişiriyordu
            # (Faz 7'de ölçüldü: aynı paritede 4 eski dolum varken fee_paid 0.012 yerine 0.048).
            taken, acc = [], Decimal(0)
            for f in buys:
                if acc >= sz:
                    break
                taken.append(f)
                acc += Decimal(str(f.get("fillSz") or 0))
            buys = taken
        total, avg_px, fee = fill_totals(pair, buys)
        entry = avg_px if total else Decimal(str(row.get("tpTriggerPx") or 0))
        real_sz = sz if sz > 0 else total
        if real_sz <= 0:
            return None
        tp = Decimal(str(row.get("tpTriggerPx") or 0))
        sl = Decimal(str(row.get("slTriggerPx") or 0))
        newest = max((int(f["ts"]) for f in buys), default=now_ms())
        return Position(pair=pair, ord_id=str(row.get("ordId") or ""), cl_ord_id="",
                        entry_px=entry, sz=real_sz, target=tp, stop=sl,
                        opened_ms=newest, algo_id=algo_id, fee_paid=fee)

    # ---- çıkışlar ----

    def _pnl(self, pos: Position, exit_px: Decimal | None, exit_fee: Decimal) -> dict[str, Any]:
        """Komisyonlu net PnL. Komisyon = giriş (pos.fee_paid) + çıkış, ikisi de USDT.

        `gross_bps` saf fiyat farkı, `fee_bps` komisyonun giriş notional'ına oranı,
        `net_bps = gross_bps − fee_bps`. Çıkış fiyatı bilinmiyorsa hepsi None.
        """
        fee = pos.fee_paid + exit_fee
        if exit_px is None or pos.entry_px <= 0:
            return {"gross_bps": None, "fee_bps": None, "net_bps": None, "net_pnl_usdt": None,
                    "fee_paid": float(fee)}
        notional = pos.entry_px * pos.sz
        gross = (exit_px - pos.entry_px) / pos.entry_px * 10_000
        fee_bps = (fee / notional * 10_000) if notional else Decimal(0)
        return {
            "gross_bps": round(float(gross), 2),
            "fee_bps": round(float(fee_bps), 2),
            "net_bps": round(float(gross - fee_bps), 2),
            "net_pnl_usdt": round(float((exit_px - pos.entry_px) * pos.sz - fee), 6),
            "fee_paid": float(fee),
        }

    def _close_position(self, pos: Position, exit_px: Decimal | None, exit_reason: str,
                        exit_fee: Decimal = Decimal(0),
                        fee_source: str = "fills") -> dict[str, Any]:
        """Pozisyonu state'ten düş, kapanan işlemi kaydet, ardışık kayıp ve cooldown'ı güncelle.

        Kayıp ölçüsü Faz 7'den itibaren NET (komisyon sonrası): komisyonu yiyen bir "kazanç"
        ardışık kayıp sayacını sıfırlamamalı.
        """
        if pos in self.state.positions:
            self.state.positions.remove(pos)
        pnl = self._pnl(pos, exit_px, exit_fee)
        self.state.closed_positions.append({
            "ts": datetime.now(tz=self.tz).isoformat(timespec="seconds"),
            "pair": pos.pair, "entry_px": str(pos.entry_px),
            "exit_px": None if exit_px is None else str(exit_px),
            "sz": str(pos.sz), "exit_reason": exit_reason, "fee_source": fee_source,
            "bars_held": pos.bars_held, **pnl,
        })
        cap = self.cfg.execution.closed_positions_max
        if len(self.state.closed_positions) > cap:
            del self.state.closed_positions[:-cap]

        if pnl["net_bps"] is not None:
            if pnl["net_bps"] < 0:
                self.state.consecutive_losses += 1
                if self.state.consecutive_losses >= self.cfg.risk.cooldown_losses:
                    self.state.cooldown_until_ms = now_ms() + self.cfg.risk.cooldown_sec * 1000
            else:
                self.state.consecutive_losses = 0
        return pnl

    async def close_now(self, pos: Position, reason: str, exit_reason: str) -> None:
        """Zaman stopu / flatten / gün sonu: ÖNCE algo iptal, SONRA market sell.

        `exit_reason`: makine okunur çıkış sebebi — "time" | "eod" | "operator"
        (TP/SL uzlaştırmada tespit edilir, oradan "tp"/"sl" gelir).

        Sıra önemli: TP/SL yaşarken market sell atarsak borsa elimizde olmayan miktarı
        satmaya çalışır.
        """
        spec = self.inst.get(pos.pair)
        if pos.algo_id:
            try:
                await self.t.cancel_algo_order(pos.pair, pos.algo_id)
                self.order_log(symbol=pos.pair, action="cancel_algo", algo_id=pos.algo_id,
                               ok=True, reason=reason)
            except OkxToolError as exc:
                self.order_log(symbol=pos.pair, action="cancel_algo", algo_id=pos.algo_id,
                               ok=False, error=str(exc.detail))
                self.decide("ERROR", symbol=pos.pair, gate="exit",
                            reason=f"algo iptal edilemedi: {exc.detail}")
                return  # TP/SL yaşıyor; market sell atmıyoruz

        # Satılabilir miktar dolumdan AZ olabilir: OKX alış komisyonunu BAZ PARADAN kesiyor
        # (Faz 2'de ölçüldü: dolum 0.117889 SOL, satılabilir 0.117771). pos.sz kadar satmaya
        # kalkarsak bakiye yetmezliğine düşeriz; gerçek bakiyeyle sınırlıyoruz.
        base_ccy = pos.pair.split("-")[0]
        try:
            avail_base = await self.t.get_avail_bal(base_ccy)
        except OkxToolError:
            avail_base = pos.sz
        sz = min(pos.sz, avail_base) if avail_base > 0 else pos.sz
        sz = q_sz(sz, spec["lotSz"]) if spec else sz
        req = {"instId": pos.pair, "side": "sell", "ordType": "market", "sz": dstr(sz),
               "tgtCcy": "base_ccy"}
        try:
            res = await self.t.place_order(inst_id=pos.pair, side="sell", ord_type="market",
                                           sz=dstr(sz), td_mode="cash", tgt_ccy="base_ccy")
        except (OkxToolError, SafetyGateError) as exc:
            self.order_log(symbol=pos.pair, request=req, ok=False, error=str(exc))
            self.decide("ERROR", symbol=pos.pair, gate="exit", reason=f"kapatma başarısız: {exc}")
            return

        if res.get("dry_run"):
            self.order_log(symbol=pos.pair, request=req, dry_run=True, ok=True)
            self.decide("EXIT", symbol=pos.pair, reason=f"{reason} (dry-run)", dry_run=True,
                        exit_reason=exit_reason)
            self._close_position(pos, None, exit_reason)
            return

        ord_id = str(res.get("ordId", ""))
        self.order_log(symbol=pos.pair, request=req, ok=True, response=res, ord_id=ord_id)
        exit_sz, exit_px, exit_fee = await self._fill_summary(pos.pair, ord_id)
        px_source = fee_source = "fills"
        if not exit_px:
            # Market satışın dolumu sorguya hemen yansımıyor. Ardışık kayıp/cooldown sayacı
            # fiyatsız çalışmaz, o yüzden son bilinen en iyi alışa düşüyoruz ve kaynağı logluyoruz.
            bid = self.micro_last.get(pos.pair, {}).get("best_bid")
            if bid:
                exit_px, px_source = Decimal(str(bid)), "best_bid"
        if exit_fee == 0 and exit_px:
            # Market satışın dolumu sorguya hemen yansımıyor (yukarıdaki best_bid yolu ile aynı
            # sebep). Çıkış komisyonunu 0 saymak net PnL'i sistematik olarak İYİMSER gösterir —
            # gidiş-dönüş komisyonun yarısı kaybolur. Bilinen komisyon oranıyla tahmin edip
            # satırı `fee_source="estimated"` diye damgalıyoruz; uydurma değil, işaretli tahmin.
            exit_fee = exit_px * (exit_sz or sz) * Decimal(str(self.fee_bps)) / Decimal(10_000)
            fee_source = "estimated"

        pnl = self._close_position(pos, exit_px if exit_px else None, exit_reason, exit_fee,
                                   fee_source)
        self.decide("EXIT", symbol=pos.pair, sz=dstr(exit_sz or sz),
                    price=float(exit_px) if exit_px else None, price_source=px_source,
                    fee_source=fee_source, ord_id=ord_id, exit_reason=exit_reason,
                    reason=reason, **pnl)
        print(f"EXIT {pos.pair} {dstr(exit_sz or sz)} @ {dstr(exit_px)} ({px_source}) "
              f"net={pnl['net_bps']}bps ({exit_reason}) — {reason}")

    async def check_time_stops(self) -> None:
        limit = self.cfg.signal.time_stop_bars
        for pos in list(self.state.positions):
            if pos.bars_held >= limit:
                await self.close_now(pos, f"zaman stopu: {pos.bars_held} kapanmış mum ≥ {limit}",
                                     "time")

    async def flatten_all(self, reason: str, exit_reason: str) -> tuple[int, int]:
        """Tüm pozisyonları kapat, bekleyenleri iptal et. (kapatılan, iptal edilen) sayısı döner."""
        closed = cancelled = 0
        for pos in list(self.state.positions):
            before = len(self.state.positions)
            await self.close_now(pos, reason, exit_reason)
            closed += before - len(self.state.positions)
        for po in list(self.state.pending):
            try:
                await self.t.cancel_order(po.pair, ord_id=po.ord_id)
                self.order_log(symbol=po.pair, ord_id=po.ord_id, action="cancel", ok=True,
                               reason=reason)
            except OkxToolError as exc:
                self.order_log(symbol=po.pair, ord_id=po.ord_id, action="cancel", ok=False,
                               error=str(exc.detail))
            self._drop_pending(po, "flatten", f"{reason}: bekleyen emir iptal")
            cancelled += 1
        return closed, cancelled

    # ---- tur ----

    async def tick(self) -> None:
        self.turn += 1
        fb_turn_start = self.t.fallback_count
        control = read_control()
        mode = control["mode"]
        orders_allowed = mode == "run"

        # Operatör eylemlerinin TEK kaynağı ajandır (dashboard yalnızca control.json yazar, Faz 5).
        # kill kendi (daha zengin) satırını aşağıda yazıyor; burada tekrarlamıyoruz.
        if mode != self._last_mode and mode != "kill":
            self.decide(f"OPERATOR_{mode.upper()}", reason=f"control.json mode={mode}")
            print(f"OPERATÖR: mode={mode}")
        self._last_mode = mode
        if control["flatten"] and not self._last_flatten:
            self.decide("OPERATOR_FLATTEN",
                        reason=f"control.json flatten=true: {len(self.state.positions)} pozisyon, "
                               f"{len(self.state.pending)} bekleyen emir kapatılacak")
            print("OPERATÖR: flatten=true")
        self._last_flatten = control["flatten"]

        if mode == "kill":
            # Acil Durdur: döngü TEMİZ çıkar. Pozisyonlar kapatılmaz — borsadaki TP/SL onları
            # korumaya devam eder; hepsini kapatmak ayrı bir eylem (flatten).
            # "Ajan asla durmaz" kuralı HATALAR için; operatör komutu bunun dışındadır.
            # state.kill_switch'e YAZILMAZ: o günlük zarar bayrağı, bu süreç komutu. Yazılırsa
            # durum dosyasında kalıcılaşır ve yeniden başlatılan ajan hiç emir gönderemez.
            self.state.last_turn_ms = now_ms()
            self.state.save()
            self.decide("OPERATOR_KILL",
                        reason=f"acil durdur: döngü sonlandırılıyor, {len(self.state.positions)} "
                               f"pozisyon borsadaki TP/SL ile korunuyor")
            print("OPERATÖR KILL: ajan temiz çıkıyor.")
            self._stop_requested = True
            return

        await self.refresh_equity()
        await self.sample_micro()
        await self.check_pending()

        local = datetime.now(tz=self.tz)
        eod = local.time() >= parse_hhmm(self.cfg.execution.flatten_local)
        flatten_now = control["flatten"] or eod
        if control["flatten"]:
            # Operatör flatten: yürüt, bayrağı DÜŞÜR, bitişi logla. Bayrak açık kalırsa gün sonuna kadar
            # yeni giriş kilitlenirdi (Faz 5 düzeltmesi). Gün sonu (eod) bayrağı ayrı; o düşürülmez.
            why = "operatör flatten"
            closed, cancelled = await self.flatten_all(why, "operator")
            write_control({"flatten": False})
            self._last_flatten = False
            self.decide("OPERATOR_FLATTEN_DONE",
                        reason=f"flatten yürütüldü: {closed} pozisyon kapatıldı, {cancelled} bekleyen "
                               f"emir iptal edildi; control.json flatten=false")
            print(f"OPERATÖR FLATTEN bitti: {closed} pozisyon, {cancelled} emir")
        elif eod and (self.state.positions or self.state.pending):
            # Gün sonu kapanışı OPERATÖR EYLEMİ DEĞİL: ayrı action, ve `control.json`'daki
            # flatten bayrağına dokunulmaz (operatör dalındaki write_control burada yok).
            why = f"gün sonu {self.cfg.execution.flatten_local}"
            self.decide("CASH", reason=why)
            closed, cancelled = await self.flatten_all(why, "eod")
            self.decide("EOD_FLATTEN_DONE",
                        reason=f"gün sonu kapanışı: {closed} pozisyon kapatıldı, {cancelled} "
                               f"bekleyen emir iptal edildi")
            print(f"GÜN SONU kapanışı bitti: {closed} pozisyon, {cancelled} emir")

        bar_ts = self.signal_due()
        if bar_ts is not None:
            # Rejim ÖNCE tazelenir ki değişim aynı mumda uygulansın (B9); 30 dk'da bir gerçekten hesaplar.
            await self.refresh_regime()
            entries_ok, why = self.regime.entries_allowed(now_ms())
            if not entries_ok:
                self.decide("WAIT", gate="regime", reason=why)
            if not orders_allowed:
                self.decide("WAIT", gate="control", reason=f"operatör {mode}: emir yok, değerlendirme sürüyor")
            await self.signal_pass(bar_ts, orders_allowed and entries_ok and not flatten_now)
            self.state.last_signal_bar_ts = bar_ts
            await self.check_time_stops()

        if now_ms() - self.last_reconcile_ms >= self.cfg.execution.reconcile_sec * 1000:
            await self.reconcile()

        # Kalp atışı decisions.jsonl'e DEĞİL state.json'a (Faz 5): dashboard canlılığı buradan okur.
        self.state.last_turn_ms = now_ms()
        self.state.last_tick_ts = datetime.now(tz=self.tz).isoformat(timespec="seconds")
        # Tur bazında aktarım: turda bir çağrı bile CLI'ya düştüyse rozet turuncu yanar (Faz 7).
        self.state.transport = "cli_fallback" if self.t.fallback_count > fb_turn_start else "mcp"
        self.state.save()

    async def run(self) -> int:
        await self.startup()
        period = self.cfg.micro.sample_sec
        while True:
            started = now_ms()
            try:
                await self.tick()
            except SystemExit:
                raise
            except Exception as exc:  # ajan ASLA tamamen durmaz (urun-mimari.md §3.3)
                self.decide("ERROR", reason=f"{type(exc).__name__}: {exc}")
                print(f"HATA turda: {type(exc).__name__}: {exc}", file=sys.stderr)
                traceback.print_exc()
                await asyncio.sleep(self.cfg.execution.error_backoff_sec)
                continue

            if getattr(self, "_stop_requested", False):
                return 0  # control.json mode=kill
            if self.args.max_turns and self.turn >= self.args.max_turns:
                print(f"--max-turns {self.args.max_turns} doldu, temiz çıkış.")
                return 0
            elapsed = (now_ms() - started) / 1000
            await asyncio.sleep(max(0.0, period - elapsed))


# ----------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description="Terazi ajan döngüsü")
    p.add_argument("--profile", required=True, help="OKX profil adı (config.yaml profiles içinde)")
    p.add_argument("--demo", action="store_true", help="MCP'yi --demo ile başlat")
    p.add_argument("--dry-run", action="store_true", help="emir gönderilmez, loglanır")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--max-turns", type=int, default=0, help="0 = sonsuz")
    args = p.parse_args()

    cfg = load_config(args.config)
    match = [v for v in cfg.profiles.values() if v["name"] == args.profile]
    if not match:
        names = [v["name"] for v in cfg.profiles.values()]
        raise SystemExit(f"profil '{args.profile}' config.yaml'da yok. Tanımlı: {names}")
    prof = match[0]
    if bool(prof["demo_flag"]) != bool(args.demo):
        raise SystemExit(
            f"profil '{args.profile}' demo_flag={prof['demo_flag']} ama --demo={args.demo}. "
            "Karışık bayrak reddedilir; config.yaml ile komut satırı aynı şeyi söylemeli."
        )
    args.expected_demo = bool(prof["expected_demo"])

    async def go() -> int:
        async with OkxTools(profile=args.profile, demo=args.demo,
                            expected_demo=args.expected_demo, dry_run=args.dry_run,
                            cli_fallback=bool(cfg.execution.cli_fallback),
                            cli_timeout_sec=float(cfg.execution.cli_timeout_sec)) as t:
            return await Agent(cfg, t, args).run()

    return asyncio.run(go())


if __name__ == "__main__":
    raise SystemExit(main())
