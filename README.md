# Terazi

**OKX TR spot piyasasında açıklanabilir, otonom bir trading ajanı.**
Agentic Trading Hackathon · 12 Eylül 2026 · ATK (Agent Trading Kit) MCP entegrasyonu

> Kurallar gaz, LLM fren, döngü direksiyon — ve istediğin an ajana "neden?" diye sorabiliyorsun.

*Bu doküman bir strateji planı ve mühendislik özetidir, yatırım tavsiyesi değildir.*

---

## 1. Terazi ne yapar

Terazi, insan müdahalesi olmadan gün boyu çalışan bir spot trading ajanıdır:

1. OKX'i **ATK MCP araçlarıyla** gözlemler (mum verisi, emir defteri, haber, funding, smart‑money akışı).
2. **Kural tabanlı** bir stratejiyle (Bollinger + RSI ortalamaya dönüş) aday işlemler üretir.
3. Adayı sırayla mikro yapı, maliyet, **LLM yargıç** ve **aşılamaz risk kapısından** geçirir.
4. Geçen aday için iliştirilmiş TP/SL'li limit emir gönderir; sonucu izler ve uzlaştırır.
5. **Her kararını** — işlem açmadığı anlar dahil — gerekçesiyle `logs/decisions.jsonl`'e yazar.
6. Tek sayfalık bir dashboard'da anlık durumu gösterir ve kullanıcının "Ajana sor" paneliyle
   loglara doğal dilde soru sormasına izin verir.

LLM sistemde **üç ayrı rolde** görünür, hiçbirinde emir tetikleyemez:

| Rol | Ne zaman | Yetki |
|---|---|---|
| **Yargıç** | Her aday işlem için (maliyet kapısını geçtikten sonra) | Sadece fren: APPROVE / REDUCE / VETO |
| **Rejim yorumcusu** | 30 dakikada bir | Sadece yorum; kural rejimiyle çelişirse loglanır |
| **Sohbet ("Ajana sor")** | Kullanıcı sorduğunda | Sadece okur; emir veremez, config değiştiremez |

---

## 2. Kimin için — hedef kitle ve vizyon

Terazi'nin arkasındaki asıl motivasyon bir teknik gösteriden ibaret değil: kripto piyasasına
**yeni başlayan ve temkinli davranan kullanıcılar** için bir güven kapısı olmak.

Bu kesim genelde iki ihtiyaç arasında sıkışır: bir yandan piyasayı öğrenmek, araştırmak, kendi
görüşünü oluşturmak isterler; öte yandan hiç deneyimi olmadan sermayelerini doğrudan riske atmaktan
çekinirler. Terazi bu boşluğu doldurmayı hedefler:

- **Önce sermayeyi korumak, sonra büyütmek.** Ajanın önceliği agresif getiri değil, **aşılamaz risk
  kapısı** (bkz. §4.6), günlük kill switch ve varsayılan "temkinli/dengeli" risk seviyeleri ile
  zararı sınırlı tutmaktır — kullanıcı isterse daha temkinli bir seviyeye geçebilir.
- **Kademeli, açıklanabilir büyüme.** "Az sayıda ama gerekçeli işlem" felsefesi (bkz. §4, ve
  [`docs/strateji.md`](docs/strateji.md) "Beklenen profil"), agresif/sık işlemle hızlı kazanç vaat
  eden yaklaşımların aksine, sermayeyi yavaş ve ölçülü şekilde artırmayı amaçlar.
- **Güven, şeffaflıktan gelir.** Ajanın attığı veya atmadığı **her** adım gerekçesiyle loglanır ve
  dashboard'da görülebilir; kullanıcı "neden şu an işlem yapmıyorsun?" diye sorduğunda kara kutu
  bir cevap değil, sayısal bir gerekçe alır (§6, "Ajana sor"). Bu, ilk kez otonom bir yatırım
  aracına güvenmeye çalışan biri için kritik bir bariyeri kaldırır.
