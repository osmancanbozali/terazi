# Terazi — Geliştirme Kuralları

## Önce oku
- docs/urun-mimari.md: ürün, puanlama, mimari, dashboard, yol haritası — KAYNAK GERÇEK
- docs/strateji.md: trading stratejisi ve parametreler
- docs/teknik-spec.md: sadece referans; çelişirse yukarıdakiler kazanır
- Her oturum başında STATUS.md'yi oku, bitince güncelle

## Mutlak yasaklar
- Canlı profile emir gönderen komut ÇALIŞTIRMA. Emir testleri sadece --demo veya --dry-run ile.
- Emre giden tek yol risk kapısından geçer; bunu atlayan kod yazma.
- Emir çağrılarında otomatik retry YOK (MCP'de de, CLI yedekte de).
- Dashboard'a al/sat düğmesi koyma. Sadece başlat/duraklat/durdur/kapat; hepsi decisions.jsonl'e loglanır.
- Sayısal eşik koda gömülmez; hepsi config.yaml'da.
- MCP araç adlarını tahmin etme; docs/mcp-araclari.md'den al.
- .env ve ~/.okx/config.toml commit edilmez.

## Çalışma şekli
- Tek istekte tek teslimat. İstenmeyen özellik ekleme; önerini STATUS.md'ye not düş.
- Her modülü gerçek MCP/CLI çıktısıyla test et; varsayma, çalıştır, çıktının ilk 3 satırını göster.
- Mum verisi en yeniden eskiye gelir; ters çevir, son (kapanmamış) mumu dışla.
- Veri/emir katmanı MCP-first; CLI sadece yedek (docs/urun-mimari.md 3.2).
- Python 3.11, pandas, pydantic, tip ipuçları. Tek dosyayla başla; bölmeyi ben isteyeceğim.
- Her faz sonunda STATUS.md güncelle + git commit.
