# STATUS

## Şu anki faz
**Faz 2 — `terazi.py` + `tools.py` MVP: TAMAM** (12 Eylül 2026, 09:07 UTC).
Demo'da bir emir uçtan uca geçti: giriş → dolum → `algoId` yakalama → kurtarma → kapatma.
**Canlıya emir gönderilmedi.** Sıradaki: Faz 3 — canlı (judge off).

### (b) testinin cevabı: EVET, algoId iliştirilmiş TP/SL listesinde görünüyor
`docs/mcp-araclari.md` §6 madde 9 **kapandı.** `spot_get_algo_orders(status="pending")`:

```json
{"algoId":"3915846276696993797","instId":"SOL-USDT","ordType":"oco","side":"sell","state":"live",
 "sz":"0.117771","tpTriggerPx":"102.86","tpOrdPx":"102.86","slTriggerPx":"100.82","slOrdPx":"100.8"}
```

Tip `oco` (TP+SL tek algo emri), `algoId` ana emrin `ordId`'sinden bağımsız. 60 saniyelik
uzlaştırma döngüsünün bel bağladığı varsayım artık ölçülmüş gerçek.

### Faz 2'de bitenler
- **`config.yaml`** oluşturuldu — tüm sayısal eşiklerin tek kaynağı. 5 parite, RSI eşiği 36,
  zaman stopu 12 mum, maliyet çarpanı 2,5, spread fallback 2 bps, stop bandı 50–120 bps,
  profiller (live=hackathon/expected_demo=false, demo=hackathondemo/expected_demo=true).
  `docs/strateji.md` §10 tablosu bu değerlerle güncellendi.