- **Öğrenirken paralel bir güvenlik ağı.** Kullanıcı piyasayı araştırıp kendi bilgisini
  oluştururken, Terazi arka planda sermayesinin değerini korumaya ve yavaşça artırmaya çalışır —
  yatırım öğrenimi ile sermaye erimesi arasındaki riski azaltan bir ara adım işlevi görür.

Bu konumlanış, mevcut tasarım kararlarıyla doğrudan örtüşüyor: al/sat düğmesinin dashboard'dan
kasıtlı olarak çıkarılmış olması (§6), LLM'in yalnızca "fren" rolünde bulunması (§1) ve risk
kapısının hiçbir koşulda atlanamaması (§9) — hepsi, deneyimsiz bir kullanıcının kazara veya
bilgisizce büyük risk almasını yapısal olarak zorlaştırır.

> Not: Terazi bugünkü hâliyle bir hackathon prototipidir. Yukarıdaki vizyon ürünün hedefidir, mevcut hâli değil — gerçek kullanıcı
> sermayesiyle çalışmadan önce daha uzun vadeli test, kalibrasyon ve olası ek güvenlik katmanları
> gerekir.

---

## 3. Neden bu strateji — piyasa tezi

12 Eylül sabahı BTC ~77.300'de, son iki gündür 76.000–79.500 bandında (≈%4,5 genişlik) yatay
salınıyordu; hafta sonu, makro veri yok. Bu ortamda trend takip stratejileri en kötü, **ortalamaya
dönüş** en iyi çalışan yaklaşımdır:

- **Ortalamaya dönüş:** yatay piyasada fiyat "normal" seviyesinden aşırı saptığında geri gelme eğilimindedir. Spot'ta yalnızca alım mümkün olduğu için sadece aşağı sapmalar alınır.
- **Kırılım/momentum** cumartesi günleri yalancı sinyal riski taşıdığı, **saf LLM kararı** ise tekrarlanamaz/ölçülemez olduğu için elenmiştir.

Tek cümlelik tez: *BTC'nin son 48 saatlik aralığı kendi ölçülür; aralık korunduğu sürece
BTC/ETH/SOL (ve otomatik seçilen genişletilmiş evrende) aşırı satılmış noktalarda, satış
baskısının kırıldığı hem fiyat hem emir defteriyle teyit edilerek alınır, bandın ortasında
satılır. Aralık kırılırsa nakde çekilir.*

Detaylı gerekçe, elenen alternatifler, senaryo kitabı ve beklenen profil: [`docs/strateji.md`](docs/strateji.md).

---

## 4. Strateji — beş kapılı karar zinciri

Her aday sırayla beş kapıdan geçer; herhangi biri kapalıysa işlem yoktur ve gerekçe loglanır.
Sayısal eşiklerin **tamamı** `config.yaml`'da yaşar — kodda sabit sayı yoktur.

### 4.1 Rejim kapısı — "Bugün hangi oyunu oynuyoruz?"
BTC'den türetilir, 30 dakikada bir yenilenir, tüm paritelere uygulanır.

| Koşul | Rejim |
|---|---|
| BTC 15m kapanış < `RANGE_LOW × 0,998` (son 48×1H mumun dip noktası) | **CASH** — taban kırıldı |
| BTC fiyat > `RANGE_HIGH` (son 48×1H mumun tepe noktası) | **CASH** — kovalanmıyor |
| Son mumun aralığı > 3×ATR | **30 dk giriş yasağı** — şok hareket |
| Aksi hâlde | **MEAN_REVERSION** — oyun açık |

### 4.2 Sinyal — "Aşırı satılmış mı, geri mi dönüyor?"
Kapanmış 5 dakikalık mumlarla, parite başına ayrı ayrı (kapanmamış son mum asla kullanılmaz):

