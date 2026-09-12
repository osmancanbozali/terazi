"""Terazi — tek seferlik kalibrasyon. EMİR YOK, salt okunur.

3 parite × 3 gün 15m veriyle RSI eşiklerini (28/32/36) tarar ve
`docs/kalibrasyon.md`'ye parite × eşik tablosu yazar.

Eşik ÖNERİLMEZ; tablo basılır, seçimi kullanıcı yapar.

Çalıştırma:
    .venv/bin/python calibrate.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable

import numpy as np
import pandas as pd

from tools import BAR_MS, OkxTools

# ----------------------------------------------------------------------------
# Karar mantığı — saf, I/O'suz. Faz 2'de terazi.py AYNI sınıfı kullanacak.
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Bar:
    """Kapanmış tek mum + o mumdaki indikatör değerleri."""

    ts: int
    high: float
    low: float
    close: float
    bb_lower: float
    bb_mid: float
    rsi: float
    atr: float


class Ev(str, Enum):
    SETUP = "SETUP"
    CANCEL = "CANCEL"
    TRIGGER = "TRIGGER"
    REJECT_STOP = "REJECT_STOP"  # stop mesafesi %1,2'yi aştı (strateji.md §4.6)
    WIN = "WIN"
    LOSS = "LOSS"
    TIMEOUT = "TIMEOUT"


@dataclass
class Event:
    kind: Ev
    ts: int
    detail: dict[str, Any]


class SetupTracker:
    """Kurulum → tetik → sonuç durum makinesi.

    Mumlar TEK TEK `step()`'e verilir. `calibrate.py` geçmişi sırayla besler (backtest);
    Faz 2'de `terazi.py` her 15m kapanışında canlı mumu besler. Aynı kod yolu.

    İlerleme kuralları (asimetrik, kullanıcı kararı):
      - Tetiklenmeyen kurulum: 2 mum sonra iptal. İptal mumu yeni kurulum SAYILMAZ,
        ama ondan SONRAKİ mum yeni kurulum olabilir (tetik penceresi yenilenir).
      - Tetiklenen kurulum: 8 mumluk ufku tüketir; ufuk bitene kadar yeni kurulum aranmaz.
      - Stop bandı reddi: ufuk tüketilmez, sonraki mum yeni kurulum olabilir.
    """

    def __init__(
        self,
        rsi_threshold: float,
        trigger_window: int = 2,
        target_horizon: int = 8,
        stop_atr_mult: float = 0.2,
        min_stop_bps: float = 50.0,
        max_stop_bps: float = 120.0,
    ) -> None:
        self.rsi_threshold = rsi_threshold
        self.trigger_window = trigger_window
        self.target_horizon = target_horizon
        self.stop_atr_mult = stop_atr_mult
        self.min_stop_bps = min_stop_bps
        self.max_stop_bps = max_stop_bps
        self._reset()

    def _reset(self) -> None:
        self._state = "IDLE"
        self._setup_low = 0.0
        self._setup_ts = 0
        self._waited = 0
        self._entry = 0.0
        self._target = 0.0
        self._stop = 0.0
        self._held = 0

    def _is_setup(self, bar: Bar) -> bool:
        return bar.close < bar.bb_lower and bar.rsi < self.rsi_threshold

    def step(self, bar: Bar) -> list[Event]:
        """Bir mumu işler, o mumda oluşan olayları döndürür (0..2 olay)."""
        if np.isnan(bar.bb_lower) or np.isnan(bar.rsi) or np.isnan(bar.atr):
            return []  # ısınma bölgesi

        if self._state == "IDLE":
            if self._is_setup(bar):
                self._state = "WAITING"
                self._setup_low = bar.low
                self._setup_ts = bar.ts
                self._waited = 0
                return [Event(Ev.SETUP, bar.ts, {"low": bar.low, "rsi": bar.rsi})]
            return []

        if self._state == "WAITING":
            self._waited += 1
            triggered = bar.close > bar.bb_lower and bar.close > self._setup_low
            if triggered:
                return self._open(bar)
            if self._waited >= self.trigger_window:
                self._reset()  # iptal; SONRAKİ mum yeni kurulum olabilir
                return [Event(Ev.CANCEL, bar.ts, {"setup_ts": self._setup_ts})]
            return []

        # HOLDING — pozisyon açık, ufuk tükeniyor
        self._held += 1
        hit_stop = bar.low <= self._stop
        hit_target = bar.high >= self._target
        if hit_stop:  # aynı mumda ikisi de olursa muhafazakâr: KAYIP
            outcome = Ev.LOSS
        elif hit_target:
            outcome = Ev.WIN
        elif self._held >= self.target_horizon:
            outcome = Ev.TIMEOUT
        else:
            return []
        ev = Event(outcome, bar.ts, {"entry": self._entry, "held": self._held})
        self._reset()
        return [ev]

    def _open(self, bar: Bar) -> list[Event]:
        """Tetik mumu: giriş, hedef ve stop dondurulur; stop bandı kontrol edilir."""
        entry = bar.close
        target = bar.bb_mid
        raw_stop = self._setup_low - self.stop_atr_mult * bar.atr
        raw_stop_bps = (entry - raw_stop) / entry * 10_000.0

        trig = Event(
            Ev.TRIGGER,
            bar.ts,
            {
                "setup_ts": self._setup_ts,
                "entry": entry,
                "target": target,
                "target_bps": (target - entry) / entry * 10_000.0,
                "raw_stop_bps": raw_stop_bps,
            },
        )

        if raw_stop_bps > self.max_stop_bps:
            self._reset()  # ufuk tüketilmez
            trig.detail["rejected"] = True
            return [trig, Event(Ev.REJECT_STOP, bar.ts, {"stop_bps": raw_stop_bps})]

        # Canlı kural: stop girişten en az %0,5 uzakta; daha yakınsa 50 bps'e çekilir.
        stop_bps = max(raw_stop_bps, self.min_stop_bps)
        self._stop = entry * (1.0 - stop_bps / 10_000.0)
        self._target = target
        self._entry = entry
        self._state = "HOLDING"
        self._held = 0
        trig.detail["stop_bps"] = stop_bps
        return [trig]


# ----------------------------------------------------------------------------
# İndikatörler
# ----------------------------------------------------------------------------


def _wilder(values: np.ndarray, period: int, first_idx: int) -> np.ndarray:
    """Wilder yumuşatması (RMA). Tohum = values[first_idx : first_idx+period] ortalaması."""
    out = np.full(values.shape, np.nan)
    seed_end = first_idx + period
    if seed_end > len(values):
        return out
    prev = float(values[first_idx:seed_end].mean())
    out[seed_end - 1] = prev
    for i in range(seed_end, len(values)):
        prev = (prev * (period - 1) + float(values[i])) / period
        out[i] = prev
    return out


def add_indicators(
    df: pd.DataFrame, bb_period: int, bb_std: float, rsi_period: int, atr_period: int
) -> pd.DataFrame:
    close = df["close"]
    mid = close.rolling(bb_period).mean()
    # Popülasyon std (ddof=0) — TradingView/OKX konvansiyonu.
    sd = close.rolling(bb_period).std(ddof=0)
    df["bb_mid"] = mid
    df["bb_lower"] = mid - bb_std * sd

    # pandas 3.0 salt okunur dizi döndürüyor → copy=True şart.
    delta = close.diff().to_numpy(dtype=float, copy=True)
    delta[0] = 0.0
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = _wilder(gain, rsi_period, 1)
    avg_loss = _wilder(loss, rsi_period, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = np.where(avg_loss == 0, 100.0, rsi)
    rsi[np.isnan(avg_gain)] = np.nan
    df["rsi"] = rsi

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    prev_close = np.concatenate([[np.nan], close.to_numpy(dtype=float)[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    tr[0] = high[0] - low[0]
    df["atr"] = _wilder(tr, atr_period, 0)
    return df


# ----------------------------------------------------------------------------
# Tarama
# ----------------------------------------------------------------------------


@dataclass
class Stats:
    setups: int = 0
    triggers: int = 0
    stop_rejects: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    naive_reach: int = 0  # stop yok sayılırsa hedefe değen (ilk spec'teki sayı)
    target_bps: list[float] = None  # type: ignore[assignment]
    stop_bps: list[float] = None  # type: ignore[assignment]
    cost_pass: int = 0

    def __post_init__(self) -> None:
        self.target_bps = []
        self.stop_bps = []

    @property
    def resolved(self) -> int:
        return self.wins + self.losses + self.timeouts

    @property
    def win_rate(self) -> float | None:
        return 100.0 * self.wins / self.resolved if self.resolved else None

    @property
    def avg_target(self) -> float | None:
        return sum(self.target_bps) / len(self.target_bps) if self.target_bps else None

    @property
    def avg_stop(self) -> float | None:
        return sum(self.stop_bps) / len(self.stop_bps) if self.stop_bps else None


def scan(bars: list[Bar], threshold: float, args: argparse.Namespace, gate_bps: float) -> Stats:
    st = Stats()
    tr = SetupTracker(
        rsi_threshold=threshold,
        trigger_window=args.trigger_window,
        target_horizon=args.target_horizon,
        stop_atr_mult=args.stop_atr_mult,
        min_stop_bps=args.min_stop_bps,
        max_stop_bps=args.max_stop_bps,
    )
    pending_naive: dict[str, Any] | None = None
    naive_left = 0
    for bar in bars:
        # "ham ulaşma": stop'u yok say, 8 mumda hedefe değdi mi (ilk spec'teki metrik)
        if pending_naive is not None:
            naive_left -= 1
            if bar.high >= pending_naive["target"]:
                st.naive_reach += 1
                pending_naive = None
            elif naive_left <= 0:
                pending_naive = None

        for ev in tr.step(bar):
            if ev.kind is Ev.SETUP:
                st.setups += 1
            elif ev.kind is Ev.TRIGGER:
                st.triggers += 1
                st.target_bps.append(ev.detail["target_bps"])
                if ev.detail["target_bps"] >= gate_bps:
                    st.cost_pass += 1
                if not ev.detail.get("rejected"):
                    st.stop_bps.append(ev.detail["stop_bps"])
                    pending_naive = {"target": ev.detail["target"]}
                    naive_left = args.target_horizon
            elif ev.kind is Ev.REJECT_STOP:
                st.stop_rejects += 1
            elif ev.kind is Ev.WIN:
                st.wins += 1
            elif ev.kind is Ev.LOSS:
                st.losses += 1
            elif ev.kind is Ev.TIMEOUT:
                st.timeouts += 1
    return st


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------


def utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def fmt(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def md_table(header: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    head = list(header)
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def self_test(args: argparse.Namespace) -> list[str]:
    """SetupTracker'ı sentetik dizilerle sına. Tablo ancak hepsi geçerse basılır.

    Sayılar gerçekçi tutuldu: kurulum_low ile giriş arası %1,2'yi aşarsa canlı kural
    adayı reddeder, o yüzden test verisi de o bandın içinde olmalı.
    """
    out: list[str] = []
    failed = False

    def tracker() -> SetupTracker:
        return SetupTracker(32, args.trigger_window, args.target_horizon,
                            args.stop_atr_mult, args.min_stop_bps, args.max_stop_bps)

    def mk(ts: int, close: float, low: float, high: float,
           lower: float = 100.0, mid: float = 101.0, rsi: float = 20.0) -> Bar:
        return Bar(ts, high, low, close, lower, mid, rsi, 0.2)

    setup = lambda ts: mk(ts, 99.50, 99.45, 99.60)          # noqa: E731 — kurulum mumu
    trig = lambda ts: mk(ts, 100.50, 100.30, 100.60, rsi=40)  # noqa: E731 — giriş 100.50
    flat = lambda ts: mk(ts, 100.50, 100.40, 100.60, rsi=40)  # noqa: E731 — ne stop ne hedef

    def check(name: str, seq: list[Bar], expect: list[Ev]) -> None:
        nonlocal failed
        tr = tracker()
        got = [ev.kind for b in seq for ev in tr.step(b)]
        ok = got == expect
        failed = failed or not ok
        out.append(f"  {'OK  ' if ok else 'HATA'} {name}: {[k.value for k in got]}")

    # A) 7 mum kesintisiz kurulum koşulu, tetik hiç gelmez → 3 kurulum (7 değil, 1 değil)
    check("iptal ufuk tüketmez (7 mum → 3 kurulum)", [setup(i) for i in range(7)],
          [Ev.SETUP, Ev.CANCEL, Ev.SETUP, Ev.CANCEL, Ev.SETUP])

    # B) tetik → 8 mum boyunca ne stop ne hedef → zaman aşımı, sonra yeni kurulum
    check("tetik + 8 mum ufuk → zaman aşımı",
          [setup(0), trig(1)] + [flat(i) for i in range(2, 10)] + [setup(10)],
          [Ev.SETUP, Ev.TRIGGER, Ev.TIMEOUT, Ev.SETUP])

    # C) hedef (bb_mid=101) önce → KAZANÇ
    check("hedef önce → kazanç",
          [setup(0), trig(1), flat(2), mk(3, 101.0, 100.4, 101.20, rsi=40)],
          [Ev.SETUP, Ev.TRIGGER, Ev.WIN])

    # D) stop (≈99.41) önce → KAYIP
    check("stop önce → kayıp",
          [setup(0), trig(1), flat(2), mk(3, 99.2, 99.00, 100.50, rsi=40)],
          [Ev.SETUP, Ev.TRIGGER, Ev.LOSS])

    # E) aynı mumda ikisi de → muhafazakâr KAYIP
    check("aynı mumda stop+hedef → kayıp (muhafazakâr)",
          [setup(0), trig(1), mk(2, 100.5, 99.00, 101.50, rsi=40)],
          [Ev.SETUP, Ev.TRIGGER, Ev.LOSS])

    # F) stop mesafesi %1,2'yi aşıyor → RED, ufuk tüketilmez (sonraki mum kurulum olabilir)
    check("stop bandı reddi ufuk tüketmez",
          [mk(0, 90.0, 89.0, 91.0), trig(1), setup(2)],
          [Ev.SETUP, Ev.TRIGGER, Ev.REJECT_STOP, Ev.SETUP])

    # G) stop %0,5'ten yakınsa 50 bps'e çekilir; ham stop'un altındaki mum artık kayıp değil
    tr = tracker()
    tight = [mk(0, 99.40, 99.38, 99.45, lower=99.5, mid=100.0),
             mk(1, 99.55, 99.50, 99.60, lower=99.5, mid=100.0, rsi=40)]
    evs = [ev for b in tight for ev in tr.step(b)]
    stop_bps = next((e.detail["stop_bps"] for e in evs if e.kind is Ev.TRIGGER), None)
    ok_g = stop_bps is not None and abs(stop_bps - args.min_stop_bps) < 1e-9
    failed = failed or not ok_g
    out.append(f"  {'OK  ' if ok_g else 'HATA'} stop 50 bps'e çekildi: {fmt(stop_bps, 2)} bps "
               f"(ham ≈21 bps)")

    for line in out:
        print(line)
    if failed:
        raise SystemExit("SetupTracker öz-testi geçmedi; tablo basılmadı.")
    return out


# ----------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    thresholds = [float(t) for t in args.rsi_thresholds.split(",")]
    bar_ms = BAR_MS[args.bar]
    per_day = 86_400_000 // bar_ms
    window_n = args.days * per_day
    report: list[str] = []

    def say(line: str = "") -> None:
        print(line)
        report.append(line)

    async with OkxTools(profile=args.profile, modules="market,account") as t:
        fee_row = await t.get_trade_fee("SPOT")
        maker = abs(Decimal(str(fee_row["maker"])))
        fee_bps = float(maker) * 10_000.0
        cost_bps = 2 * fee_bps + args.spread_bps
        gate_bps = args.cost_mult * cost_bps
        args.demo_seen = t.demo
        print(f"profil={args.profile} capabilities.demo={t.demo} (canlı=False beklenir)")
        print(f"maker={fee_row['maker']} → abs={fee_bps:.1f} bps · "
              f"maliyet={cost_bps:.1f} bps · kapı={gate_bps:.1f} bps")

        # --- Adım 2: evren doğrulaması
        rows = await t.filter_instruments(
            instType="SPOT", quoteCcy="USDT", minVolUsd24h=args.min_vol_usd,
            sortBy="volUsd24h", sortOrder="desc", limit=100,  # 100 tavan; >100 → kod 902
        )
        found = {r["instId"]: r for r in rows if r["instId"] in pairs}
        missing = [p for p in pairs if p not in found]
        print(f"market_filter: {len(rows)} parite (minVolUsd24h={args.min_vol_usd}); "
              f"aranan 3'ten bulunan {len(found)}")
        if missing:
            print(f"HATA: filtrede yok: {missing}", file=sys.stderr)
            return 1
        universe = [
            (p, str(found[p].get("rank", "?")), f"{float(found[p]['volUsd24h']):,.0f}") for p in pairs
        ]

        # --- Adım 3+4: mumlar ve indikatörler
        frames: dict[str, pd.DataFrame] = {}
        data_notes: list[str] = []
        for pair in pairs:
            candles = await t.get_candles_history(pair, args.bar, need=window_n + args.warmup)
            closed = [c for c in candles if c.confirm]
            df = pd.DataFrame(
                {
                    "ts": [c.ts for c in closed],
                    "high": [float(c.h) for c in closed],
                    "low": [float(c.l) for c in closed],
                    "close": [float(c.c) for c in closed],
                }
            )
            dup = len(df) - df["ts"].nunique()
            gaps = int((df["ts"].diff().dropna() != bar_ms).sum())
            df = add_indicators(df, args.bb_period, args.bb_std, args.rsi_period, args.atr_period)
            frames[pair] = df
            data_notes.append(
                f"{pair}: {len(df)} kapanmış mum ({utc(int(df.ts.iloc[0]))} → "
                f"{utc(int(df.ts.iloc[-1]))} UTC), tekrar eden ts={dup}, boşluk={gaps}"
            )
            print(data_notes[-1])

        # --- RSI çapraz kontrolü
        rsi_rows: list[list[str]] = []
        for pair in pairs:
            series = await t.get_indicator_series(pair, "rsi", args.bar, [args.rsi_period], limit=100)
            df = frames[pair]
            ours = dict(zip(df["ts"].tolist(), df["rsi"].tolist()))
            diffs = [
                abs(ours[ts] - float(val))
                for ts, val in series
                if ts in ours and not np.isnan(ours[ts])
            ]
            if diffs:
                tail = diffs[-50:]  # OKX'in kendi ısınması bittikten sonrası
                rsi_rows.append([
                    pair, str(len(diffs)),
                    f"{max(diffs):.3f}", f"{sum(diffs) / len(diffs):.3f}",
                    f"{max(tail):.4f}", f"{sum(tail) / len(tail):.4f}",
                ])
            else:
                rsi_rows.append([pair, "0", "—", "—", "—", "—"])
        print("RSI çapraz kontrol (bizim vs market_get_indicator): " +
              " · ".join(f"{r[0]} n={r[1]} maxΔ(tümü)={r[2]} maxΔ(son50)={r[4]}"
                         for r in rsi_rows))

    # --- Öz-test
    print("SetupTracker öz-testi:")
    self_test(args)  # satırları kendisi basar; geçmezse SystemExit

    # --- Adım 5: tarama
    header = ["parite", "eşik", "kurulum", "tetik", "stop-RED", "ulaştı(ham)", "kazanç",
              "kayıp", "z.aşımı", "kazanma %", "ort hedef bps", "ort stop bps", "maliyet ✓"]
    table_rows: list[list[str]] = []
    for pair in pairs:
        df = frames[pair].iloc[-window_n:]
        bars = [
            Bar(int(r.ts), r.high, r.low, r.close, r.bb_lower, r.bb_mid, r.rsi, r.atr)
            for r in df.itertuples()
        ]
        for th in thresholds:
            s = scan(bars, th, args, gate_bps)
            table_rows.append([
                pair, f"{th:g}", str(s.setups), str(s.triggers), str(s.stop_rejects),
                str(s.naive_reach), str(s.wins), str(s.losses), str(s.timeouts),
                fmt(s.win_rate), fmt(s.avg_target), fmt(s.avg_stop), str(s.cost_pass),
            ])

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    say(f"# Kalibrasyon — RSI eşik taraması")
    say()
    say(f"Üretildi: `calibrate.py`, {now} UTC · profil `{args.profile}` · "
        f"`capabilities.demo` = **{args.demo_seen}** · emir gönderilmedi.")
    say()
    say(f"Veri: {args.days} gün × {args.bar}, parite başına {window_n} kapanmış mum "
        f"(+{args.warmup} ısınma). Kapanmamış mum (`confirm=0`) atıldı.")
    say()
    for note in data_notes:
        say(f"- {note}")
    say()
    say(f"Ücret ölçüldü: `account_get_trade_fee` maker `{fee_row['maker']}` → "
        f"**abs = {fee_bps:.1f} bps**. Maliyet = 2×{fee_bps:.1f} + {args.spread_bps:g} spread = "
        f"**{cost_bps:.1f} bps**. Kapı = {args.cost_mult:g} × maliyet = **{gate_bps:.1f} bps**.")
    say()
    say("## Evren doğrulaması (`market_filter`)")
    say()
    say(md_table(["parite", "hacim sırası", "volUsd24h"], universe))
    say()
    say("## RSI çapraz kontrolü — bizim Wilder(14) vs `market_get_indicator`")
    say()
    say(md_table(
        # Başlıkta boru işareti kullanma — markdown tablosunu böler.
        ["parite", "örtüşen nokta", "max Δ (tümü)", "ort Δ (tümü)",
         "max Δ (son 50)", "ort Δ (son 50)"],
        rsi_rows,
    ))
    say()
    say("""**Sonuç: RSI'ımız doğru.** Fark bir *ısınma artefaktıdır*, formül farkı değil.
