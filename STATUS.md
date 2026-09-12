# STATUS

## Şu anki faz
**Faz 0 — Ortam keşfi: TAMAM** (12 Eylül 2026). Sıradaki: Faz 1 — `tools.py` (MCP client + CLI yedek).

## Bitenler
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

## Ertelenen öneriler
- Faz 1'de demo profiliyle tek emir atıp iliştirilmiş TP/SL'in `algoId`'sini doğrula (madde 9).
- `market_get_indicator` ile kendi RSI'ımızı karşılaştırma (urun-mimari.md 3.2'de planlı) Faz 0'da
  yapılmadı — indikatör hesabı yazıldığında yapılmalı.
- `logs/` klasörü boş; git boş klasör tutmuyor. İlk log dosyası yazılınca sorun kalmaz.

## Canlı ajan durumu
- Çalışmıyor. Profil: — . Son başlatma: — .
- Canlı hesap (`hackathon`) bakiyesi: 30 USDT (totalEq 29.9922). Emir gönderilmedi.
