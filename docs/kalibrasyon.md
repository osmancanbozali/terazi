# Kalibrasyon — RSI eşik taraması

Üretildi: `calibrate.py`, 2026-09-12 08:42 UTC · profil `hackathon` · `capabilities.demo` = **False** · emir gönderilmedi.

Veri: 3 gün × 15m, parite başına 288 kapanmış mum (+120 ısınma). Kapanmamış mum (`confirm=0`) atıldı.

- BTC-USDT: 407 kapanmış mum (2026-09-08 02:45 → 2026-09-12 08:15 UTC), tekrar eden ts=0, boşluk=0
- ETH-USDT: 407 kapanmış mum (2026-09-08 02:45 → 2026-09-12 08:15 UTC), tekrar eden ts=0, boşluk=0
- SOL-USDT: 407 kapanmış mum (2026-09-08 02:45 → 2026-09-12 08:15 UTC), tekrar eden ts=0, boşluk=0
- XRP-USDT: 407 kapanmış mum (2026-09-08 02:45 → 2026-09-12 08:15 UTC), tekrar eden ts=0, boşluk=0
- DOGE-USDT: 407 kapanmış mum (2026-09-08 02:45 → 2026-09-12 08:15 UTC), tekrar eden ts=0, boşluk=0

Ücret ölçüldü: `account_get_trade_fee` maker `-0.0008` → **abs = 8.0 bps**. Maliyet = 2×8.0 + 2 spread = **18.0 bps**. Kapı = 2.5 × maliyet = **45.0 bps**.

## Evren doğrulaması (`market_filter`)

| parite | hacim sırası | volUsd24h |
|---|---|---|
| BTC-USDT | 2 | 570,260,582 |
| ETH-USDT | 1 | 640,993,269 |
| SOL-USDT | 4 | 118,894,533 |
| XRP-USDT | 6 | 57,040,808 |
| DOGE-USDT | 7 | 44,460,936 |

## RSI çapraz kontrolü — bizim Wilder(14) vs `market_get_indicator`

| parite | örtüşen nokta | max Δ (tümü) | ort Δ (tümü) | max Δ (son 50) | ort Δ (son 50) |
|---|---|---|---|---|---|
| BTC-USDT | 99 | 3.634 | 0.247 | 0.0147 | 0.0049 |
| ETH-USDT | 99 | 3.843 | 0.303 | 0.0175 | 0.0057 |
| SOL-USDT | 99 | 3.561 | 0.274 | 0.0416 | 0.0089 |
| XRP-USDT | 99 | 3.552 | 0.308 | 0.0164 | 0.0082 |
| DOGE-USDT | 99 | 3.894 | 0.317 | 0.0140 | 0.0070 |

**Sonuç: RSI'ımız doğru.** Fark bir *ısınma artefaktıdır*, formül farkı değil.
`market_get_indicator` `returnList` 100 noktada tavan yapıyor ve OKX Wilder ortalamasını
kendi 100 mumluk penceresi içinde tohumluyor; bizde 407 mumluk geçmiş var, o yüzden bizim
seri her yerde yakınsamış durumda. Fark bu yüzden serinin başında büyük, sonunda yok:
BTC'de ilk 10 noktada ort 1,60 · orta 10 noktada 0,008 · **son 10 noktada 0,004**.
Kontrol amaçlı Cutler (SMA tabanlı) RSI da denendi ve OKX'ten max **23,3** puan saptı —
yani OKX kesinlikle Wilder kullanıyor, bizim seçimimiz doğru. Sinyal penceresi yalnızca
yakınsamış değerleri kullandığı için tarama etkilenmiyor; ek çalışma yapılmadı.

## Sonuç tablosu

