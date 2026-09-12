# MCP araçları ve yanıt şemaları — Faz 0 keşif çıktısı

Bu dosya **gözlem kaydıdır**, tahmin değil. Aşağıdaki her araç adı ve her alan adı
`okx-trade-mcp 1.4.6` üzerinden gerçek çağrıyla alınmıştır (12 Eylül 2026, 07:48–07:50 UTC).
Kod yazarken araç adlarını buradan al; başka yerden tahmin etme.

Resmî ATK dokümantasyonu: <https://www.okx.com/docs-v5/agent_en/#introduction>

## 0. Ortam

| Şey | Değer |
|---|---|
| `okx` CLI | 1.4.6 (a5dedf45), `/opt/homebrew/bin/okx`, Pilot: installed (darwin-arm64) |
| `okx-trade-mcp` | 1.4.6, `/opt/homebrew/bin/okx-trade-mcp` |
| Profiller | `hackathon` (demo=false → **CANLI**, 30 USDT) · `hackathondemo` (demo=true, ~100k USDT test parası) |
| Python | Sistemde 3.9.6 vardı; Faz 0'da `python@3.11` (3.11.16) kuruldu, proje venv'i `.venv/` |
| Paketler | `mcp`, `pandas 3.0.5`, `pydantic 2.13.5` |

Başlatma komutu (ajanın kullanacağı):

```bash
okx-trade-mcp --profile hackathon --modules market,account,spot,news,smartmoney
# demo için:
okx-trade-mcp --profile hackathondemo --modules market,account,spot,news,smartmoney --demo
```

`list_tools` → **69 araç**. Yüklenen modüller doğrulandı:
`market, spot, account, news, smartmoney` = enabled; `swap, futures, option, event, earn.*, bot.*` =
`MODULE_FILTERED` (kapalı). Yani `--modules` filtresi çalışıyor, swap/futures araçları hiç görünmüyor.

## 1. Python `mcp` SDK kullanımı — dikkat

Kurulu SDK sürümü alanları **snake_case** veriyor; dokümanlardaki camelCase isimler `AttributeError` atar:

| Yanlış | Doğru |
|---|---|
| `init.serverInfo` | `init.server_info` |
| `tool.inputSchema` | `tool.input_schema` |
| `result.isError` | `result.is_error` |

İskelet:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(
    command="okx-trade-mcp",
    args=["--profile", "hackathon", "--modules", "market,account,spot,news,smartmoney"],
)
async with stdio_client(params) as (r, w):
    async with ClientSession(r, w) as s:
        await s.initialize()
        res = await s.call_tool("market_get_candles", {"instId": "BTC-USDT", "bar": "15m", "limit": 3})
        payload = json.loads(res.content[0].text)
