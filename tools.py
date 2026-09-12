"""Terazi — OKX ATK MCP istemcisi (ince katman).

Faz 2 kapsamı: `market_*`, `account_*` ve `spot_*` (emir yüzeyi dahil).

Retry politikası — CLAUDE.md mutlak yasağı koda gömülü:
  - VERİ çağrıları: 2 deneme, üssel bekleme.
  - EMİR çağrıları (`ORDER_TOOLS`): TEK deneme. `_call` bunu assert ile zorlar;
    çift emir riski yüzünden yeniden deneme yasak.

Emir güvenlik kapısı: her `spot_place_order` öncesi yanıtlardan okunan `capabilities.demo`,
`expected_demo` ile karşılaştırılır. Eşleşmezse emir GÖNDERİLMEZ, `SafetyGateError` atılır.
`dry_run=True` ise emir araçları MCP'ye hiç gitmez.

Bu dosyada BİLEREK yok:
  - CLI yedeği — Faz 7 (docs/urun-mimari.md §3.2)

Araç adları `docs/mcp-araclari.md`'den alınmıştır; tahmin edilmemiştir.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, ConfigDict

DEFAULT_MODULES = "market,account,spot,news,smartmoney"

# Mum verisi 15m ise bir bar 900000 ms; bar süresi ms cinsinden.
BAR_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1H": 3_600_000,
    "2H": 7_200_000,
    "4H": 14_400_000,
    "1D": 86_400_000,
}

# Bilinen API tavanları (Faz 1'de ÖLÇÜLDÜ, tahmin değil):
#   candles: limit=500 istendi, 300 satır geldi — sessizce kırpıyor.
#   filter:  limit=200 → kod 902 "Bind Arguments Validation Failure" — PATLIYOR.
#   indicator: returnList limit=300 istendi, 100 nokta geldi.
CANDLES_MAX_LIMIT = 300
FILTER_MAX_LIMIT = 100
INDICATOR_MAX_LIMIT = 100

# Emir araçları: bunlarda YENİDEN DENEME YOK (çift emir riski). `_call` assert ile zorlar.
ORDER_TOOLS: frozenset[str] = frozenset(
    {
        "spot_place_order",
        "spot_cancel_order",
        "spot_amend_order",
        "spot_place_algo_order",
        "spot_amend_algo_order",
        "spot_cancel_algo_order",
        "spot_batch_orders",
        "spot_batch_amend",
        "spot_batch_cancel",
    }
)

DATA_ATTEMPTS = 2  # veri çağrısı deneme sayısı
RETRY_BACKOFF_SEC = 0.5  # 1. hata sonrası bekleme; her denemede ikiye katlanır

# Sayısala çevrilmeyecek alanlar: kimlikler, zaman damgaları, enum'lar.
# Bunlar rakamdan ibaret olsa bile string kalmalı (ts'i Decimal yapmak indekslemeyi bozar).
KEEP_STR: frozenset[str] = frozenset(
    {
        "instId", "instType", "instFamily", "uly",
        "baseCcy", "quoteCcy", "settleCcy", "ccy",
        "ts", "uTime", "cTime", "fillTime", "listTime", "expTime", "nextFundingTime",
        "tradeId", "ordId", "clOrdId", "algoId", "algoClOrdId", "billId", "posId",
        "side", "posSide", "state", "ordType", "tdMode", "execType", "source",
        "category", "level", "ruleType", "feeGroup", "optType", "alias",
        "rank", "mode",
    }
)


class OkxToolError(RuntimeError):
    """Bir MCP aracı hata döndürdü. Emir araçlarında retry yok; çağıran karar verir."""

    def __init__(self, tool: str, detail: Any) -> None:
        self.tool = tool
        self.detail = detail
        super().__init__(f"{tool}: {detail!r}")


def _check_scode(tool: str, row: dict[str, Any]) -> dict[str, Any]:
    """Emir yanıtındaki `sCode`'u doğrula.

    TUZAK (Faz 2'de yaşandı): emir REDDEDİLSE BİLE dış zarf `ok: true` gelir ve
    `payload["data"]["data"][0]` içinde `sCode` sıfırdan farklı olur (`ordId` boş string).
    Bunu kontrol etmezsek başarısız emri başarılı sayar, olmayan pozisyonu takip ederiz.
    """
    code = str(row.get("sCode", "0"))
    if code not in ("0", ""):
        raise OkxToolError(tool, {"sCode": code, "sMsg": row.get("sMsg"), "row": row})
    return row


class SafetyGateError(RuntimeError):
    """Emir güvenlik kapısı emri durdurdu: `capabilities.demo` != `expected_demo`.

    Emir MCP'ye hiç gitmedi. Çağıran bunu `decisions.jsonl`'e ERROR olarak yazmalı.
    """


class Candle(BaseModel):
    """Tek bir mum. `market_get_candles` 9 elemanlı konumsal dizi döndürür."""

    model_config = ConfigDict(frozen=True)

    ts: int  # ms cinsinden açılış zamanı
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741 — OKX alan adı
    c: Decimal
    vol: Decimal
    vol_ccy: Decimal
    vol_ccy_quote: Decimal
    confirm: bool  # "1" = kapanmış, "0" = hâlâ açık

    @classmethod
    def from_row(cls, row: list[str]) -> "Candle":
        return cls(
            ts=int(row[0]),
            o=Decimal(row[1]),
            h=Decimal(row[2]),
            l=Decimal(row[3]),
            c=Decimal(row[4]),
            vol=Decimal(row[5]),
            vol_ccy=Decimal(row[6]),
            vol_ccy_quote=Decimal(row[7]),
            confirm=row[8] == "1",
        )


def _to_decimal(value: str) -> Decimal | None:
    """Boş string (`availEq:""` tuzağı) → None. Sayı değilse ValueError."""
    if value == "":
        return None
    return Decimal(value)


def _decimalize(value: Any, key: str | None = None) -> Any:
    """Sözlük/liste içindeki sayısal string'leri Decimal'e çevirir.

    KEEP_STR'deki anahtarlar ve sayıya çevrilemeyen string'ler olduğu gibi kalır.
    Boş string sayısal bir alansa None olur — ama hangi alanın sayısal olduğunu
    bilmediğimiz için boş string'e dokunmuyoruz; çağıran `or None` yapsın.
    """
    if isinstance(value, dict):
        return {k: _decimalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimalize(v, key) for v in value]
    if isinstance(value, str) and key not in KEEP_STR and value != "":
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    return value


class OkxTools:
    """`okx-trade-mcp` stdio oturumu. Async context manager olarak kullanılır.

        async with OkxTools(profile="hackathon") as t:
            candles = await t.get_candles("BTC-USDT", "15m", limit=10)
    """

    def __init__(
        self,
        profile: str,
        modules: str = DEFAULT_MODULES,
        demo: bool = False,
        command: str = "okx-trade-mcp",
        expected_demo: bool | None = None,
        dry_run: bool = False,
    ) -> None:
        args = ["--profile", profile, "--modules", modules]
        if demo:
            args.append("--demo")
        self._params = StdioServerParameters(command=command, args=args)
        self._profile = profile
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._demo: bool | None = None
        # Güvenlik kapısı: None = kapı kapalı, emir aracı çağrılırsa reddedilir.
        self._expected_demo = expected_demo
        self._dry_run = dry_run

    # ---- oturum ----

    async def __aenter__(self) -> "OkxTools":
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(self._params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    @property
    def profile(self) -> str:
        return self._profile

    @property
    def demo(self) -> bool | None:
        """Yanıtlardan okunan `capabilities.demo`. Canlı/demo ayrımı için tek güvenilir kaynak.

        Config'e veya profil adına değil buna bak (docs/mcp-araclari.md §7).
        İlk çağrıdan önce None.
        """
        return self._demo

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    # ---- tek soyma noktası ----

    async def _call(self, tool: str, args: dict[str, Any], attempts: int = DATA_ATTEMPTS) -> Any:
        """Aracı çağır, üç kat zarfı soy, `capabilities.demo`'yu sakla.

        Zarf: {tool, ok, data:{endpoint, requestTime, data:<GERÇEK>}, capabilities, timestamp}

        `attempts`: veri çağrıları için 2 (üssel bekleme). EMİR araçları için 1 olmak ZORUNDA —
        assert bunu zorlar, yorumla bırakılmaz (CLAUDE.md: emir çağrılarında retry YOK).
        """
        if tool in ORDER_TOOLS:
            assert attempts == 1, f"{tool}: emir çağrısında yeniden deneme yasak (attempts={attempts})"
        if self._session is None:
            raise RuntimeError("OkxTools oturumu açık değil; 'async with' içinde kullan.")

        delay = RETRY_BACKOFF_SEC
        for attempt in range(1, attempts + 1):
            try:
                return await self._call_once(tool, args)
            except OkxToolError:
                if attempt == attempts:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
        raise AssertionError("ulaşılamaz")

    async def _call_once(self, tool: str, args: dict[str, Any]) -> Any:
        assert self._session is not None
        result = await self._session.call_tool(tool, args)  # SDK snake_case
        if not result.content:
            raise OkxToolError(tool, "boş yanıt (content yok)")
        payload = json.loads(result.content[0].text)

        if result.is_error or not payload.get("ok"):
            raise OkxToolError(tool, payload)

        caps = payload.get("capabilities") or {}
        if "demo" in caps:
            seen = bool(caps["demo"])
            if self._demo is not None and self._demo != seen:
                raise OkxToolError(
                    tool, f"capabilities.demo oturum içinde değişti: {self._demo} → {seen}"
                )
            self._demo = seen

        return payload["data"]["data"]

    # ---- emir güvenlik kapısı ----

    async def _gate(self, inst_id: str) -> None:
        """Emir öncesi tek kapı. Geçmezse emir MCP'ye HİÇ gitmez.

        `capabilities.demo` profil adına değil gerçek yanıta dayanır (docs/mcp-araclari.md §7).
        Henüz hiç yanıt görülmediyse önce ucuz bir veri çağrısıyla doldurulur.
        """
        if self._expected_demo is None:
            raise SafetyGateError(
                "expected_demo verilmedi; emir yolu kapalı. OkxTools(expected_demo=...) ile aç."
            )
        if self._demo is None:
            await self.get_ticker(inst_id)  # capabilities.demo'yu doldurur
        if self._demo != self._expected_demo:
            raise SafetyGateError(
                f"EMİR DURDURULDU: capabilities.demo={self._demo} != expected_demo="
                f"{self._expected_demo} (profil={self._profile})"
            )

    # ---- market ----

    async def get_candles(
        self,
        inst_id: str,
        bar: str = "15m",
        limit: int = CANDLES_MAX_LIMIT,
        after: int | str | None = None,
    ) -> list[Candle]:
        """Mumlar, ESKİDEN YENİYE sıralı (API en yeniden eskiye verir; burada ters çevrilir).

        `confirm` filtresi UYGULANMAZ — ham veri döner, kapanmamış mumu atmak çağıranın işi.
        `after`: bu ts'ten ESKİ mumlar (sayfalama).
        """
        args: dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": min(limit, CANDLES_MAX_LIMIT)}
        if after is not None:
            args["after"] = str(after)
        rows = await self._call("market_get_candles", args)
        return [Candle.from_row(r) for r in reversed(rows)]

    async def get_candles_history(
        self, inst_id: str, bar: str = "15m", need: int = CANDLES_MAX_LIMIT
    ) -> list[Candle]:
        """`need` adede ulaşana kadar `after` ile sayfalar. Eskiden yeniye, ts'e göre tekil."""
        by_ts: dict[int, Candle] = {}
        after: int | None = None
        while len(by_ts) < need:
            page = await self.get_candles(inst_id, bar, CANDLES_MAX_LIMIT, after)
            if not page:
                break
            before = len(by_ts)
            for candle in page:
                by_ts[candle.ts] = candle
            if len(by_ts) == before:  # yeni satır gelmedi, sonsuz döngüyü kes
                break
            after = page[0].ts  # sayfanın en eskisi
        return [by_ts[ts] for ts in sorted(by_ts)][-need:]

    async def filter_instruments(self, **kwargs: Any) -> list[dict[str, Any]]:
        """`market_filter`. Yanıt fazladan bir kat derin: [{"rows": [...]}].

        `limit` 100'de tavan — 100'ün üstü kod 902 ile PATLIYOR, sessiz kırpma yok.
        """
        if "limit" in kwargs and kwargs["limit"] is not None:
            kwargs["limit"] = min(int(kwargs["limit"]), FILTER_MAX_LIMIT)
        data = await self._call("market_filter", kwargs)
        rows = data[0].get("rows", []) if data else []
        return [_decimalize(r) for r in rows]

    async def get_indicator_series(
        self,
        inst_id: str,
        indicator: str,
        bar: str = "15m",
        params: list[int] | None = None,
        limit: int = 100,
    ) -> list[tuple[int, Decimal]]:
        """`market_get_indicator`. (ts, değer) listesi, API'nin verdiği sırada (eskiden yeniye).

        Yanıt fazladan iki kat derin:
        [{"data": [{"timeframes": {<bar>: {"indicators": {<IND>: [{ts, values:{<param>: v}}]}}}}]}]
        NOT: `returnList` 100 noktada tavan yapıyor (Faz 1'de ölçüldü).
        """
        args: dict[str, Any] = {
            "instId": inst_id,
            "indicator": indicator,
            "bar": bar,
            "returnList": True,
            "limit": min(limit, INDICATOR_MAX_LIMIT),  # returnList 100 noktada tavan
        }
        if params:
            args["params"] = params
        data = await self._call("market_get_indicator", args)

        inner = data[0]["data"][0]
        indicators = inner["timeframes"][bar]["indicators"]
        key = indicator.upper()
        if key not in indicators:
            raise OkxToolError("market_get_indicator", f"{key} yok; gelenler: {list(indicators)}")
        points = indicators[key]

        param_key = str(params[0]) if params else None
        out: list[tuple[int, Decimal]] = []
        for point in points:
            values = point["values"]
            raw = values[param_key] if param_key in values else next(iter(values.values()))
            out.append((int(point["ts"]), Decimal(raw)))
        return out

    async def get_ticker(self, inst_id: str) -> dict[str, Any]:
        rows = await self._call("market_get_ticker", {"instId": inst_id})
        return _decimalize(rows[0])

    async def get_instruments(
        self, inst_type: str = "SPOT", inst_id: str | None = None
    ) -> list[dict[str, Any]]:
        args: dict[str, Any] = {"instType": inst_type}
        if inst_id:
            args["instId"] = inst_id
        rows = await self._call("market_get_instruments", args)
        return [_decimalize(r) for r in rows]

    async def get_orderbook(self, inst_id: str, sz: int = 5) -> dict[str, Any]:
        """Emir defteri. Her kademe 4 elemanlı dizi: [fiyat, miktar, "0", emir_sayısı]."""
        rows = await self._call("market_get_orderbook", {"instId": inst_id, "sz": sz})
        return _decimalize(rows[0])

    async def get_trades(self, inst_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Son işlemler, en yeniden eskiye. `side` = agresörün (taker'ın) yönü."""
        rows = await self._call("market_get_trades", {"instId": inst_id, "limit": limit})
        return [_decimalize(r) for r in rows]

    # ---- account ----

    async def get_balance(self, ccy: str | None = None) -> dict[str, Any]:
        """Bakiye. `availEq` NAKİT HESAPTA BOŞ STRING — kullanılabilir için `availBal` oku."""
        args: dict[str, Any] = {}
        if ccy:
            args["ccy"] = ccy
        rows = await self._call("account_get_balance", args)
        return _decimalize(rows[0])

    async def get_avail_bal(self, ccy: str = "USDT") -> Decimal:
        """`details[]` içinden tek para biriminin kullanılabilir bakiyesi (`availBal`).

        `availEq` boş string geldiği için ona bakılmaz (docs/mcp-araclari.md §4.3).
        """
        bal = await self.get_balance()
        for row in bal.get("details") or []:
            if row.get("ccy") == ccy:
                raw = row.get("availBal")
                return Decimal(str(raw)) if raw not in ("", None) else Decimal(0)
        return Decimal(0)

    async def get_trade_fee(
        self, inst_type: str = "SPOT", inst_id: str | None = None
    ) -> dict[str, Any]:
        """Ham ücret satırı. DİKKAT: OKX oranları NEGATİF döndürür (negatif = senden kesilen).

        `abs()` almak çağıranın işi — burada bilerek dokunulmuyor ki işaret kaybolmasın.
        """
        args: dict[str, Any] = {"instType": inst_type}
        if inst_id:
            args["instId"] = inst_id
        rows = await self._call("account_get_trade_fee", args)
        return _decimalize(rows[0])

    # ---- spot: EMİR YOLU ----
    #
    # Buradaki her metot TEK deneme (attempts=1). Yeniden deneme yok, çünkü ikinci deneme
    # birincinin borsaya ulaşıp ulaşmadığını bilemez → çift emir riski.
    # `place_order` ayrıca güvenlik kapısından geçer; okuma araçları (orders/fills/algo) geçmez.

    async def place_order(
        self,
        inst_id: str,
        side: str,
        ord_type: str,
        sz: str,
        px: str | None = None,
        td_mode: str = "cash",
        tgt_ccy: str | None = None,
        cl_ord_id: str | None = None,
        tp_trigger_px: str | None = None,
        tp_ord_px: str | None = None,
        tp_ord_kind: str | None = None,
        sl_trigger_px: str | None = None,
        sl_ord_px: str | None = None,
    ) -> dict[str, Any]:
        """`spot_place_order`. TEK DENEME + güvenlik kapısı + dry-run.

        Tüm fiyat/miktar alanları ÇAĞIRAN tarafından tickSz/lotSz'a yuvarlanmış string olmalı;
        burada yuvarlama yapılmaz (sessiz düzeltme, sessiz hatadır).

        `dry_run` ise MCP'ye hiç gitmez; `{"dry_run": True, "args": ...}` döner.
        Kapı geçmezse `SafetyGateError` — emir gönderilmez.
        """
        await self._gate(inst_id)

        args: dict[str, Any] = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
        }
        optional = {
            "px": px,
            "tgtCcy": tgt_ccy,
            "clOrdId": cl_ord_id,
            "tpTriggerPx": tp_trigger_px,
            "tpOrdPx": tp_ord_px,
            "tpOrdKind": tp_ord_kind,
            "slTriggerPx": sl_trigger_px,
            "slOrdPx": sl_ord_px,
        }
        args.update({k: v for k, v in optional.items() if v is not None})

        if self._dry_run:
            return {"dry_run": True, "args": args}

        rows = await self._call("spot_place_order", args, attempts=1)
        return _check_scode("spot_place_order", _decimalize(rows[0])) if rows else {}

    async def cancel_order(
        self, inst_id: str, ord_id: str | None = None, cl_ord_id: str | None = None
    ) -> dict[str, Any]:
        """`spot_cancel_order`. TEK DENEME."""
        args: dict[str, Any] = {"instId": inst_id}
        if ord_id:
            args["ordId"] = ord_id
        if cl_ord_id:
            args["clOrdId"] = cl_ord_id
        if self._dry_run:
            return {"dry_run": True, "args": args}
        rows = await self._call("spot_cancel_order", args, attempts=1)
        return _check_scode("spot_cancel_order", _decimalize(rows[0])) if rows else {}

    async def cancel_algo_order(self, inst_id: str, algo_id: str) -> dict[str, Any]:
        """`spot_cancel_algo_order` — iliştirilmiş TP/SL'i iptal eder. TEK DENEME.

        Zaman stopu ve flatten bu çağrıyı yapmadan market sell atmamalı: aksi halde
        TP/SL borsada yaşamaya devam eder ve elimizde olmayan miktarı satmaya çalışır.
        """
        args = {"instId": inst_id, "algoId": algo_id}
        if self._dry_run:
            return {"dry_run": True, "args": args}
        rows = await self._call("spot_cancel_algo_order", args, attempts=1)
        return _check_scode("spot_cancel_algo_order", _decimalize(rows[0])) if rows else {}

    async def amend_algo_order(self, inst_id: str, algo_id: str, **fields: Any) -> dict[str, Any]:
        """`spot_amend_algo_order`. TEK DENEME. Alanlar: newSz/newTpTriggerPx/newTpOrdPx/
        newSlTriggerPx/newSlOrdPx (docs/mcp-araclari.md §6)."""
        args: dict[str, Any] = {"instId": inst_id, "algoId": algo_id}
        args.update({k: v for k, v in fields.items() if v is not None})
        if self._dry_run:
            return {"dry_run": True, "args": args}
        rows = await self._call("spot_amend_algo_order", args, attempts=1)
        return _check_scode("spot_amend_algo_order", _decimalize(rows[0])) if rows else {}

    # ---- spot: okuma (uzlaştırma) ----

    async def get_orders(
        self, status: str = "open", inst_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        args: dict[str, Any] = {"status": status}
        if inst_id:
            args["instId"] = inst_id
        if limit:
            args["limit"] = limit
        rows = await self._call("spot_get_orders", args)
        return [_decimalize(r) for r in rows]

    async def get_order(
        self, inst_id: str, ord_id: str | None = None, cl_ord_id: str | None = None
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"instId": inst_id}
        if ord_id:
            args["ordId"] = ord_id
        if cl_ord_id:
            args["clOrdId"] = cl_ord_id
        rows = await self._call("spot_get_order", args)
        return _decimalize(rows[0]) if rows else {}

    async def get_fills(
        self, inst_id: str | None = None, ord_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Dolumlar. Kısmi dolum için gerçek miktar BURADAN gelir, emirden değil."""
        args: dict[str, Any] = {}
        if inst_id:
            args["instId"] = inst_id
        if ord_id:
            args["ordId"] = ord_id
        if limit:
            args["limit"] = limit
        rows = await self._call("spot_get_fills", args)
        return [_decimalize(r) for r in rows]

    async def get_algo_orders(
        self, status: str = "pending", inst_id: str | None = None, ord_type: str | None = None
    ) -> list[dict[str, Any]]:
        """İliştirilmiş TP/SL burada `algoId` ile görünür — pozisyonun çıkış emri kimliği."""
        args: dict[str, Any] = {"status": status}
        if inst_id:
            args["instId"] = inst_id
        if ord_type:
            args["ordType"] = ord_type
        rows = await self._call("spot_get_algo_orders", args)
        return [_decimalize(r) for r in rows]