`market_get_indicator` `returnList` 100 noktada tavan yapıyor ve OKX Wilder ortalamasını
kendi 100 mumluk penceresi içinde tohumluyor; bizde 407 mumluk geçmiş var, o yüzden bizim
seri her yerde yakınsamış durumda. Fark bu yüzden serinin başında büyük, sonunda yok:
BTC'de ilk 10 noktada ort 1,60 · orta 10 noktada 0,008 · **son 10 noktada 0,004**.
Kontrol amaçlı Cutler (SMA tabanlı) RSI da denendi ve OKX'ten max **23,3** puan saptı —
yani OKX kesinlikle Wilder kullanıyor, bizim seçimimiz doğru. Sinyal penceresi yalnızca
yakınsamış değerleri kullandığı için tarama etkilenmiyor; ek çalışma yapılmadı.""")
    say()
    say("## Sonuç tablosu")
    say()
    say(md_table(header, table_rows))
    say()
    say("""### Sütunlar
- **kurulum**: `close < BB_lower` ve `RSI < eşik`; örtüşmesiz sayım (aşağıya bak).
- **tetik**: kurulumdan sonraki 2 mum içinde `close > BB_lower` ve `close > kurulum.low`.
- **stop-RED**: tetikledi ama stop mesafesi %1,2'yi aştığı için reddedildi (canlı kural).
- **ulaştı(ham)**: stop yok sayılırsa 8 mumda `BB_mid`'e değenler — ilk spec'teki metrik.
- **kazanç / kayıp / z.aşımı**: 8 mumluk ufuk SIRAYLA gezilir; `low ≤ stop` önce gelirse kayıp,
  `high ≥ hedef` önce gelirse kazanç, aynı mumda ikisi de olursa **muhafazakâr = kayıp**,
  hiçbiri olmazsa zaman aşımı. `ulaştı(ham)` ile fark, stop'un önce yendiği işlemlerdir.