- **`tools.py` tamamlandı:** `account_get_balance` (+`availBal` yardımcısı), tüm `spot_*` emir ve
  uzlaştırma araçları. Limit tavanları metot düzeyinde zorlandı (filter 100, candles 300,
  indicator 100). Veri çağrıları 2 deneme + üssel bekleme; **emir çağrılarında retry `assert` ile
  yasaklandı** (`ORDER_TOOLS` frozenset'i, `attempts>1` → AssertionError). Emir güvenlik kapısı
  (`capabilities.demo` vs `expected_demo`) ve `--dry-run` bağlandı.
- **`terazi.py`** (tek dosya): 20 sn tur, control.json, mikro katman (OBI/TFI/spread + 30 dk medyan),
  15m kapanış+15 sn sinyal geçişi, rejim (BTC 1H 48 mum), 5 kapı sırayla, iliştirilmiş TP/SL'li
  limit alış, 90 sn TTL, 60 sn uzlaştırma, zaman stopu, gün sonu/flatten, state kurtarma.
  `SetupTracker` ve `add_indicators` `calibrate.py`'den import — canlı ile backtest aynı kod yolu.
- **Testler (hepsi geçti):**
  (a) `hackathon --dry-run` 3 tur: 3 karar satırı, 15 mikro satırı, `capabilities.demo=False`,
  `orders.jsonl` hiç oluşmadı. (b) demo'da emir → dolum → algoId → flatten ile kapanış.
  (c) pozisyon açıkken `state.json` silindi, yeniden başlatmada uzlaştırma pozisyonu **ve**
  algoId'yi borsadan kurdu (`KURTARMA SOL-USDT: sz=0.117771 entry=101.79 algoId=…`) — dosyadaki
  0.117889 değil, **borsanın gerçeği** 0.117771 alındı.
- Emir sonrası config geri alındı: eşik 36, `demo_test.enabled: false`; yedekle **birebir** diff.

### Faz 2 sürprizleri (hepsi ölçüm, tahmin değil)
18. **`tpOrdKind: "limit"` SPOT'TA ÇALIŞMIYOR** — kod 51094 "You can't place TP limit orders in
    spot, margin, or options trading." `docs/mcp-araclari.md` §6'nın CLI yardımından yaptığı
    çıkarım yanlıştı, düzeltildi. `tpOrdKind` hiç gönderilmeyince emir geçiyor ve `tpOrdPx`
    sabit fiyat olarak duruyor; strateji.md'nin "hedef BB_mid" gereksinimi korunuyor.
19. **Emir reddi `ok: true` içinde saklanıyor.** Dış zarf başarılı görünüyor, hata
    `data.data[0].sCode`'da ve `ordId` boş string. İlk denemede başarısız emri başarılı saydık.
    `tools.py` artık `_check_scode` ile tek yerde zorluyor — dört emir metodunun hepsinde.
20. **`market_filter` demo ortamında FİLTRESİZ BİLE 0 satır** döndürüyor (canlıda 22).
    Canlı piyasa tarama aracı demo hesaba bağlı değil. Evren doğrulaması bu yüzden iki kaynaklı:
    filtre satır döndürürse o, döndürmezse `ticker.volCcy24h` — hangisi kullanıldığı loglanıyor.
21. **OKX alış komisyonunu BAZ PARADAN kesiyor.** Dolum 0.117889 SOL, satılabilir 0.117771.
    Dolum miktarı kadar satmaya kalkmak bakiye yetmezliği demek; çıkış miktarı artık gerçek baz
    bakiyeyle sınırlanıyor. Borsanın kendi algo emri de 0.117771 ile kurulmuş.
22. **Gerçek spread varsayımdan 150× küçük.** Ölçülen BTC medyanı **0,013 bps**, varsayım 2 bps idi.
    Maliyet kapısı 45,0 bps yerine ~40,0 bps'e iniyor, yani kalibrasyon tablosundan **daha
    geçirgen**. Kalibrasyonun "spread 2 bps" varsayımı muhafazakâr çıktı.
23. **Kapıda reddedilen aday paritenin ufkunu tüketiyor.** `SetupTracker` tetikte HOLDING'e geçtiği
    için, aday sonradan mikro/maliyet/risk kapısında reddedilse de o parite 12 mum yeni kurulum
    aramıyor. Bu **bilinçli**: kalibrasyonun "tetiklenen kurulum ufku tüketir" semantiği ile canlı
    aynı kalsın diye. Yön muhafazakâr (canlı daha az işlem yapar), ama bilinmesi gerekiyor.
24. Demo testinde mikro kapısı bir adayı gerçekten reddetti (OBI −0,025 < 0) — kapıların sahte
    olmadığının kanıtı; ikinci denemede OBI +0,130 ile geçti.

### Faz 2'de ertelenenler
- **CLI yedeği (Faz 7).** `transport` alanı şimdilik sabit `"mcp"`.
- **judge (Faz 5).** İmza bırakıldı: `async def judge(candidate, cfg, tools) -> Verdict`;
  `llm.enabled: false` iken pass-through, `true` iken `NotImplementedError`.
- **Gerçek PnL'de komisyon.** Kill switch/PnL `totalEq` farkından ölçülüyor (komisyon dolaylı
  olarak içinde); pozisyon başına net PnL hesabı hâlâ saf fiyat farkı.
- **Zaman stopu ve gün sonu canlı olarak test edilmedi** — kod yolu flatten ile aynı ve flatten
  demo'da çalıştı, ama 12 mum dolmuş bir pozisyon görülmedi (Faz 7'ye).
- `demo_test` bloğu config'de kapalı duruyor; canlıda `capabilities.demo is not True` iken ajan
  başlamayı reddediyor (bu da test edildi).

### Canlıya geçiş komutu — ÇALIŞTIRILMADI, kullanıcı geçecek
```bash
cd /Users/osmancanbozali/Desktop/terazi
# Önce kontrol: config.yaml'da rsi_setup_threshold 36 ve demo_test.enabled false olmalı.
.venv/bin/python terazi.py --profile hackathon
```
Bayraklar: `--demo` YOK, `--dry-run` YOK (ikisi de emri engeller). `--max-turns` verilmezse
sonsuz döngü. Duraklatma/durdurma `control.json` ile: `{"mode":"pause"}` · `{"mode":"kill"}` ·
`{"mode":"run","flatten":true}`. Güvenlik kapısı canlıda `expected_demo=false` bekler; demo
MCP'sine yanlışlıkla bağlanılırsa emir gitmez, `decisions.jsonl`'e ERROR düşer.

