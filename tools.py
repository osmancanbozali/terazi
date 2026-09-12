"""Terazi — OKX ATK MCP istemcisi (ince katman).

Faz 1 kapsamı: sadece `market_*` ve `account_get_trade_fee`.
Bu dosyada BİLEREK yok:
  - emir aracı (`spot_*`) — emre giden yol risk kapısından geçer, o Faz 2'de
  - CLI yedeği — Faz 1'de MCP-only
  - otomatik retry — tek deneme, hata yukarı fırlar (CLAUDE.md mutlak yasak)

Araç adları `docs/mcp-araclari.md`'den alınmıştır; tahmin edilmemiştir.
"""

from __future__ import annotations

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

# market_get_candles tek çağrıda en fazla bunu döndürüyor (Faz 1'de ölçüldü:
# limit=500 istendi, 300 satır geldi). Fazlası için `after` ile sayfala.
CANDLES_MAX_LIMIT = 300

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
    """Bir MCP aracı hata döndürdü. Retry yok; çağıran karar verir."""

    def __init__(self, tool: str, detail: Any) -> None:
        self.tool = tool
        self.detail = detail
        super().__init__(f"{tool}: {detail!r}")


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
    ) -> None:
        args = ["--profile", profile, "--modules", modules]
        if demo:
            args.append("--demo")
        self._params = StdioServerParameters(command=command, args=args)
        self._profile = profile
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._demo: bool | None = None

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

    # ---- tek soyma noktası ----

    async def _call(self, tool: str, args: dict[str, Any]) -> Any:
        """Aracı çağır, üç kat zarfı soy, `capabilities.demo`'yu sakla.

        Zarf: {tool, ok, data:{endpoint, requestTime, data:<GERÇEK>}, capabilities, timestamp}
        Retry YOK. Hata → OkxToolError.
        """
        if self._session is None:
            raise RuntimeError("OkxTools oturumu açık değil; 'async with' içinde kullan.")

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
        """`market_filter`. Yanıt fazladan bir kat derin: [{"rows": [...]}]."""
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
            "limit": limit,
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
        rows = await self._call("market_get_orderbook", {"instId": inst_id, "sz": sz})
        return _decimalize(rows[0])

    async def get_trades(self, inst_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._call("market_get_trades", {"instId": inst_id, "limit": limit})
        return [_decimalize(r) for r in rows]

    # ---- account ----

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