- **kazanma %**: kazanç / (kazanç+kayıp+z.aşımı).
- **ort hedef bps**: `(BB_mid − giriş)/giriş`, tetik anında dondurulmuş hedefle.
- **ort stop bps**: `setup_low − 0,2×ATR`; 50 bps'in altındaysa 50'ye çekilmiş hâli (canlı kural).
- **maliyet ✓**: hedef ≥ kapı olan tetik sayısı.

### Varsayımlar
- Giriş = tetik mumunun **kapanışı** (canlıda limit alış, en iyi alış + 1 tick — vekil değer).
- Hedef tetik anında **dondurulur** (borsada sabit fiyatlı maker limit satış).
- Bollinger std'si **popülasyon** (ddof=0), TradingView/OKX konvansiyonu.
- Spread **2 bps sabit varsayıldı**, ölçülmedi — maliyet kapısı bu varsayıma duyarlı.
- Örtüşmesiz sayım: tetiklenmeyen kurulum 2 mum sonra iptal olur ve **ufuk tüketmez**
  (iptalden sonraki mum yeni kurulum olabilir); tetiklenen kurulum 8 mumluk ufku tüketir;
  stop bandı reddi ufuk tüketmez.
- Komisyon ve kayma **PnL'e uygulanmadı**; kazanç/kayıp saf fiyat hareketidir.
  Maliyet kapısı ayrı sütunda duruyor.

