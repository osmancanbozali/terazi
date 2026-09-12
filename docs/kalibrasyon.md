# Kalibrasyon — RSI eşik taraması

Üretildi: `calibrate.py`, 2026-09-12 08:26 UTC · profil `hackathon` · `capabilities.demo` = **False** · emir gönderilmedi.

Veri: 3 gün × 15m, parite başına 288 kapanmış mum (+120 ısınma). Kapanmamış mum (`confirm=0`) atıldı.

- BTC-USDT: 407 kapanmış mum (2026-09-08 02:30 → 2026-09-12 08:00 UTC), tekrar eden ts=0, boşluk=0
- ETH-USDT: 407 kapanmış mum (2026-09-08 02:30 → 2026-09-12 08:00 UTC), tekrar eden ts=0, boşluk=0
- SOL-USDT: 407 kapanmış mum (2026-09-08 02:30 → 2026-09-12 08:00 UTC), tekrar eden ts=0, boşluk=0

Ücret ölçüldü: `account_get_trade_fee` maker `-0.0008` → **abs = 8.0 bps**. Maliyet = 2×8.0 + 2 spread = **18.0 bps**. Kapı = 2.5 × maliyet = **45.0 bps**.

## Evren doğrulaması (`market_filter`)

| parite | hacim sırası | volUsd24h |
|---|---|---|
| BTC-USDT | 2 | 572,126,551 |
| ETH-USDT | 1 | 638,311,850 |
| SOL-USDT | 4 | 119,043,668 |

## RSI çapraz kontrolü — bizim Wilder(14) vs `market_get_indicator`

| parite | örtüşen nokta | max Δ (tümü) | ort Δ (tümü) | max Δ (son 50) | ort Δ (son 50) |
|---|---|---|---|---|---|
| BTC-USDT | 99 | 2.905 | 0.232 | 0.0142 | 0.0043 |
| ETH-USDT | 99 | 2.593 | 0.232 | 0.0191 | 0.0091 |
| SOL-USDT | 99 | 2.729 | 0.205 | 0.0239 | 0.0061 |

**Sonuç: RSI'ımız doğru.** Fark bir *ısınma artefaktıdır*, formül farkı değil.
`market_get_indicator` `returnList` 100 noktada tavan yapıyor ve OKX Wilder ortalamasını
kendi 100 mumluk penceresi içinde tohumluyor; bizde 407 mumluk geçmiş var, o yüzden bizim
seri her yerde yakınsamış durumda. Fark bu yüzden serinin başında büyük, sonunda yok:
BTC'de ilk 10 noktada ort 1,60 · orta 10 noktada 0,008 · **son 10 noktada 0,004**.
Kontrol amaçlı Cutler (SMA tabanlı) RSI da denendi ve OKX'ten max **23,3** puan saptı —
yani OKX kesinlikle Wilder kullanıyor, bizim seçimimiz doğru. Sinyal penceresi yalnızca
yakınsamış değerleri kullandığı için tarama etkilenmiyor; ek çalışma yapılmadı.

## Sonuç tablosu

| parite | eşik | kurulum | tetik | stop-RED | ulaştı(ham) | kazanç | kayıp | z.aşımı | kazanma % | ort hedef bps | ort stop bps | maliyet ✓ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC-USDT | 28 | 2 | 1 | 0 | 0 | 0 | 0 | 1 | 0.0 | 49.5 | 50.0 | 1 |
| BTC-USDT | 32 | 4 | 3 | 0 | 0 | 0 | 1 | 2 | 0.0 | 48.1 | 61.2 | 2 |
| BTC-USDT | 36 | 6 | 4 | 0 | 1 | 1 | 1 | 2 | 25.0 | 43.3 | 51.2 | 1 |
| ETH-USDT | 28 | 2 | 1 | 0 | 0 | 0 | 1 | 0 | 0.0 | 65.3 | 67.2 | 1 |
| ETH-USDT | 32 | 4 | 2 | 0 | 1 | 1 | 1 | 0 | 50.0 | 64.7 | 58.6 | 2 |
| ETH-USDT | 36 | 6 | 4 | 0 | 1 | 1 | 1 | 2 | 25.0 | 58.2 | 67.2 | 3 |
| SOL-USDT | 28 | 3 | 3 | 2 | 0 | 0 | 0 | 1 | 0.0 | 111.1 | 82.6 | 3 |
| SOL-USDT | 32 | 7 | 5 | 1 | 1 | 1 | 0 | 3 | 25.0 | 82.3 | 73.7 | 5 |
| SOL-USDT | 36 | 7 | 5 | 1 | 1 | 1 | 0 | 3 | 25.0 | 82.3 | 64.2 | 5 |

### Sütunlar
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

**Eşik seçimi kullanıcıya aittir.** Bu dosya öneri içermez; seçilen değer `config.yaml`'a girilir.