- **Kurulum:** `close < BB_lower(20, 2σ)` **VE** `RSI(14) < 36`
- **Tetik** (kurulumdan sonraki 2 mum içinde): `close > BB_lower` **VE** `close > kurulum_mumu.low`
- İki mum içinde tetik gelmezse kurulum iptal edilir.

### 4.3 Mikro yapı teyidi — "Emir defteri de aynı şeyi söylüyor mu?"
Aday kapıya girerken o parite için **taze bir defter örneği** alınır:
`OBI(±10bps) ≥ 0` **VE** `spread ≤ 2 × son 30 dk medyan spread`. Aynı katman gün boyu her 20
saniyede bir örnek alıp `micro.jsonl`'e yazar; dashboard'da sparkline olarak görünür.

### 4.4 Maliyet kapısı — "Bu işlem komisyonu karşılar mı?"
```
hedef_bps   = (BB_mid − giriş) / giriş × 10.000
maliyet_bps = 2 × fee_bps + spread_bps
koşul:        hedef_bps ≥ 2,5 × maliyet_bps
```
Bant daraldıkça bu kapı çoğu adayı eler — istenen davranış budur.

### 4.5 LLM yargıç — "Bu düşüş sıradan mı, haber mi?"
Yalnızca mikro + maliyet kapısını geçen aday için çağrılır. Girdi: aday özeti, son 10 mum, ATK
`news`/`funding` verisi. **LLM frene basabilir, gaza basamaz**: `APPROVE|REDUCE(0,3–1,0)|VETO`.
Emin değilse VETO; zaman aşımında (20 sn) aday geçirilir ve `status: failed_open` loglanır.

### 4.6 Risk kapısı — aşılamaz katman
Emre giden **tek yol** buradan geçer; bunu atlayan kod yoktur (`_place_entry`/`close_now` dışında
`tools.place_order` çağrılmaz).

| # | Kontrol | Değer (dengeli) | Neden |
|---|---|---|---|
| 1 | Kill switch | Günlük PnL ≤ −%1,5 → gün bitti | ~6–7 kayıp |
| 2 | Cooldown | 2 ardışık **net** kayıp → 45 dk giriş yok | Kötü koşulda ısrar etme |
| 3 | Günlük işlem tavanı | 8 | Komisyon sınırı |
| 4 | Eşzamanlı pozisyon | En fazla 2 | Pariteler korelasyonlu |
| 5 | Parite başına | Aynı paritede ikinci pozisyon yok | |
| 6 | Boyut | equity × %30 (≈9 USDT / 30 USDT) | minSz üstü |
| 7 | Stop mesafesi | 50–120 bps bandı, dışındaysa **red** | R:R kontrolü |
| 8 | Enstrüman kısıtı | lotSz'a yuvarla; minSz altı → red | |
| 9 | Bakiye | notional ≤ kullanılabilir | |
| 10 | Saat | 18:30 sonrası yeni giriş yok, 19:10'da tüm pozisyonlar kapanır | Gün sonu payı |

Stop: `setup_low − 0,2×ATR`. Hedef: `BB_mid`, maker limit satış. İcra: limit alış = en iyi alış +
1 tick, 90 sn'de dolmazsa iptal; **emir çağrılarında otomatik yeniden deneme yok** — tek deneme,
hata loglanır.

### 4.7 Operatör risk seviyeleri
Kontrol #1, #3, #4, #6 ve cooldown süresi, dashboard'dan seçilebilen üç seviyeye bağlıdır
(strateji eşikleri — RSI, OBI, maliyet çarpanı, stop bandı — seviyeden bağımsızdır):

| Seviye | Pozisyon | Eşzamanlı | Günlük tavan | Kill switch | Cooldown |
|---|---|---|---|---|---|
| Temkinli | %20 | 1 | 4 | −%1,0 | 60 dk |
| **Dengeli (varsayılan)** | %30 | 2 | 8 | −%1,5 | 45 dk |
| Agresif | %40 | 3 | 12 | −%2,5 | 30 dk |

