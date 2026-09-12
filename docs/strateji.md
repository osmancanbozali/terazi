# TERAZİ — Trading Stratejisi

**Agentic Trading Hackathon · 12 Eylül 2026 · OKX TR Spot**
**Rejim: Ortalamaya dönüş (mean reversion) · Pariteler: BTC, ETH, SOL, XRP, DOGE /USDT · Sermaye: 30 USDT**

> Bu doküman yalnızca trading stratejisini anlatır. Ürün, mimari, dashboard, MCP entegrasyonu ve
> puanlama haritası `docs/urun-mimari.md`'dedir; yol haritası da orada. Bütün sayısal eşikler
> `config.yaml`'da yaşar; buradaki değerler başlangıç değerleridir, kalibrasyon sonrası güncellenebilir.

---

## 1. Tek cümlelik tez

Cumartesi kripto piyasası genellikle yatay bant içinde salınır. Terazi, BTC'nin son 48 saatlik aralığını
kendisi ölçer; aralık korunduğu sürece BTC/ETH/SOL'da aşırı satılmış noktalarda, satış baskısının
kırıldığını hem fiyat hem emir defteriyle teyit ederek alır, bandın ortasında satar. Aralık kırılırsa
nakde çekilir. Kurallar gaz, LLM fren, döngü direksiyon.

---

## 2. Piyasa okuması ve neden bu strateji

| Gözlem | Değer (12 Eylül sabahı) |
|---|---|
| BTC fiyatı | ~77.300 |
| Son 2 günlük taban | 76.000 – 76.500 (birkaç kez savunuldu) |
| Son 2 günlük tavan | 79.000 – 79.500 (birkaç kez reddedildi) |
| Bant genişliği | ~%4,5 |
| Takvim | Cumartesi; makro veri yok, Fed kararı gelecek hafta |

**Çıkarım:** Belirgin trend yok, bant yapısı iki gündür korunuyor, hafta sonu likiditesi düşük.
Trend takip stratejilerinin en kötü, ortalamaya dönüşün en iyi çalıştığı ortam.

**Elenen alternatifler:**
- *Kırılım / momentum:* cumartesi yalancı kırılımların günüdür; çok stop yenir.
- *OKX spot grid botu:* yatay piyasada çalışır ama çok işlem = komisyon; kırılımda envanterle kalınır;
  "ajan" değil "bot ayarı"dır.
- *Saf LLM kararı:* aynı veriye farklı cevap verir, ölçülemez, savunulamaz; herkes aynı şeyi yapacak.

---

## 3. Sıfırdan kavramlar (sunumda da lazım)

**Ortalamaya dönüş:** Yatay piyasada fiyat "normal" seviyesinden fazla saptığında geri gelme
eğilimindedir. Biz aşağı sapmaları alıyoruz (spot piyasada sadece alım yapılabilir).

**Bollinger Bantları (20, 2):** Son 20 mumun ortalaması (orta bant) ve onun 2 standart sapma altı/üstü.
Fiyat alt bandın altına kapanırsa "normalden istatistiksel olarak uzak" demektir.

**RSI (14):** Son 14 mumda alıcı ve satıcı gücünün oranı, 0–100 arası. 30'un altı "satıcılar aşırı
baskın" demektir.

**ATR (14):** Son 14 mumun ortalama hareket genişliği. Stop mesafesini fiyatın o günkü "doğal
titreşimine" göre ölçeklemek için kullanılır.

**Emir defteri dengesizliği (OBI):** Orta fiyatın ±10 baz puan bandında bekleyen alış miktarı ile satış
miktarının farkı, −1 ile +1 arası. Pozitifse alıcılar daha kalabalık.

**Spread:** En iyi alış ile en iyi satış fiyatı arasındaki fark. Anormal genişlerse likidite çekilmiş
demektir; o anda işlem yapılmaz.

**Komisyon gerçeği:** OKX spot ~%0,08 maker / %0,10 taker (gerçek oran sabah `account fees` ile
doğrulanır). Bir al-sat turu ≈ %0,16–0,20. 30 USDT bakiyede 9 USDT'lik pozisyonda bu 1–2 cent; mutlak
olarak önemsiz, **yüzde olarak stratejinin en büyük düşmanı.** Beklenen kârı komisyonun 2,5 katından
küçük hiçbir işlem yapılmaz.

