# Yarışma Kuralları — Güncel Özet

## Değerlendirme kriterleri (12 Eylül sabahı açıklanan resmî tablo)

| Kriter | Ağırlık |
|---|---:|
| Functional Utility & Value | 30% |
| User Experience & Interaction | 30% |
| ATK MCP Integration Depth | 20% |
| System Reliability & Safety | 10% |
| Innovation & Uniqueness | 10% |

Etkinlik sayfasındaki eski tablo (hesap performansı %35, mimari %25, risk %20, özgünlük %10,
sunum %10) **geçersizdir.** Detaylı puanlama rubriği yayımlanmadı.

## Geçerli kalan kurallar

- Bireysel katılım; takım yok.
- İşlemler yalnızca yarışma sub-account'ında, OKX TR işlem kredisiyle (**30 USDT**), spot piyasada.
- Değerlendirmeye esas işlemler ajan tarafından **otonom** alınmalı; elle girilen emirler sayılmaz ve
  diskalifiye sebebi olabilir. Dashboard'da al/sat düğmesi yok; sadece operatör güvenlik kontrolleri,
  hepsi loglanır.
- API anahtarı sub-account'a ait; açık kaynak ATK (`github.com/okx/agent-trade-kit`) ile yapılandırılır.
- Önceden bitmiş sistemi "sıfırdan" diye sunmak yasak; açık kaynak kütüphaneler serbest.
- Fikri mülkiyet katılımcıda.

## Gün akışı

| Saat | Ne |
|---|---|
| 12:00 | Check-in #1 (3 dk rapor + 2 dk soru) |
| 13:30 | Mentor Round #2 |
| 15:00 | Check-in #2 |
| 16:00 | Mentor Round #3 |
| 17:30 | Check-in #3 — kod donar |
| 19:00–19:30 | Teslim: README, kısa video/GIF, hesap performans dökümü, çalışır ajan linki, sunum dosyaları |
| 19:30 | Dosya kilidi; hesap defterleri kapanır |
| 20:00 | Sunumlar (3 dk) |
| 22:15 | Ödül töreni |

## Belirsiz kalanlar (varsayma, sor)

- Alt kriterlerin rubriği · 19:30'da gerçekleşmemiş kârın sayılıp sayılmadığı · izinli pariteler ·
  minimum emir büyüklüğü (Faz 0'da instruments ile doğrula) · API rate limitleri (2 sn'de 20 istek varsayımı).