## Faz 2 ön işi — zaman aşımı çıkış sütunu (12 Eylül, 08:42 UTC)
`calibrate.py`'ye tek sütun eklendi: **z.aşımı çıkış bps** — zaman aşımına düşen tetiklerde
`j+8` kapanışında çıkılsaydı ortalama PnL bps. Tarama 5 pariteyle yenilendi (XRP + DOGE eklendi;
ikisinde de 407 kapanmış mum, tekrar eden ts=0, boşluk=0 — veri temiz).

Eşik **36**: BTC +14,2 · ETH +2,0 · SOL +1,8 · XRP −1,8 · DOGE −9,5 bps.
12 zaman aşımı tetiği üzerinden **ağırlıklı ortalama +1,1 bps**; 18 bps tur maliyeti düşülünce
**−16,9 bps**.

**Yorum:** zaman aşımı kovası fiyat olarak yatay, komisyonla birlikte kayıp. `j+8`'de erken çıkmak
bir kâr kaynağı DEĞİL; zaman stopu hasar sınırlayıcıdır. Bu, ufku 8 mumda kesmek yerine
`time_stop_bars: 12` seçimini destekliyor (pozisyona hedefe gitmesi için daha fazla alan).

## Faz 1 özeti
**`calibrate.py`: TAMAM** (12 Eylül 2026, 08:30 UTC). Tablo `docs/kalibrasyon.md`'de.
Eşik seçimi Faz 2'de yapıldı: **36** (sinyal sıklığına göre), `config.yaml`'da.