---

## 4. Strateji katmanları

Karar sırayla beş kapıdan geçer. Herhangi bir kapı kapalıysa işlem yoktur ve gerekçe loglanır.

### 4.1 Rejim kapısı — "Bugün hangi oyunu oynuyoruz?"

BTC'den türetilir, 30 dakikada bir yenilenir, üç pariteye de uygulanır.

- `RANGE_LOW` = son 48 adet 1H mumun en düşük low'u
- `RANGE_HIGH` = son 48 adet 1H mumun en yüksek high'ı
- Elle sayı girilmez; ajan aralığı kendisi ölçer ve loglar.

| Koşul | Rejim | Anlamı |
|---|---|---|
| BTC 15m kapanış < RANGE_LOW × 0,998 | **CASH** | Taban kırıldı, yatay gün bitti, alım yok |
| BTC fiyat > RANGE_HIGH | **CASH** | Yukarı kırılım; kovalamıyoruz |
| Son 15m mumun aralığı > 3 × ATR | **30 dk giriş yasağı** | Şok hareket (haber, tasfiye) |
| Aksi hâlde | **MEAN_REVERSION** | Oyun açık |

CASH'e geçmek başarısızlık değil, tasarlanmış davranıştır.

### 4.2 Sinyal — "Aşırı satılmış mı, geri dönüyor mu?"

Her parite için ayrı, kapanmış 15 dakikalık mumlarla. Kapanmamış son mum asla kullanılmaz.

**Kurulum:** `close < BB_lower(20,2)` VE `RSI14 < 32`

**Tetik (kurulumdan sonraki 1–2 mum içinde):** `close > BB_lower` VE `close > kurulum_mumu.low`

İki mum içinde tetik gelmezse kurulum iptal. Tetik beklemenin nedeni: aşırı satılmış fiyat saatlerce
daha düşebilir; bandın içine geri kapanış, satıcıların gücünün kırıldığının ilk objektif kanıtıdır.

### 4.3 Mikro yapı teyidi — "Emir defteri de aynı şeyi söylüyor mu?"

Tetik anında tek örnek: `OBI(±10bps) ≥ 0` VE `spread ≤ 2 × son 30 dk medyan spread`.
Bu katman ayrıca gün boyu her 20 saniyede örnek alıp `micro.jsonl`'e yazar; dashboard'da sparkline
olarak görünür.

### 4.4 Maliyet kapısı — "Bu işlem komisyonu karşılar mı?"

```
hedef_bps   = (BB_mid − giriş) / giriş × 10.000
maliyet_bps = 2 × fee_bps + spread_bps
koşul:  hedef_bps ≥ 2,5 × maliyet_bps
```
Bant daraldığında bu kapı çoğu adayı eler. İstenen davranıştır.

### 4.5 LLM yargıç — "Bu düşüş sıradan mı, haber mi?"

Yalnızca aday oluştuğunda çağrılır. Girdi: aday özeti, son 10 mum özeti, ATK `news` çıktısı,
funding/OI. Çıktı yapılandırılmış: `decision: APPROVE|REDUCE|VETO`, `size_multiplier: 0,3–1,0`,
`reason ≤ 300`, `news_risk: none|low|high`.

**LLM frene basabilir, gaza basamaz.** Emin değilse VETO. Zaman aşımında (20 sn) aday geçirilir ve
loglanır (fail-open).

### 4.6 Risk kapısı — aşılamaz katman