| parite | eşik | kurulum | tetik | stop-RED | ulaştı(ham) | kazanç | kayıp | z.aşımı | z.aşımı çıkış bps | kazanma % | ort hedef bps | ort stop bps | maliyet ✓ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC-USDT | 28 | 2 | 1 | 0 | 0 | 0 | 0 | 1 | 10.4 | 0.0 | 49.5 | 50.0 | 1 |
| BTC-USDT | 32 | 4 | 3 | 0 | 0 | 0 | 1 | 2 | 8.4 | 0.0 | 48.1 | 61.2 | 2 |
| BTC-USDT | 36 | 6 | 4 | 0 | 1 | 1 | 1 | 2 | 14.2 | 25.0 | 43.3 | 51.2 | 1 |
| ETH-USDT | 28 | 2 | 1 | 0 | 0 | 0 | 1 | 0 | — | 0.0 | 65.3 | 67.2 | 1 |
| ETH-USDT | 32 | 4 | 2 | 0 | 1 | 1 | 1 | 0 | — | 50.0 | 64.7 | 58.6 | 2 |
| ETH-USDT | 36 | 6 | 4 | 0 | 1 | 1 | 1 | 2 | 2.0 | 25.0 | 58.2 | 67.2 | 3 |
| SOL-USDT | 28 | 3 | 3 | 2 | 0 | 0 | 0 | 1 | -18.7 | 0.0 | 111.1 | 82.6 | 3 |
| SOL-USDT | 32 | 7 | 5 | 1 | 1 | 1 | 0 | 3 | 1.8 | 25.0 | 82.3 | 73.7 | 5 |
| SOL-USDT | 36 | 7 | 5 | 1 | 1 | 1 | 0 | 3 | 1.8 | 25.0 | 82.3 | 64.2 | 5 |
| XRP-USDT | 28 | 4 | 3 | 0 | 1 | 0 | 2 | 1 | 20.9 | 0.0 | 103.9 | 64.9 | 3 |
| XRP-USDT | 32 | 5 | 2 | 0 | 0 | 0 | 0 | 2 | -11.2 | 0.0 | 87.8 | 88.8 | 2 |
| XRP-USDT | 36 | 10 | 6 | 0 | 1 | 0 | 3 | 3 | -1.8 | 0.0 | 83.3 | 73.4 | 5 |
| DOGE-USDT | 28 | 4 | 2 | 0 | 0 | 0 | 1 | 1 | -13.5 | 0.0 | 171.3 | 113.8 | 2 |
| DOGE-USDT | 32 | 5 | 3 | 0 | 0 | 0 | 2 | 1 | 4.8 | 0.0 | 142.2 | 69.7 | 3 |
| DOGE-USDT | 36 | 8 | 6 | 0 | 1 | 1 | 3 | 2 | -9.5 | 16.7 | 109.5 | 65.9 | 6 |

### Sütunlar
- **kurulum**: `close < BB_lower` ve `RSI < eşik`; örtüşmesiz sayım (aşağıya bak).
- **tetik**: kurulumdan sonraki 2 mum içinde `close > BB_lower` ve `close > kurulum.low`.
- **stop-RED**: tetikledi ama stop mesafesi %1,2'yi aştığı için reddedildi (canlı kural).
- **ulaştı(ham)**: stop yok sayılırsa 8 mumda `BB_mid`'e değenler — ilk spec'teki metrik.
- **kazanç / kayıp / z.aşımı**: 8 mumluk ufuk SIRAYLA gezilir; `low ≤ stop` önce gelirse kayıp,
  `high ≥ hedef` önce gelirse kazanç, aynı mumda ikisi de olursa **muhafazakâr = kayıp**,
  hiçbiri olmazsa zaman aşımı. `ulaştı(ham)` ile fark, stop'un önce yendiği işlemlerdir.
- **z.aşımı çıkış bps**: zaman aşımına düşen tetiklerde **j+8 kapanışında** çıkılsaydı ortalama
  PnL bps. Bugün zaman aşımı = "sonuçsuz"; bu sütun o kovanın gerçekte artı mı eksi mi olduğunu
  söyler. Komisyon uygulanmadı (18 bps tur maliyeti bu sayıdan düşülmeli).
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

**Eşik seçimi kullanıcıya aittir.** Bu dosya öneri içermez; seçilen değer `config.yaml`'a girilir.
