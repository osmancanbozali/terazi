# Kalibrasyon — RSI eşik taraması

Üretildi: `calibrate.py`, 2026-09-12 14:05 UTC · profil `hackathon` · `capabilities.demo` = **False** · emir gönderilmedi.

Veri: 2 gün × 5m, parite başına 576 kapanmış mum (+120 ısınma). Kapanmamış mum (`confirm=0`) atıldı.

- ETH-USDT: 695 kapanmış mum (2026-09-10 04:05 → 2026-09-12 13:55 UTC), tekrar eden ts=0, boşluk=0
- BTC-USDT: 695 kapanmış mum (2026-09-10 04:05 → 2026-09-12 13:55 UTC), tekrar eden ts=0, boşluk=0
- SOL-USDT: 695 kapanmış mum (2026-09-10 04:05 → 2026-09-12 13:55 UTC), tekrar eden ts=0, boşluk=0
- ZEC-USDT: 695 kapanmış mum (2026-09-10 04:05 → 2026-09-12 13:55 UTC), tekrar eden ts=0, boşluk=0
- XRP-USDT: 695 kapanmış mum (2026-09-10 04:05 → 2026-09-12 13:55 UTC), tekrar eden ts=0, boşluk=0
- HYPE-USDT: 695 kapanmış mum (2026-09-10 04:10 → 2026-09-12 14:00 UTC), tekrar eden ts=0, boşluk=0
- DOGE-USDT: 695 kapanmış mum (2026-09-10 04:10 → 2026-09-12 14:00 UTC), tekrar eden ts=0, boşluk=0
- UNI-USDT: 695 kapanmış mum (2026-09-10 04:10 → 2026-09-12 14:00 UTC), tekrar eden ts=0, boşluk=0
- SUI-USDT: 695 kapanmış mum (2026-09-10 04:10 → 2026-09-12 14:00 UTC), tekrar eden ts=0, boşluk=0
- BNB-USDT: 695 kapanmış mum (2026-09-10 04:10 → 2026-09-12 14:00 UTC), tekrar eden ts=0, boşluk=0
- NEAR-USDT: 695 kapanmış mum (2026-09-10 04:10 → 2026-09-12 14:00 UTC), tekrar eden ts=0, boşluk=0
- RAY-USDT: 695 kapanmış mum (2026-09-10 04:10 → 2026-09-12 14:00 UTC), tekrar eden ts=0, boşluk=0

Ücret ölçüldü: `account_get_trade_fee` maker `-0.0008` → **abs = 8.0 bps**. Maliyet = 2×8.0 + 2 spread = **18.0 bps**. Kapı = 2.5 × maliyet = **45.0 bps**.

## Evren doğrulaması (`market_filter`)

| parite | hacim sırası | volUsd24h |
|---|---|---|
| ETH-USDT | 1 | 383,253,866 |
| BTC-USDT | 2 | 318,529,909 |
| SOL-USDT | 4 | 75,490,662 |
| ZEC-USDT | 5 | 66,522,687 |
| XRP-USDT | 6 | 36,231,687 |
| HYPE-USDT | 7 | 30,543,677 |
| DOGE-USDT | 8 | 29,015,830 |
| UNI-USDT | 9 | 19,313,137 |
| SUI-USDT | 10 | 18,454,249 |
| BNB-USDT | 11 | 18,142,417 |
| NEAR-USDT | 12 | 12,741,664 |
| RAY-USDT | 14 | 10,062,016 |

## RSI çapraz kontrolü — bizim Wilder(14) vs `market_get_indicator`

| parite | örtüşen nokta | max Δ (tümü) | ort Δ (tümü) | max Δ (son 50) | ort Δ (son 50) |
|---|---|---|---|---|---|
| ETH-USDT | 98 | 2.235 | 0.316 | 0.0422 | 0.0097 |
| BTC-USDT | 98 | 2.127 | 0.251 | 0.0728 | 0.0132 |
| SOL-USDT | 98 | 2.239 | 0.420 | 0.1290 | 0.0332 |
| ZEC-USDT | 98 | 1.665 | 0.408 | 0.1396 | 0.0318 |
| XRP-USDT | 98 | 1.869 | 0.180 | 0.0409 | 0.0104 |
| HYPE-USDT | 99 | 1.792 | 0.327 | 0.1001 | 0.0285 |
| DOGE-USDT | 99 | 1.044 | 0.172 | 0.0765 | 0.0115 |
| UNI-USDT | 99 | 1.436 | 0.157 | 0.0414 | 0.0133 |
| SUI-USDT | 99 | 1.461 | 0.249 | 0.0385 | 0.0101 |
| BNB-USDT | 99 | 3.743 | 0.536 | 0.0463 | 0.0154 |
| NEAR-USDT | 99 | 2.714 | 0.213 | 0.0386 | 0.0111 |
| RAY-USDT | 99 | 2.811 | 0.359 | 0.1053 | 0.0299 |

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
| ETH-USDT | 36 | 9 | 5 | 0 | 2 | 2 | 3 | 0 | — | 40.0 | 28.2 | 51.5 | 1 |
| BTC-USDT | 36 | 7 | 4 | 0 | 1 | 1 | 1 | 2 | 2.0 | 25.0 | 46.5 | 50.6 | 1 |
| SOL-USDT | 36 | 8 | 5 | 1 | 1 | 1 | 1 | 2 | 6.5 | 25.0 | 54.2 | 56.2 | 2 |
| ZEC-USDT | 36 | 13 | 6 | 0 | 4 | 3 | 3 | 0 | — | 50.0 | 131.8 | 52.9 | 6 |
| XRP-USDT | 36 | 9 | 6 | 0 | 1 | 1 | 4 | 1 | 69.7 | 16.7 | 49.9 | 50.0 | 3 |
| HYPE-USDT | 36 | 12 | 8 | 0 | 4 | 3 | 5 | 0 | — | 37.5 | 87.9 | 52.7 | 7 |
| DOGE-USDT | 36 | 10 | 9 | 1 | 4 | 3 | 4 | 1 | 40.9 | 37.5 | 46.3 | 55.7 | 4 |
| UNI-USDT | 36 | 8 | 5 | 0 | 1 | 1 | 4 | 0 | — | 20.0 | 101.7 | 65.2 | 5 |
| SUI-USDT | 36 | 12 | 10 | 1 | 2 | 0 | 8 | 1 | -5.5 | 0.0 | 56.9 | 56.6 | 5 |
| BNB-USDT | 36 | 8 | 5 | 0 | 5 | 5 | 0 | 0 | — | 100.0 | 27.3 | 50.0 | 1 |
| NEAR-USDT | 36 | 15 | 13 | 2 | 5 | 4 | 7 | 0 | — | 36.4 | 131.9 | 63.7 | 12 |
| RAY-USDT | 36 | 8 | 8 | 3 | 4 | 2 | 2 | 0 | — | 50.0 | 229.1 | 93.5 | 8 |
| **TOPLAM (12 parite)** | 36 | 119 | 84 | 8 | 34 | 26 | 42 | 7 | 17.4 | 34.7 | 90.1 | 58.2 | 55 |

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