## Faz 1'de bitenler
- `tools.py` ilk taslağı: `OkxTools` async context manager, üç kat zarfı **tek yerde** (`_call`)
  soyuyor, `capabilities.demo`'yu her yanıttan okuyup saklıyor ve oturum içinde değişirse hata
  atıyor. `Candle` pydantic modeli (`ts:int`, OHLCV `Decimal`, `confirm:bool`).
  Yüzey: `get_candles`, `get_candles_history`, `filter_instruments`, `get_indicator_series`,
  `get_ticker`, `get_instruments`, `get_orderbook`, `get_trades`, `get_trade_fee`.
  **Emir aracı yok, CLI yedeği yok, retry yok** (hepsi bilinçli; Faz 2'ye).
- `calibrate.py`: 3 parite × 3 gün 15m, RSI 28/32/36 taraması. **Emir gönderilmedi.**
  Ücret canlıdan çekildi: `maker=-0.0008` → `abs`=8,0 bps, maliyet 18,0 bps, kapı 45,0 bps —
  strateji.md §62 tahmini yine birebir tuttu.
- Veri sağlamlığı doğrulandı: üç paritede de 407 kapanmış mum, **tekrar eden ts=0, boşluk=0**
  (sayfa sınırında bile). Analiz penceresi son 288 mum, öncesi ısınma.
- `SetupTracker` durum makinesi + **7 öz-test** (hepsi geçti). Faz 2'de `terazi.py` bu sınıfa
  canlı mumu tek tek verecek — backtest ile canlının sapması imkânsız.
- Tablo `docs/kalibrasyon.md`'ye yazıldı: parite × eşik, kazanç/kayıp/zaman aşımı ayrımıyla.

## Faz 0'da bitenler
- `okx` CLI 1.4.6 ve `okx-trade-mcp` 1.4.6 kurulu doğrulandı; Pilot: installed (darwin-arm64).
- Python 3.11.16 kuruldu (sistemde 3.9.6 vardı, `mcp` SDK 3.10+ istiyor). Proje venv'i `.venv/`,
  içinde `mcp`, `pandas 3.0.5`, `pydantic 2.13.5`.
- `okx-trade-mcp --profile hackathon --modules market,account,spot,news,smartmoney` stdio olarak
  başlatıldı, Python `mcp` SDK ile `list_tools` çağrıldı → **69 araç**. Modül filtresi çalışıyor
  (swap/futures/option/event/earn/bot = `MODULE_FILTERED`).
- Tüm araç adları + parametre şemaları `docs/mcp-araclari.md`'ye yazıldı. **Artık araç adı tahmin edilmiyor.**
- 9 veri çağrısı gerçek yanıtla doğrulandı (fees, instruments ×3, balance, tickers, candles,
  orderbook, trades); alan adları ve birer örnek satır dokümana işlendi.
- CLI karşılaştırması yapıldı (candles + balance, `--json`): iç payload birebir aynı, sadece zarf farklı.
- `okx spot --help` / `okx spot algo --help` incelendi; iliştirilmiş TP/SL'in iptal yolu çıkarıldı.
- `--demo` profili (`hackathondemo`) balance ile doğrulandı: totalEq 100350.5, 5000 USDT test parası.
- 9 USDT'lik pozisyon üç paritede de minSz'ı karşılıyor (BTC 11.6×, ETH 35.7×, SOL 8.8×).
- **Emir gönderilmedi** (ne canlı ne demo).

## Bilinen sorunlar / sürprizler
1. **Ücretler negatif geliyor.** `account_get_trade_fee` → `maker: "-0.0008"`, `taker: "-0.001"`.
   Negatif = senden kesilen. Maliyet kapısında **`abs()` al**, yoksa ücreti gelir sanıp ters çalışır.
   Mutlak değerler strateji.md §62 tahminini birebir doğruluyor (8 bps maker / 10 bps taker).
2. **Yanıt zarfı üç kat iç içe.** Gerçek veri `payload["data"]["data"]`'da. `tools.py` bunu tek
   yerde soymalı.
3. **`mcp` SDK alanları snake_case.** `server_info`, `input_schema`, `is_error` — camelCase
   karşılıkları `AttributeError` atıyor. Faz 0'da üç kez buna takıldık.
4. **Mumlarda `confirm` alanı var (indeks 8): `"1"` kapanmış, `"0"` açık.** Son mumu körlemesine
   atmaya gerek yok; `confirm == "1"` filtresi daha sağlam. Sıralamanın en yeniden eskiye olduğu
   doğrulandı (07:45 → 07:30 → 07:15). Açık mumun canlı güncellendiğini de gözledik
   (aynı mumun `vol`'ü 2 dk'da 6.22 → 7.01 oldu).
5. **Nakit hesapta `availEq` boş string (`""`) geliyor** — hem üst seviyede hem `details[]` içinde.
   Kullanılabilir bakiye için `availBal` oku. Tüm sayısal alanlar string; `Decimal` kullan, float değil.
6. **`market_get_tickers` 1416 satır döndürüyor, parite filtresi yok.** Tek parite için
   `market_get_ticker` var — döngüde onu kullan, 1416 satırı her 20 sn'de çekme.
7. **`capabilities.demo` her yanıtta geliyor** (`hackathon` → `false`, `hackathondemo --demo` → `true`).
   Config'e güvenmeden çalışma anında canlı/demo ayrımı yapılabilir — emir yolunda güvenlik kapısı
   olarak kullanılmalı.
8. **İliştirilmiş TP/SL sonradan iptal edilebiliyor** — ana emirden bağımsız algo order olarak yaşıyor,
   `spot_cancel_algo_order` / `spot_amend_algo_order` ile yönetiliyor, `algoId`'si
   `spot_get_algo_orders` ile bulunuyor. MCP'de tam karşılığı var, CLI'ya düşmeye gerek yok.
   `tpOrdKind: "limit"` sayesinde "hedef BB_mid, maker limit satış" tek çağrıda kuruluyor.
9. **Doğrulanmamış:** iliştirilmiş TP/SL'in `spot_get_algo_orders` listesinde gerçekten `algoId` ile
   göründüğü emir göndermeden test edilemedi. Faz 1'de demo profiliyle tek emirle doğrulanmalı;
   60 sn'lik uzlaştırma döngüsü buna bel bağlayacak.
10. CLI ile MCP'nin **iç payload'ı birebir aynı**, tek fark zarf (CLI doğrudan dizi döndürüyor).
    Yedek yolu yazmak ucuz: MCP'de iki kat soy, CLI'da hiç soyma.

### Faz 1'de eklenenler

11. **`market_get_candles` `limit` 300'de tavan.** limit=500 istendi, 300 geldi — sessizce kırpıyor.
    `after=<en eski ts>` ile sayfalama **temiz**: sayfa 2'nin en yenisi tam 1 bar (900000 ms) eski,
    örtüşme yok. 407 mumda tekrar eden ts = 0.
12. **`market_filter` `limit` 100'de tavan ve >100 SESSİZ DEĞİL, PATLIYOR:** kod 902
    "Bind Arguments Validation Failure". limit=200 ile denenip görüldü. 100 ve altı sorunsuz.
    `minVolUsd24h=10M` ile SPOT/USDT evreni 22 parite; üçümüz de içinde (ETH 1., BTC 2., SOL 4.).
13. **`market_get_indicator` ve `market_filter` fazladan kat taşıyor.** Genel `payload["data"]["data"]`
    yetmiyor: filter → `[0]["rows"]`, indicator → `[0]["data"][0]["timeframes"][bar]["indicators"][IND]`.
    `tools.py` genel soymayı `_call`'da yapıyor, bu iki ekstra katı ilgili metotta.
14. **`market_get_indicator` `returnList` 100 noktada tavan** (limit=300 istendi, 100 geldi).
15. **RSI çapraz kontrolü: bizimki DOĞRU.** Ham max fark 2,9 puan görünüyor ama bu bir *ısınma
    artefaktı*: OKX Wilder'ı kendi 100 mumluk penceresinde tohumluyor, bizde 407 mum var.
    Fark serinin başında büyük, sonunda yok — BTC'de ilk 10 nokta ort 1,60 → **son 10 nokta 0,004**.
    Cutler (SMA) varyantı OKX'ten 23,3 puan sapıyor, yani OKX kesin Wilder. Ek çalışma yapılmadı.
16. **pandas 3.0 `.to_numpy()` SALT OKUNUR dizi döndürüyor.** `delta[0] = 0` → `ValueError:
    assignment destination is read-only`. `copy=True` şart. pandas 2.x'ten geçerken bu ısırır.
17. **Markdown tablo başlığında `|Δ|` yazma** — boru işareti sütunu bölüyor, tablo dağılıyor.

## Ertelenen öneriler
- ~~Faz 2'de demo profiliyle tek emir atıp iliştirilmiş TP/SL'in `algoId`'sini doğrula (madde 9).~~
  **KAPANDI** — Faz 2'de doğrulandı, yukarıdaki (b) testine bak.
- ~~`market_get_indicator` ile RSI karşılaştırması~~ — Faz 1'de yapıldı (madde 15).
- `logs/` klasörü boş; git boş klasör tutmuyor. İlk log dosyası yazılınca sorun kalmaz.
- ~~`config.yaml` henüz yok.~~ **Faz 2'de oluşturuldu.**
- ~~Spread 2 bps varsayıldı, ölçülmedi.~~ **Faz 2'de ölçüldü:** gerçek medyan 0,013 bps (BTC),
  varsayımın 150× altında. Mikro katman 20 sn'de bir örnekliyor, kapı medyanı kullanıyor
  (yukarıdaki madde 22).
- Tarama komisyonu PnL'e uygulamıyor (kazanç/kayıp saf fiyat hareketi); maliyet kapısı ayrı
  sütunda. Faz 2'de gerçek PnL hesabı ücreti düşmeli.
- 3 günlük pencere parite başına 2–7 kurulum veriyor — **örneklem küçük**. Tablo kalibrasyondur,
  optimizasyon değil; eşiği kazanma yüzdesine göre seçmek aşırı uydurma riski taşır.

## Canlı ajan durumu
- **Çalışmıyor.** Profil: — . Son başlatma: — . Canlıya **hiç emir gönderilmedi**
  (Faz 2 canlı testleri `--dry-run` ile geçti; `orders.jsonl`'de canlı satır yok).
- Canlı hesap (`hackathon`) bakiyesi: 30 USDT (totalEq 29.9925).
- Demo hesap (`hackathondemo`): 1 emir atıldı ve kapatıldı. SOL bakiyesi toz seviyesinde
  (1.11e-7), pending algo emri 0 — açık pozisyon kalmadı.
