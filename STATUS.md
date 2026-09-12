# STATUS

## Şu anki faz
**Faz 1 — `calibrate.py`: TAMAM** (12 Eylül 2026, 08:30 UTC). Tablo `docs/kalibrasyon.md`'de,
**eşik seçimi kullanıcıda bekliyor.** Sıradaki: Faz 2 — `terazi.py` MVP + seçilen eşikle `config.yaml`.

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
- Faz 2'de demo profiliyle tek emir atıp iliştirilmiş TP/SL'in `algoId`'sini doğrula (madde 9).
  **Hâlâ açık** — Faz 1 emirsizdi.
- ~~`market_get_indicator` ile RSI karşılaştırması~~ — Faz 1'de yapıldı (madde 15).
- `logs/` klasörü boş; git boş klasör tutmuyor. İlk log dosyası yazılınca sorun kalmaz.
- **`config.yaml` henüz yok.** Kullanıcı eşiği seçince Faz 2'de oluşturulacak; `calibrate.py`'ın
  argparse varsayılanları (strateji.md §10'dan) ilk içeriği için hazır şablon.
- **Spread 2 bps varsayıldı, ölçülmedi.** Maliyet kapısı bu sayıya duyarlı. Faz 2'de mikro yapı
  katmanı 20 sn'de bir orderbook örneklerken gerçek medyan spread ölçülüp kapıya beslenmeli.
- Tarama komisyonu PnL'e uygulamıyor (kazanç/kayıp saf fiyat hareketi); maliyet kapısı ayrı
  sütunda. Faz 2'de gerçek PnL hesabı ücreti düşmeli.
- 3 günlük pencere parite başına 2–7 kurulum veriyor — **örneklem küçük**. Tablo kalibrasyondur,
  optimizasyon değil; eşiği kazanma yüzdesine göre seçmek aşırı uydurma riski taşır.

## Canlı ajan durumu
- Çalışmıyor. Profil: — . Son başlatma: — . (Faz 1 salt okunur geçti; emir gönderilmedi.)
- Canlı hesap (`hackathon`) bakiyesi: 30 USDT (totalEq 29.9922). Emir gönderilmedi.