```

## 2. Yanıt zarfı — üç kat iç içe

Her MCP yanıtı tek bir text content'tir; içindeki JSON şu yapıdadır:

```
{
  "tool": "market_get_candles",
  "ok": true,
  "data": {                      # ← 1. kat: ATK zarfı
    "endpoint": "GET /api/v5/market/candles",
    "requestTime": "2026-09-12T07:48:27.196Z",
    "data": [ ... ]              # ← 2. kat: OKX'in gerçek payload'ı BURADA
  },
  "capabilities": {"readOnly": false, "hasAuth": true, "demo": false, "moduleAvailability": {...}},
  "timestamp": "..."
}
```

**Gerçek veriye erişim yolu: `payload["data"]["data"]`.** `tools.py` bunu tek yerde soymalı.

`capabilities.demo` her yanıtta gelir ve profilin canlı mı demo mu olduğunu söyler
(`hackathon` → `false`, `hackathondemo --demo` → `true`). Bu, config'e güvenmeden çalışma
anında doğrulanabilen bir güvenlik kapısıdır — emir yolunda kullan.

## 3. Araç listesi (69)

### market — 20 araç

| araç | parametreler (`*` = zorunlu) |
|---|---|
| `market_get_ticker` | `instId*:string`, `demo:boolean` |
| `market_get_tickers` | `instType*:string (SPOT/SWAP/FUTURES/OPTION/MARGIN/EVENTS)`, `uly:string`, `instFamily:string`, `demo:boolean` |
| `market_get_orderbook` | `instId*:string`, `sz:number`, `demo:boolean` |
| `market_get_candles` | `instId*:string`, `bar:string`, `after:string`, `before:string`, `limit:number`, `demo:boolean` |
| `market_get_instruments` | `instType*:string (SPOT/SWAP/FUTURES/OPTION/MARGIN/EVENTS)`, `instId:string`, `uly:string`, `instFamily:string`, `seriesId:string`, `demo:boolean` |
| `market_get_funding_rate` | `instId*:string`, `history:boolean`, `after:string`, `before:string`, `limit:number`, `demo:boolean` |
| `market_get_mark_price` | `instType*:string (MARGIN/SWAP/FUTURES/OPTION)`, `instId:string`, `uly:string`, `instFamily:string`, `demo:boolean` |
| `market_get_trades` | `instId*:string`, `limit:number`, `demo:boolean` |
| `market_get_index_ticker` | `instId:string`, `quoteCcy:string`, `demo:boolean` |
| `market_get_index_candles` | `instId*:string`, `bar:string`, `after:string`, `before:string`, `limit:number`, `history:boolean`, `demo:boolean` |
| `market_get_price_limit` | `instId*:string`, `demo:boolean` |
| `market_get_open_interest` | `instType*:string (SWAP/FUTURES/OPTION)`, `instId:string`, `uly:string`, `instFamily:string`, `demo:boolean` |
| `market_get_stock_tokens` | `instType:string (SPOT/SWAP)`, `instId:string`, `demo:boolean` |
| `market_get_instruments_by_category` | `instCategory*:string (3/4/5/6/7)`, `instType:string (SPOT/SWAP)`, `instId:string`, `demo:boolean` |
| `market_filter` | `instType*:string (SPOT/SWAP/FUTURES)`, `baseCcy:string`, `quoteCcy:string`, `settleCcy:string`, `instFamily:string`, `ctType:string (linear/inverse)`, `minLast:string`, `maxLast:string`, `minChg24hPct:string`, `maxChg24hPct:string`, `minMarketCapUsd:string`, `maxMarketCapUsd:string`, `minVolUsd24h:string`, `maxVolUsd24h:string`, `minFundingRate:string`, `maxFundingRate:string`, `minOiUsd:string`, `maxOiUsd:string`, `sortBy:string (last/chg24hPct/marketCapUsd/volUsd24h/fundingRate/oiUsd/listTime)`, `sortOrder:string (asc/desc)`, `limit:number` |
| `market_get_oi_history` | `instId*:string`, `bar:string (5m/15m/1H/4H/1D)`, `limit:number`, `ts:number` |
| `market_filter_oi_change` | `instType*:string (SWAP/FUTURES)`, `bar:string (5m/15m/1H/4H/1D)`, `minOiUsd:string`, `minVolUsd24h:string`, `minAbsOiDeltaPct:string`, `sortBy:string (oiUsd/oiDeltaUsd/oiDeltaPct/absOiDeltaPct/volUsd24h/fundingRate/last)`, `sortOrder:string (asc/desc)`, `limit:number` |
| `market_get_pair_spread` | `instIdA*:string`, `instIdB*:string`, `bar:string (5m/15m)`, `window:string`, `backtestTime:number` |
| `market_get_indicator` | `instId*:string`, `indicator*:string`, `bar:string`, `params:array`, `returnList:boolean`, `limit:integer`, `backtestTime:integer` |
| `market_list_indicators` | — |

### spot — 14 araç

| araç | parametreler (`*` = zorunlu) |
|---|---|
| `spot_place_order` | `instId*:string`, `tdMode*:string (cash/cross/isolated)`, `side*:string (buy/sell)`, `ordType*:string (market/limit/post_only/fok/ioc)`, `sz*:string`, `tgtCcy:string (base_ccy/quote_ccy)`, `px:string`, `clOrdId:string`, `tpTriggerPx:string`, `tpOrdPx:string`, `tpOrdKind:string (condition/limit)`, `tpTriggerPxType:string (last/index/mark)`, `slTriggerPx:string`, `slOrdPx:string`, `slTriggerPxType:string (last/index/mark)`, `stpMode:string (cancel_maker/cancel_taker/cancel_both)` |
| `spot_cancel_order` | `instId*:string`, `ordId:string`, `clOrdId:string` |
| `spot_amend_order` | `instId*:string`, `ordId:string`, `clOrdId:string`, `newSz:string`, `newPx:string`, `newClOrdId:string` |
| `spot_get_orders` | `status:string (open/history/archive)`, `instId:string`, `ordType:string`, `state:string`, `after:string`, `before:string`, `begin:string`, `end:string`, `limit:number` |
| `spot_place_algo_order` | `instId*:string`, `tdMode:string (cash/cross/isolated)`, `side*:string (buy/sell)`, `ordType*:string (conditional/oco/move_order_stop/trigger/chase/iceberg/twap)`, `sz*:string`, `tpTriggerPx:string`, `tpOrdPx:string`, `tpOrdKind:string (condition/limit)`, `tpTriggerPxType:string (last/index/mark)`, `slTriggerPx:string`, `slOrdPx:string`, `slTriggerPxType:string (last/index/mark)`, `stpMode:string (cancel_maker/cancel_taker/cancel_both)`, `algoClOrdId:string`, `tgtCcy:string (base_ccy/quote_ccy)`, `callbackRatio:string`, `callbackSpread:string`, `activePx:string`, `triggerPx:string`, `orderPx:string`, `advanceOrdType:string (fok/ioc)`, `triggerPxType:string (last/index/mark)`, `chaseType:string (distance/ratio)`, `chaseVal:string`, `maxChaseType:string (distance/ratio)`, `maxChaseVal:string`, `pxVar:string`, `pxSpread:string`, `szLimit:string`, `pxLimit:string`, `timeInterval:string` |
| `spot_amend_algo_order` | `instId*:string`, `algoId*:string`, `newSz:string`, `newTpTriggerPx:string`, `newTpOrdPx:string`, `newSlTriggerPx:string`, `newSlOrdPx:string` |
| `spot_cancel_algo_order` | `instId*:string`, `algoId*:string` |
| `spot_get_algo_orders` | `status:string (pending/history)`, `instId:string`, `ordType:string (conditional/oco/move_order_stop)`, `after:string`, `before:string`, `limit:number`, `state:string (effective/canceled/order_failed)` |
| `spot_get_fills` | `archive:boolean`, `instId:string`, `ordId:string`, `after:string`, `before:string`, `begin:string`, `end:string`, `limit:number` |
| `spot_batch_orders` | `action*:string (place/cancel/amend)`, `orders*:array` |
| `spot_get_order` | `instId*:string`, `ordId:string`, `clOrdId:string` |
| `spot_batch_amend` | `orders*:array` |
| `spot_batch_cancel` | `orders*:array` |
| `spot_set_leverage` | `instId:string`, `ccy:string`, `lever*:string`, `mgnMode*:string (cross/isolated)` |

### account — 14 araç

| araç | parametreler (`*` = zorunlu) |
|---|---|
| `account_get_balance` | `ccy:string` |
| `account_transfer` | `ccy*:string`, `amt*:string`, `from*:string`, `to*:string`, `type:string`, `subAcct:string`, `clientId:string` |
| `account_get_max_size` | `instId*:string`, `tdMode*:string (cross/isolated)`, `px:string`, `leverage:string`, `ccy:string` |
| `account_get_asset_balance` | `ccy:string`, `showValuation:boolean`, `valuationCcy:string` |
| `account_get_bills` | `instType:string (SPOT/MARGIN/SWAP/FUTURES/OPTION/EVENTS)`, `ccy:string`, `mgnMode:string (isolated/cross)`, `type:string`, `after:string`, `before:string`, `begin:string`, `end:string`, `limit:number` |
| `account_get_positions_history` | `instType:string (SWAP/FUTURES/MARGIN/OPTION/EVENTS)`, `instId:string`, `mgnMode:string (cross/isolated)`, `type:string`, `posId:string`, `after:string`, `before:string`, `limit:number` |
| `account_get_trade_fee` | `instType*:string (SPOT/MARGIN/SWAP/FUTURES/OPTION/EVENTS)`, `instId:string` |
| `account_get_config` | — |
| `account_get_max_withdrawal` | `ccy:string` |
| `account_get_max_avail_size` | `instId*:string`, `tdMode*:string (cross/isolated/cash)`, `ccy:string`, `reduceOnly:boolean` |
| `account_get_positions` | `instType:string (MARGIN/SWAP/FUTURES/OPTION/EVENTS)`, `instId:string`, `posId:string` |
| `account_get_bills_archive` | `instType:string (SPOT/MARGIN/SWAP/FUTURES/OPTION)`, `ccy:string`, `mgnMode:string (isolated/cross)`, `type:string`, `after:string`, `before:string`, `begin:string`, `end:string`, `limit:number` |
| `account_set_position_mode` | `posMode*:string (long_short_mode/net_mode)` |
| `account_get_balance_all` | `ccy:string`, `accounts:string`, `showValuation:boolean`, `valuationCcy:string`, `preferParallel:boolean` |

### news — 9 araç

| araç | parametreler (`*` = zorunlu) |
|---|---|
| `news_get_latest` | `coins:string`, `importance:string (high/low)`, `platform:string`, `begin:number`, `end:number`, `language:string (en-US/zh-CN)`, `detailLvl:string (brief/summary/full)`, `limit:number`, `after:string` |
| `news_get_by_coin` | `coins*:string`, `importance:string (high/low)`, `platform:string`, `begin:number`, `end:number`, `language:string (en-US/zh-CN)`, `detailLvl:string (brief/summary/full)`, `limit:number` |
| `news_search` | `keyword:string`, `coins:string`, `importance:string (high/low)`, `platform:string`, `sentiment:string (bullish/bearish/neutral)`, `sortBy:string (latest/relevant)`, `begin:number`, `end:number`, `language:string (en-US/zh-CN)`, `detailLvl:string (brief/summary/full)`, `limit:number`, `after:string` |
| `news_get_detail` | `id*:string`, `language:string (en-US/zh-CN)` |
| `news_get_coin_sentiment` | `coins*:string`, `period:string (1h/4h/24h)`, `trendPoints:number` |
| `news_get_sentiment_ranking` | `period:string (1h/4h/24h)`, `sortBy:string (hot/bullish/bearish)`, `limit:number` |
| `news_get_economic_calendar` | `region:string`, `importance:string (1/2/3)`, `before:string`, `after:string`, `limit:number` |
| `news_get_domains` | — |
| `news_list_calendar_regions` | — |

### smartmoney — 10 araç

| araç | parametreler (`*` = zorunlu) |
|---|---|
| `smartmoney_get_traders_by_filter` | `updateTime:string`, `sortBy*:string (pnl/pnlRatio)`, `period*:string (3/7/30/90)`, `minPnl:string`, `minWinRate:string`, `maxDrawdown:string`, `minAum:string`, `after:string`, `before:string`, `limit:integer` |
| `smartmoney_get_performance_by_trader` | `authorIds*:array`, `sortBy*:string (pnl/pnlRatio)`, `period*:string (3/7/30/90)` |
| `smartmoney_get_trader_positions` | `authorId*:string`, `instId:string` |
| `smartmoney_get_trader_positions_history` | `authorId*:string`, `instId:string`, `after:string`, `before:string`, `limit:integer` |
| `smartmoney_get_trader_orders_history` | `authorId*:string`, `instId:string`, `after:string`, `before:string`, `limit:integer` |
| `smartmoney_search_trader` | `keyword*:string` |
| `smartmoney_get_signal_overview_by_filter` | `topInstruments:integer`, `instCcyList:array`, `sortBy*:string (pnl/pnlRatio)`, `period*:string (3/7/30/90)`, `pnlTier:string (PNL_ANY/PNL_TOP50/PNL_TOP20/PNL_TOP5)`, `winRateTier:string (WR_ANY/WR_GE_50/WR_GE_80)`, `maxDrawdownTier:string (MR_ANY/MR_LE_20/MR_LE_50)`, `aumTier:string (AUM_ANY/AUM_TOP50/AUM_TOP20/AUM_TOP5)`, `lmtNum:integer` |
| `smartmoney_get_signal_overview_by_trader` | `authorIds*:array`, `topInstruments:integer`, `instCcyList:array`, `sortBy*:string (pnl/pnlRatio)`, `period*:string (3/7/30/90)` |
| `smartmoney_get_signal_trend_by_filter` | `instCcy*:string`, `asOfTime:string`, `granularity*:string (1h/1d)`, `limit:integer`, `sortBy*:string (pnl/pnlRatio)`, `period*:string (3/7/30/90)`, `pnlTier:string (PNL_ANY/PNL_TOP50/PNL_TOP20/PNL_TOP5)`, `winRateTier:string (WR_ANY/WR_GE_50/WR_GE_80)`, `maxDrawdownTier:string (MR_ANY/MR_LE_20/MR_LE_50)`, `aumTier:string (AUM_ANY/AUM_TOP50/AUM_TOP20/AUM_TOP5)`, `lmtNum:integer` |
| `smartmoney_get_signal_trend_by_trader` | `authorIds*:array`, `instCcy*:string`, `asOfTime:string`, `granularity*:string (1h/1d)`, `limit:integer`, `sortBy*:string (pnl/pnlRatio)`, `period*:string (3/7/30/90)` |

### trade — 1 araç

| araç | parametreler (`*` = zorunlu) |
|---|---|
| `trade_get_history` | `limit:number`, `tool:string`, `level:string (INFO/WARN/ERROR/DEBUG)`, `since:string` |

### system — 1 araç

| araç | parametreler (`*` = zorunlu) |
|---|---|
| `system_get_capabilities` | — |

Ürün mimarisindeki takma adların gerçek karşılığı (mimari dokümanı kısa ad kullanıyor):

| urun-mimari.md'de | Gerçek araç adı |
|---|---|
| account: fees | `account_get_trade_fee` |
| market: indicator (rsi) | `market_get_indicator` (+ `market_list_indicators`) |
| market: funding-rate / open-interest | `market_get_funding_rate` / `market_get_open_interest` |
| news: by-coin | `news_get_by_coin` |
| smartmoney: signal-overview-by-filter | `smartmoney_get_signal_overview_by_filter` |
| spot: place / cancel / orders / fills | `spot_place_order` / `spot_cancel_order` / `spot_get_orders` / `spot_get_fills` |

---

## 4. Çekilen veriler — alan adları ve örnek satırlar

Aşağıdaki örnekler `--profile hackathon` (canlı, salt okunur çağrılar) ile alındı.
Fiyatlar 12 Eylül 2026 07:48 UTC anlıkıdır.

### 4.1 fees — `account_get_trade_fee {"instType": "SPOT"}`

Alanlar: `category, delivery, exercise, feeGroup, fiat, instType, level, maker, makerU, makerUSDC,
ruleType, settle, taker, takerU, takerUSDC, ts`

```json
{"category":"1","instType":"SPOT","level":"Lv1","maker":"-0.0008","taker":"-0.001",
 "makerU":"","takerU":"","ruleType":"normal","ts":"1789199304456"}