| # | Kontrol | Değer | Neden |
|---|---|---|---|
| 1 | Kill switch | Günlük PnL ≤ −%1,5 → gün bitti | ~6–7 kayıp |
| 2 | Cooldown | 2 ardışık kayıp → 45 dk giriş yok | Kötü koşulda ısrar etme |
| 3 | Günlük işlem tavanı | 8 | Komisyon sınırı |
| 4 | Eşzamanlı pozisyon | En fazla 2 | Üç parite korelasyonlu |
| 5 | Parite başına | Aynı paritede ikinci pozisyon yok | |
| 6 | Boyut | equity × %30 (30 USDT'de ≈ 9 USDT) | minSz üstünde; Faz 0'da doğrulanır |
| 7 | Stop mesafesi | aşağıda | R:R kontrolü |
| 8 | Enstrüman kısıtı | lotSz'a aşağı yuvarla; minSz altındaysa reddet | |
| 9 | Bakiye | notional ≤ kullanılabilir | |
| 10 | Saat | 18:30 sonrası yeni giriş yok | Gün sonu payı |

**Stop yapısal:** `stop = kurulum_mumu.low − 0,2×ATR`; girişten en az %0,5, en fazla %1,2 uzakta;
%1,2'yi aşıyorsa aday reddedilir.

**Hedef:** BB_mid, limit satış (maker).

**Gün sonu:** 19:10'da tüm açık pozisyonlar kapatılır.

---

## 5. İcra ilkeleri

- Limit alış, fiyat = en iyi alış + 1 tick; 90 sn'de dolmazsa iptal.
- TP ve SL emre **iliştirilir**; borsa tarafında bekler.
- Tetik fiyatı ile emir fiyatı arasında 1–2 tick pay.
- **Emir komutlarında otomatik yeniden deneme yoktur.** Tek deneme; hata loglanır.
- Her emir denemesi, başarısızlar dahil, `orders.jsonl`'e yazılır.

---

## 6. Beklenen profil

| Ölçü | Beklenti |
|---|---|
| Sinyal sayısı (3 parite, ~7 saat canlı) | 2 – 6 |
| Gerçekleşen işlem | 1 – 4 |
| İşlem başına sonuç | ± %0,15 – 0,25 equity |
| Gün sonu getiri | −%0,5 ile +%0,8 arası |
| Maksimum düşüş | < %0,5 |

Yeni puanlamada hesap performansının doğrudan ağırlığı yok; "Functional Utility & Value" içinde
dolaylı sayılır. Bu yüzden hedef "çok işlem" değil, **az sayıda doğru işlem + çok sayıda gerekçeli
bekleme**dir. Her karar açıklanabilir olduğu sürece sıfır işlem bile savunulabilir.

---

## 7. Upside / downside

**Upside:** piyasa koşuluyla uyumlu; az işlem = düşük komisyon ve MDD; her "bekle" gerekçeli;
aralığı ajanın kendisi ölçmesi, mikro teyit, fren-only LLM özgün; üç parite = 3× fırsat.

| Risk | Olasılık | Karşılık |
|---|---|---|
| Sıfır sinyal | Orta | 3 parite; 12:00'de veriye göre RSI 32→36 (config'den, loglanır); "N gerekçeli bekleme" hikâyesi |
| Trend günü | Düşük–orta | Rejim kapısı + cooldown + kill switch |
| R:R ≈ 1:1 | Yapısal | Tetik kazanma oranını yükseltir; README'de açıkça yazılır |
| İki pozisyon aynı anda stoplanır | Orta | Bilinçli kabul; 2 tavanı bu yüzden |
| LLM her şeye veto verir | Orta | Fail-open; verdictlar loglanır ve dashboard'da görünür |
| Prototip geç canlıya çıkar | En yüksek | 12:30 canlı hedefi |

---

## 8. Senaryo kitabı

**S1 — Bant korunuyor:** sistem tasarlandığı gibi çalışır.
**S2 — Taban kırılıyor:** CASH; loglar "taban kırıldı" der. Eşik gevşetme tuzağına düşme.
**S3 — Tavan kırılıyor:** CASH; kovalamıyoruz.
**S4 — Ölü piyasa:** 12:00'de loglara bak; hangi kapı reddediyorsa sadece onu ayarla, config'den, loglayarak.
**S5 — Haber şoku:** vol kesici 30 dk yasak + LLM veto. Müdahale etme; bu anın logu sunumun en güçlü karesi.
**S6 — Teknik arıza:**