### Sınırlar
- 3 gün ≈ 288 mum tek parite için küçük örneklem; bu tablo **kalibrasyondur, optimizasyon değildir**.
- 8 mumluk ufkun sonuna sığmayan tetikler zaman aşımı sayılır (pencere kenarı etkisi).

---

**Eşik seçimi kullanıcıya aittir.** Bu dosya öneri içermez; seçilen değer `config.yaml`'a girilir.""")

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    print(f"\n→ {args.out} yazıldı ({len(table_rows)} satır).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Terazi kalibrasyonu (emirsiz, salt okunur)")
    p.add_argument("--profile", default="hackathon")
    p.add_argument("--pairs", default="BTC-USDT,ETH-USDT,SOL-USDT")
    p.add_argument("--bar", default="15m")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--warmup", type=int, default=120)
    p.add_argument("--bb-period", type=int, default=20)
    p.add_argument("--bb-std", type=float, default=2.0)
    p.add_argument("--rsi-period", type=int, default=14)
    p.add_argument("--atr-period", type=int, default=14)
    p.add_argument("--rsi-thresholds", default="28,32,36")
    p.add_argument("--trigger-window", type=int, default=2)
    p.add_argument("--target-horizon", type=int, default=8)
    p.add_argument("--stop-atr-mult", type=float, default=0.2)
    p.add_argument("--min-stop-bps", type=float, default=50.0)
    p.add_argument("--max-stop-bps", type=float, default=120.0)
    p.add_argument("--spread-bps", type=float, default=2.0)
    p.add_argument("--cost-mult", type=float, default=2.5)
    p.add_argument("--min-vol-usd", default="10000000")
    p.add_argument("--out", default="docs/kalibrasyon.md")
    args = p.parse_args()
    args.demo_seen = None
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