```

**Dikkat — işaret:** OKX ücret oranlarını **negatif** döndürür; negatif = senden kesilen ücret.
Yani gerçek maliyet `abs(maker) = %0,08 = 8 bps`, `abs(taker) = %0,10 = 10 bps`.
Kodda `abs()` al, yoksa maliyet kapısı ücreti gelir sanır ve ters çalışır.
Tur maliyeti (taker giriş + maker çıkış) = 18 bps, (taker+taker) = 20 bps.
strateji.md §62'deki %0,08/%0,10 tahmini **birebir doğrulandı**.
`makerU/takerU` boş; USDT-marjlı kontrat alanları, spot'ta kullanılmıyor — `maker`/`taker` kullan.

### 4.2 instruments — `market_get_instruments {"instType":"SPOT","instId":"<parite>"}`

Satırda 50+ alan var; işimize yarayanlar:
`instId, baseCcy, quoteCcy, minSz, lotSz, tickSz, state, maxMktSz, maxLmtSz, maxMktAmt`

| parite | minSz | lotSz | tickSz | state |
|---|---|---|---|---|
| BTC-USDT | 0.00001 | 0.00000001 | 0.1 | live |
| ETH-USDT | 0.0001 | 0.000001 | 0.01 | live |
| SOL-USDT | 0.01 | 0.000001 | 0.01 | live |

`instId` filtresi çalışıyor → tek parite için tek satır döner (1416 satırlık listeyi taramaya gerek yok).

### 4.3 balance — `account_get_balance {}`

Üst seviye alanlar: `totalEq, adjEq, availEq, isoEq, imr, mmr, mgnRatio, ordFroz, upl, notionalUsd*,
delta*, borrowFroz, deltaNeutralStatus, uTime, details[]`

`details[]` satır alanları (43 adet); kullanacaklarımız:
`ccy, eq, cashBal, availBal, frozenBal, eqUsd, disEq, ordFrozen, upl, spotBal`

```json
{"ccy":"USDT","eq":"30","cashBal":"30","availBal":"30","frozenBal":"0","eqUsd":"29.9922","availEq":""}
```

`totalEq` = `"29.9922"` (canlı hesap: 30 USDT).

**Tuzak:** nakit hesapta üst seviye `availEq` ve `details[].availEq` **boş string** (`""`) gelir.
Kullanılabilir bakiye için `details[].availBal` oku; `availEq`'e güvenme, float'a çevirirken patlar.
Tüm sayısal alanlar string'dir — `Decimal`'e çevir, float'a değil.

### 4.4 tickers — `market_get_tickers {"instType":"SPOT"}`

**1416 satır** döner (tüm SPOT pariteleri); parite filtresi yok, listeyi kendin süz.
Tek parite için `market_get_ticker {"instId": ...}` var — döngüde onu kullan.

Alanlar: `instType, instId, last, lastSz, askPx, askSz, bidPx, bidSz, open24h, high24h, low24h,
volCcy24h, vol24h, sodUtc0, sodUtc8, ts`

Üç paritenin de **varlığı doğrulandı**:

```json
{"instId":"BTC-USDT","last":"77286.3","bidPx":"77286.2","askPx":"77286.3","vol24h":"7439.64252106","ts":"1789199306235"}
{"instId":"ETH-USDT","last":"2522.23","bidPx":"2522.22","askPx":"2522.23","vol24h":"250224.881884","ts":"1789199306185"}
{"instId":"SOL-USDT","last":"101.7",  "bidPx":"101.69", "askPx":"101.7",  "vol24h":"1168265.52505","ts":"1789199306073"}
```

`vol24h` = baz para cinsinden hacim, `volCcy24h` = kote (USDT) cinsinden. Likidite filtresinde
`volCcy24h` kullan.

### 4.5 candles — `market_get_candles {"instId":"BTC-USDT","bar":"15m","limit":3}`

Sözlük değil, **9 elemanlı dizi listesi**. İndeks anlamları:

| # | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| alan | `ts` (ms) | `o` | `h` | `l` | `c` | `vol` (baz) | `volCcy` | `volCcyQuote` | `confirm` |

```
["1789199100000","77287","77287","77262.7","77286.3","6.22250698","480884.065708675","480884.065708675","0"]
["1789198200000","77311.8","77311.9","77282.4","77287","20.50034522","1584558.233578067","1584558.233578067","1"]
["1789197300000","77346.4","77348.7","77311.8","77311.8","17.3194721","1339308.267706561","1339308.267706561","1"]
```

**Sıralama: EN YENİDEN ESKİYE.** Okunur zaman damgaları: `07:45 → 07:30 → 07:15` UTC.
CLAUDE.md kuralı doğrulandı: pandas'a vermeden önce `reversed()` uygula.

**`confirm` alanı (indeks 8) kapanmamış mumu tahmin etmeyi gereksiz kılıyor:**
`"0"` = mum hâlâ açık, `"1"` = kapanmış. Yukarıda ilk satır `"0"` — yani en yeni mum kapanmamış.
Son mumu körlemesine atmak yerine `confirm == "1"` filtresi uygula; bu hem daha sağlam
hem de 15m kapanışına 15 sn kala çalışan döngüde yanlış mum atmayı önler.
(Aynı mumu 2 dk arayla iki kez çektiğimizde `vol` 6.22 → 7.01 değişti, `confirm` hâlâ `"0"` idi —
açık mumun canlı güncellendiğinin kanıtı.)

### 4.6 orderbook — `market_get_orderbook {"instId":"BTC-USDT","sz":5}`

Alanlar: `asks, bids, ts, seqId`. `sz:5` → 5 kademe asks + 5 kademe bids.

Her kademe **4 elemanlı dizi**: `[fiyat, miktar, "0" (spot'ta hep 0, likidasyon alanı), emir_sayısı]`

```json
{"asks":[["77286.3","0.36695228","0","9"], ...],
 "bids":[["77286.2","0.55611307","0","22"], ...],
 "ts":"1789199307551","seqId":...}
```

`asks[0]` = en iyi satış, `bids[0]` = en iyi alış. Spread = `77286.3 − 77286.2 = 0.1` (≈0.013 bps).
OBI hesabı için indeks 1 (miktar) kullanılır.

### 4.7 trades — `market_get_trades {"instId":"BTC-USDT","limit":3}`

Alanlar: `instId, tradeId, px, sz, side, ts, source`

```json
{"instId":"BTC-USDT","tradeId":"1056321611","px":"77286.3","sz":"0.00002587","side":"buy","ts":"1789199306168","source":"0"}
{"instId":"BTC-USDT","tradeId":"1056321610","px":"77286.3","sz":"0.00010351","side":"buy","ts":"1789199306083","source":"0"}
{"instId":"BTC-USDT","tradeId":"1056321609","px":"77286.2","sz":"0.00191752","side":"sell","ts":"1789199306075","source":"0"}
```

**Alan adı: `side`. Değerleri: `"buy"` / `"sell"`** (küçük harf, string).
`side` = **agresörün (taker'ın) yönü** — `buy` fiyatı ask'a vurdu, `sell` bid'e vurdu.
Mikro yapı katmanında alım/satım baskısı bundan hesaplanır. Sıralama yine en yeniden eskiye.

---

## 5. CLI karşılaştırması (`okx --json`)

Aynı iki çağrı CLI ile de yapıldı:

```bash
okx --profile hackathon --json market candles BTC-USDT --bar 15m --limit 3
okx --profile hackathon --json account balance
```

**Yapı MCP ile aynı DEĞİL — tek fark zarf:**

| | MCP | CLI `--json` |
|---|---|---|
| Dış yapı | `{tool, ok, data:{endpoint, requestTime, data:[...]}, capabilities, timestamp}` | **doğrudan dizi** `[...]` |
| Gerçek veriye yol | `payload["data"]["data"]` | `payload` (kökün kendisi) |
| Alan adları | aynı | aynı |
| Satır içeriği | aynı | aynı |

Yani **iç payload birebir aynı, sadece sarmalayıcı farklı.** CLI yedeği yazarken tek yapılacak:
MCP'de iki kat soy, CLI'da hiç soyma. `okx --json --env` ile CLI de `{env, profile, data}` zarfına
sarılabiliyor ama buna ihtiyaç yok.

Mum verisi CLI'da da **en yeniden eskiye** geldi, `confirm` alanı aynı yerde (indeks 8).
CLI bakiyesi de `availEq:""` / `availBal:"30"` aynı tuzağı taşıyor.

---

## 6. İliştirilmiş TP/SL sonradan iptal edilebilir mi?

**Evet.** `okx spot place` ile emre iliştirilen TP/SL, bağımsız bir *algo order* olarak yaşar ve
kendi `algoId`'si üzerinden ayrıca değiştirilip iptal edilebilir.

CLI yüzeyi (`okx spot --help`, `okx spot algo --help`):

| İş | Komut |
|---|---|
| TP/SL iliştirerek emir | `okx spot place --instId <id> --side buy --ordType market --sz <n> --tpTriggerPx <p> --slTriggerPx <p>` |
| Ana emri değiştir | `okx spot amend --instId <id> --ordId <id> [--newSz] [--newPx]` — **fiyat/miktar sadece** |
| İliştirilmiş TP/SL'i değiştir | `okx spot algo amend --instId <id> --algoId <id> [--newTpTriggerPx] [--newTpOrdPx] [--newSlTriggerPx] [--newSlOrdPx]` |
| İliştirilmiş TP/SL'i **iptal et** | `okx spot algo cancel --instId <id> --algoId <id>` |
| `algoId`'yi bul | `okx spot algo orders [--instId <id>] [--history] [--ordType conditional\|oco]` |

`okx spot amend`'in kendi yardım metni bunu açıkça söylüyor:
> "Amend a pending spot order (price/size only; **to modify TP/SL use 'okx spot algo amend'**)"

ve `okx spot algo amend` açıklaması:
> "Amend a pending spot algo order (**including attached TP/SL**)"

**MCP tarafında tam karşılığı var** — CLI'ya düşmeye gerek yok:

| CLI | MCP aracı |
|---|---|
| `okx spot place ... --tpTriggerPx` | `spot_place_order` (`tpTriggerPx, tpOrdPx, tpOrdKind, tpTriggerPxType, slTriggerPx, slOrdPx, slTriggerPxType`) |
| `okx spot algo orders` | `spot_get_algo_orders` (`status: pending\|history`, `instId`, `ordType`, `state`) |
| `okx spot algo amend` | `spot_amend_algo_order` |
| `okx spot algo cancel` | `spot_cancel_algo_order` (`instId*`, `algoId*`) |
| `okx spot algo place` | `spot_place_algo_order` (`conditional` = tek TP/SL, `oco` = TP+SL çifti) |

Uçlar: `spot_get_algo_orders` → `GET /api/v5/trade/orders-algo-pending` (boş hesapta `data: []` döndü).

**DOĞRULANDI (Faz 2, 12 Eylül 12:01 UTC+3, `hackathondemo --demo` ile tek emir):** iliştirilmiş
TP/SL `spot_get_algo_orders(status="pending")` listesinde gerçekten `algoId` ile görünüyor.
Gözlenen satır:

```json
{"algoId":"3915846276696993797","instId":"SOL-USDT","ordType":"oco","side":"sell","state":"live",
 "sz":"0.117771","tpTriggerPx":"102.86","tpOrdPx":"102.86","slTriggerPx":"100.82","slOrdPx":"100.8"}
```

Notlar (hepsi ölçüm):
- Tip **`oco`** geliyor (TP+SL çifti tek algo emri). `ordType` filtresi kullanacaksan `oco` ara.
- `algoId` ana emrin `ordId`'sinden FARKLI ve ondan bağımsız yaşıyor.
- **`sz` dolumdan AZ:** dolum 0.117889 SOL, algo emri 0.117771. OKX alış komisyonunu **baz
  paradan** kesiyor. Çıkışta `dolum miktarı` kadar satmaya kalkarsan bakiye yetmezliğine
  düşersin — satış miktarını gerçek baz bakiyeyle sınırla.

**DÜZELTME — `tpOrdKind: "limit"` SPOT'TA ÇALIŞMIYOR.** Bu doküman önceden CLI yardım metninden
"hedefi maker limit satış yapabiliyoruz" çıkarımını yapmıştı; **bu çıkarım yanlıştı ve ölçümle
çürütüldü.** `tpOrdKind: "limit"` ile gönderilen emir şu yanıtı verdi:

```json
{"ordId":"","sCode":"51094","sMsg":"You can't place TP limit orders in spot, margin, or options trading."}
```

`tpOrdKind` hiç gönderilmediğinde emir sorunsuz geçiyor ve `tpOrdPx` sabit fiyat olarak duruyor
(yukarıdaki `oco` satırı o çağrının sonucu). `tpOrdPx = "-1"` ise piyasa emriyle çıkış demek.

**TUZAK — emir reddi `ok: true` içinde saklanıyor.** Emir başarısız olsa bile dış zarf
`"ok": true` geliyor; hata `payload["data"]["data"][0]["sCode"]` içinde ve `ordId` boş string.
`sCode`'u kontrol etmezsen başarısız emri başarılı sayar, olmayan pozisyonu takip edersin.
`tools.py` bunu `_check_scode` ile tek yerde zorluyor.

**TUZAK — `market_filter` DEMO ORTAMINDA BOŞ.** `--profile hackathondemo --demo` ile
`market_filter` **filtresiz bile 0 satır** döndürüyor (canlıda 22 satır). Canlı piyasa tarama
aracı demo hesaba bağlı değil. `market_get_instruments` ve `market_get_ticker` demo'da normal
çalışıyor — hacim doğrulaması demo'da `ticker.volCcy24h`'ten yapılmalı.

---

## 7. `--demo` profili doğrulaması

```bash
okx --profile hackathondemo --demo --json account balance
```

Çalışıyor. MCP tarafında da `capabilities.demo: true` döndü.

| ccy | cashBal | availBal | eqUsd |
|---|---|---|---|
| BTC | 1 | 1 | 77261 |
| OKB | 100 | 100 | 11449.6 |
| USDT | 5000 | 5000 | 4997.5 |
| TRY | 200000 | 200000 | 4120 |
| ETH | 1 | 1 | 2522.4 |

`totalEq` = 100350.5. Demo hesap OKX'in standart test bakiyesiyle dolu.

**Canlı ile demo'yu ayırt etme:** profil adına değil, yanıttaki `capabilities.demo` alanına bak.
`hackathon` → `false`, `hackathondemo --demo` → `true`.

---

## 8. 9 USDT'lik pozisyon minSz'ı karşılıyor mu?

strateji.md §134: boyut = equity × %30 ≈ 30 USDT'de 9 USDT.

| parite | fiyat | 9 USDT = sz | minSz | minSz'ın kaç katı | minSz'ın USDT karşılığı | lotSz'a yuvarlanmış |
|---|---|---|---|---|---|---|
| BTC-USDT | 77286.3 | 0.00011645 | 0.00001 | **11.6×** | 0.77 USDT | 0.00011645 |
| ETH-USDT | 2522.23 | 0.00356827 | 0.0001 | **35.7×** | 0.25 USDT | 0.00356800 |
| SOL-USDT | 101.7 | 0.08849558 | 0.01 | **8.8×** | 1.02 USDT | 0.08849500 |

**Üçü de rahatça geçiyor.** En dar marj SOL'da: 8.8×.

Emniyet payı: 9 USDT'nin minSz'a *eşitlenmesi* için fiyatların BTC 900.000 (12×), ETH 90.000 (36×),
SOL 900 (9×) USDT'ye çıkması gerekir. Yarışma ufkunda gerçekçi değil — üç parite de güvenli.

Pratik sonuç `tools.py` için:
- Miktarı `lotSz`'a **aşağı** yuvarla (`ROUND_DOWN`), yoksa bakiyeyi aşabilirsin.
- Yuvarlama sonrası `sz >= minSz` kontrolünü yine de yap (fiyat fırlarsa diye) ve
  geçmiyorsa işlemi reddet — sessizce minSz'a yükseltme.
- Fiyatı `tickSz`'a yuvarla: BTC 0.1, ETH 0.01, SOL 0.01.
- Tüm sayılar API'ye **string** gider; `Decimal` ile hesapla, `str()` ile gönder.

## 9. news / smartmoney / funding — gerçek zarflar (Faz 5, 12 Eylül)

Hepsi standart üç kat zarf (`payload.data.data`), `tools._call` olduğu gibi soyar. Alanlar **string**.

| araç | `data.data` şekli |
|---|---|
| `news_get_by_coin {"coins":"BTC","importance":"high","limit":2,"detailLvl":"brief"}` | `[{"details":[{id, title, importance, ccyList, ccySentiments:[{ccy,sentiment}], cTime, sourceUrl, platformList, summary:"", content:""}]}]` — brief'te `summary`/`content` **boş**; başlık + duygu kullanılır |
| `news_get_coin_sentiment {"coins":"BTC","period":"1h"}` | `[{"details":[{ccy, mentionCnt, newsMentionCnt, xMentionCnt, sentiment:{label, bullishCnt, bullishRatio, bearishCnt, bearishRatio, neutralCnt}, trend:[]}], period, ts}]` |
| `news_get_sentiment_ranking {"period":"4h","limit":3}` | aynı öğe şekli, `details` çok ccy |
| `market_get_funding_rate {"instId":"BTC-USDT-SWAP"}` | `[{fundingRate, nextFundingRate, premium, fundingTime, nextFundingTime, settFundingRate, settState, minFundingRate, maxFundingRate, ...}]` |
| `smartmoney_get_signal_overview_by_filter {"instCcyList":["BTC","ETH","SOL"],"sortBy":"pnl","period":"7"}` | `[{ccy, dataVersion, longShortRatio:{longRatio, shortRatio, longRatioVs1h, longRatioVs24h, longRatioVs7d, weightedLongRatio, weightedShortRatio}, longTraders, shortTraders, notional:{longNotionalUsdt, shortNotionalUsdt, netNotionalUsdt, totalNotionalUsdt, smartMoneyLongAvgEntry, ...}, winRate:{avgLongWinRate, avgShortWinRate}, tradersQualified, tradersWithPosition}]` |

**TUZAK — `mcp` 2.2 istemcisi smartmoney'de sahte hata atıyor.** `ClientSession.call_tool` sonucu aracın
`output_schema`'sına göre doğruluyor; `smartmoney_get_signal_overview_by_filter` için
`RuntimeError: Invalid structured content ... 'endpoint' is a required property` geliyor. Ham
`content[0].text` sağlam ve standart zarf. `tools.LenientSession` doğrulamayı kapatır (biz
`structured_content` kullanmıyoruz). Diğer dört araçta doğrulama zaten geçiyordu.

`news_*` `limit` tavanı ölçülmedi; `tools.py` 20 ile sınırlar, LLM girdisi 5 kullanır.