| Arıza | Davranış |
|---|---|
| MCP çağrısı hata | 2 deneme, sonra aynı işlem CLI yedeğinden, logla |
| LLM zaman aşımı | Adayı geçir, logla (fail-open) |
| İnternet koptu | Borsadaki TP/SL korur; ajan dönünce state.json'dan devam |
| Ajan çöktü | Yeniden başlat; state.json + borsadaki açık emirlerle uzlaş |

---

## 9. Bilinçli sınırlamalar (README'ye yazılacak)

- Sadece alım yönü (spot); düşen piyasada nakit dışında araç yok.
- Tek gün, tek rejim için tasarlandı; trend günlerinde CASH'te oturur.
- Eşikler 3 günlük veriyle **kalibre edildi, optimize edilmedi**.
- R:R yaklaşık 1:1; kâr kazanma oranına bağlı.
- Üç parite yüksek korelasyonlu.
- Yaklaşık 7 saatlik canlı pencere; sonuçlar istatistiksel anlam değil, davranış kanıtı taşır.

---

## 10. Başlangıç parametreleri (config.yaml için)

Faz 2'de `config.yaml` oluşturuldu; aşağıdaki tablo **o dosyadaki gerçek değerlerdir**.
Çelişki olursa `config.yaml` kazanır (kodda sabit sayı yok).

| Parametre | Değer | Not |
|---|---|---|
| pariteler | BTC-USDT, ETH-USDT, SOL-USDT, **XRP-USDT, DOGE-USDT** | Faz 2'de 5'e çıkarıldı; hepsi ≥10M USD hacim filtresinde, 9 USDT hepsinde minSz'ı karşılıyor (en dar XRP 6,6×). Açılışta doğrulanır, geçmeyen evrenden düşer ve loglanır |
| rejim göstergesi | BTC-USDT | beş pariteye de uygulanır; BTC'nin kendi sinyali de açık |
| sinyal zaman dilimi | 15m | kapanıştan 15 sn sonra işlenir |
| rejim zaman dilimi | 1H, son 48 mum | 30 dk'da bir yenilenir |
| BB | 20, 2σ (popülasyon, ddof=0) | |
| RSI kurulum eşiği | **36** | kalibrasyon sonrası seçildi — **sinyal sıklığına göre**, kazanma yüzdesine göre değil (örneklem küçük, aşırı uydurma riski) |
| tetik penceresi | 2 mum | |
| zaman stopu | **12 kapanmış mum** | kalibrasyon: j+8 çıkışı ham +1,1 bps, komisyonla −16,9 bps → erken çıkış kâr kaynağı değil, ufku aç |
| OBI bant / eşik | ±10 bps / ≥ 0 | |
| spread eşiği | 2 × 30 dk medyan | medyan yoksa **fallback 2 bps** ve loglanır |
| maliyet çarpanı | 2,5 | ölçülen maker 8,0 bps → maliyet 18,0 bps → kapı 45,0 bps |
| vol kesici | son mum aralığı > 3×ATR → 30 dk | |
| pozisyon boyutu | equity × %30 | |
| eşzamanlı pozisyon | 2 | parite başına en fazla 1 |
| stop | setup_low − 0,2×ATR; **bant 50–120 bps** | 50'nin altı 50'ye çekilir, 120'nin üstü **reddedilir** |
| hedef | BB_mid, maker limit satış (`tpOrdKind: limit`) | |
| kill switch | −%1,5 günlük | |
| cooldown | 2 ardışık kayıp → 45 dk | |
| günlük işlem tavanı | 8 | |
| limit emir ömrü | 90 sn | dolmazsa iptal, aday düşer |
| uzlaştırma periyodu | 60 sn | borsa kaynak gerçek |
| son giriş / kapanış saati | 18:30 / 19:10 (Europe/Istanbul) | |
| profiller | live=`hackathon` (expected_demo=false) · demo=`hackathondemo` (expected_demo=true) | emir öncesi `capabilities.demo` bununla karşılaştırılır; eşleşmezse emir gitmez |
| LLM zaman aşımı | 20 sn, fail-open | Faz 2'de `enabled: false` |
| LLM modeli | birincil claude-sonnet-5, yedek claude-haiku-4-5 (doğrudan Anthropic API) | |

*Bu bir strateji planıdır, yatırım tavsiyesi değildir.*