---

## 5. Mimari

### 5.1 İki bağımsız süreç, tek dosya sistemi üzerinden konuşuyor

```
terazi.py      ajan döngüsü        ──yazar──►  logs/decisions.jsonl, orders.jsonl, micro.jsonl,
                                                llm.jsonl, state.json
dashboard.py   FastAPI + index.html ◄──okur──  aynı dosyalar (2 sn polling)
               ──yazar──►  control.json  {"mode":"run|pause|kill","flatten":bool,
                                            "risk_level":"cautious|balanced|aggressive"}
terazi.py      ◄──okur──  control.json (her turun başında)
```

Dashboard çökerse ajan durmaz; ajan çökerse dashboard "AJAN YANIT VERMİYOR" gösterir
(`state.json` 60 sn'den eskiyse). Operatör eylemlerinin **tek yazarı ajandır** — dashboard yalnızca
`control.json`'a yazar, ajan değişimi görünce `OPERATOR_*` satırını kendisi düşer.

### 5.2 Ajan döngüsü (özet zaman çizelgesi)

```
her 20 sn        : control.json oku → bir alt küme paritenin orderbook+trades → micro.jsonl
5m kapanış+15 sn : candles → indikatörler → rejim (30 dk'da bir) → sinyal
                   aday varsa: taze mikro örnek → mikro teyit → maliyet kapısı → yargıç (LLM)
                   → risk kapısı → emir
her 30 dk        : rejim yorumcusu (LLM) → llm.jsonl + state.json
her 60 sn        : açık emirler + bakiye ile uzlaş → zaman/gün sonu kontrolleri
her saat         : evren yeniden seçilir (hacme göre) → UNIVERSE satırı
her hata         : logla → 30 sn bekle → devam — ajan asla tamamen durmaz
```

### 5.3 Araç katmanı — MCP-first, CLI yedek

- `okx-trade-mcp` yerel stdio süreci olarak başlatılır (`market, account, spot, news, smartmoney`
  modülleri). Gerçek araç adları [`docs/mcp-araclari.md`](docs/mcp-araclari.md)'den alınır —
  **tahmin edilmez**.
- Bir MCP çağrısı iki kez üst üste hata verirse aynı **veri** çağrısı `okx` CLI'dan tek deneme ile
  yapılır ve `transport: "cli_fallback"` loglanır. Yedek yalnızca beş veri aracı için vardır
  (`market_get_candles|orderbook|trades|ticker`, `account_get_balance`); emir/algo araçlarının
  yedeğe düşmesi kod düzeyinde `assert` ile imkânsız kılınmıştır (çift emir riski + CLI çıktısında
  `capabilities.demo` olmadığı için emir güvenlik kapısı yedekten beslenemez).
- Emir öncesi her `spot_place_order`, borsadan gelen `capabilities.demo` alanını profildeki
  `expected_demo` ile karşılaştırır; eşleşmezse emir **gönderilmez**.

| ATK modülü | Kullanım |
|---|---|
| `market` (candles, orderbook, trades, instruments, ticker, indicator) | sinyal, mikro yapı, rejim, evren seçimi |
| `market` (funding-rate) | yargıç girdisi |
| `account` (balance, fees) | equity, komisyon, risk boyutlandırma |
| `spot` (place ile iliştirilmiş TP/SL, cancel, orders, fills) | icra ve uzlaştırma |
| `news` (by-coin, sentiment) | yargıç girdisi |
| `smartmoney` (signal-overview) | rejim yorumcusu girdisi |

### 5.4 LLM katmanı (`judge.py`)

Doğrudan Anthropic API (`anthropic` SDK). Birincil `claude-sonnet-5`, yedek
`claude-haiku-4-5-20251001`; zaman aşımı 20 sn, SDK yeniden denemesi kapalı. Sıra: birincil →
hata/zaman aşımında yedek → o da başarısız olursa **fail-open** (aday geçirilir,
`status: "failed_open"` loglanır). Sohbet ("Ajana sor") ayrı bir modülde (`ask.py`) yaşar; salt
okunur 7 MCP aracına erişebilir, `spot_*` hiç tanımlı değildir (modül düzeyinde `assert` ile
zorlanır), soru başına en fazla 4 araç çağrısı yapabilir.

### 5.5 Evren seçimi (otomatik mod)

`universe.mode: auto` iken parite listesi sabit değildir: `market_filter` ile ≥10M USD 24s hacimli
USDT spot pariteleri (stablecoin çiftleri hariç) hacme göre sıralanır, minSz filtresinden geçenlerin
ilk `top_n`'i alınır. Seçim **saat başı** yenilenir ve `UNIVERSE` satırına loglanır; açık pozisyonu
olan bir parite evrenden asla düşmez. `mode: fixed` ile sabit 5 pariteye (`BTC, ETH, SOL, XRP,
DOGE`) dönülebilir. 20 pariteyi aşan bir evrende mikro örnekleme alt kümelere bölünür
(`micro.max_pairs_per_turn`), her paritenin örnekleme aralığı `sample_interval_sec` olarak
loglanır.

### 5.6 Dosya yapısı

```
terazi/
├── terazi.py          # ajan döngüsü (tek dosya)
├── tools.py           # MCP client + CLI yedek
├── judge.py           # LLM görevleri (yargıç + rejim yorumcusu)
├── ask.py             # "Ajana sor" sohbet çekirdeği
├── calibrate.py        # backtest / eşik kalibrasyonu
├── dashboard.py        # FastAPI sunucusu
├── static/index.html   # tek sayfalık dashboard arayüzü
├── config.yaml          # TÜM sayısal eşiklerin tek kaynağı
├── control.json         # operatör kontrol yüzeyi (dashboard yazar, ajan okur)
├── state.json            # ajanın kalıcı durumu (kurtarma bunun üzerinden)
├── logs/                 # decisions.jsonl · orders.jsonl · micro.jsonl · llm.jsonl · ask.jsonl
└── docs/                 # urun-mimari.md · strateji.md · teknik-spec.md · mcp-araclari.md · ...
```

---

## 6. Dashboard

Tek sayfa, koyu tema (OKX tarzı, siyah zemin + lime vurgu), Tailwind + Chart.js, build adımı yok,
2 sn polling, port 8787.

- **Üst şerit:** rejim rozeti, equity, günlük PnL %, açık pozisyon sayısı, evren/tur/aktarım
  (MCP/CLI) durumu, seçili risk seviyesi.
- **Sol sütun:** equity eğrisi, karar akışı (son kararlar, tıklayınca tam JSON), LLM paneli.
- **Sağ sütun:** açık pozisyonlar, kapanan işlemler (net PnL, komisyon dahil), **"Ajana sor"**
  sohbet paneli (3 hazır soru + serbest metin), mikro yapı sparkline'ları (OBI + spread, 12 parite).
- **Kontrol çubuğu:** Duraklat/Devam ve risk seviyesi seçici. **Al/sat düğmesi yoktur** — kural
  gereği (`CLAUDE.md`). Acil Durdur / Tümünü Kapat butonları kullanıcı kararıyla arayüzden
  kaldırıldı (`STATUS.md`); sunucu tarafında `mode: kill` / `flatten: true` hâlâ desteklenir,
  gerektiğinde `control.json` elle düzenlenerek veya CLI ile tetiklenir.

Endpoint'ler: `GET /state`, `GET /feed`, `GET /llm`, `GET /equity`, `GET /micro`, `POST /ask`,
`POST /control`.

---

## 7. Kurulum ve çalıştırma

### Gereksinimler
- Python 3.11, sanal ortam `.venv/` (paketler: `mcp`, `pandas`, `pydantic`, `numpy`, `pyyaml`,
  `fastapi`, `uvicorn`, `anthropic`)
- `okx` CLI + `okx-trade-mcp` kurulu (ATK)
- Proje kökünde `.env`: `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` (commit edilmez)
- `~/.okx/config.toml` içinde `hackathon` (canlı) ve `hackathondemo` (demo) profilleri

### Ajanı başlat
```bash
# Demo/dry-run testi (emir gitmez):
.venv/bin/python terazi.py --profile hackathondemo --demo --max-turns 5
.venv/bin/python terazi.py --profile hackathon --dry-run --max-turns 3

# Canlı (gerçek emir gönderir!):
nohup .venv/bin/python -u terazi.py --profile hackathon > logs/terazi.out 2>&1 & disown
```
`-u` bayrağı şarttır — onsuz stdout tamponlanır. `--demo` / `--dry-run` verilmezse ajan canlı
hesaba emir gönderebilir; bu yüzden **canlı profile emir gönderen komutlar yalnızca bilinçli ve
onaylı şekilde çalıştırılmalıdır.**

### Dashboard'u başlat
```bash
.venv/bin/uvicorn dashboard:app --port 8787
# → http://localhost:8787
```

### Ajanı kontrol et (`control.json`)
```bash
echo '{"mode":"pause"}' > control.json                    # veri akışı devam, yeni giriş yok
echo '{"mode":"kill","flatten":false}' > control.json      # ajan temiz çıkar (pozisyonlar borsa TP/SL ile korunur)
echo '{"mode":"run","flatten":true}' > control.json         # tüm pozisyonları kapat
```

### Kalibrasyon (backtest)
```bash
.venv/bin/python calibrate.py --pairs BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,DOGE-USDT
```
Çıktı: `docs/kalibrasyon.md` / `docs/kalibrasyon-5m.md` — parite × RSI eşiği tablosu
(kurulum/tetik/kazanç/kayıp/zaman aşımı sayıları, ortalama hedef/stop bps).

---

## 8. Config — tek kaynak (`config.yaml`)

Hiçbir sayısal eşik kodda gömülü değildir; hepsi burada, açıklamalı satırlarla. Öne çıkan
bloklar: `universe` (evren seçimi), `signal` (BB/RSI/ATR, bar, RSI eşiği 36), `regime` (1H, 48
mum), `micro` (OBI/spread parametreleri), `cost` (2,5× çarpan), `risk` + `risk_levels`
(temkinli/dengeli/agresif), `execution` (limit ömrü, gün sonu saati), `profiles` (canlı/demo),
`llm` (model, zaman aşımı, bütçeler), `demo_test` (yalnızca demo profilinde çalışan sentetik
uçtan-uca test).

---

## 9. Güvenlik ve tasarım ilkeleri

- **Emre giden tek yol risk kapısından geçer**; bunu atlayan kod yazılmaz.
- **Emir çağrılarında otomatik yeniden deneme yoktur** (ne MCP'de ne CLI yedeğinde) — çift emir
  riski kabul edilmez.
- **Dashboard'da al/sat düğmesi yoktur.** Yalnızca başlat/duraklat/devam/risk seviyesi; her
  operatör eylemi `decisions.jsonl`'e `OPERATOR_*` satırı olarak düşer, görünmez müdahale yoktur.
- **Fail-open yalnızca LLM'de**, risk kapısında değil: yargıç zaman aşımına uğrarsa aday geçer ve
  loglanır; risk kapısındaki 10 kontrolden hiçbiri gevşetilmez.
- **State kurtarma:** `state.json` silinse veya ajan çökse bile açık pozisyon, TP/SL algo emri ve
  ödenen komisyon borsadan yeniden kurulur — dosyaya değil borsanın gerçeğine güvenilir.
- **MCP→CLI yedeği sadece veri okur**, emir asla CLI'ya düşmez.

---
