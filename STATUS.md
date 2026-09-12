# STATUS

## Faz 4 — Dashboard MVP: TAMAM (12 Eylül, 13:20 +03:00)

**Teslimat:** `dashboard.py` (FastAPI, port 8787) + `static/index.html` (Tailwind CDN, build yok).
Ayrı süreç; **MCP çağrısı yok, borsaya temas yok.** Kaynak yalnızca `logs/decisions.jsonl`,
`logs/orders.jsonl`, `state.json`, `control.json`. 2 sn polling.

### Başlatma komutu
```bash
cd /Users/osmancanbozali/Desktop/terazi
.venv/bin/uvicorn dashboard:app --port 8787
# arka plan: nohup .venv/bin/uvicorn dashboard:app --port 8787 > logs/dashboard.out 2>&1 & disown
```
Bind **127.0.0.1** (uvicorn varsayılanı). `POST /control` kimlik doğrulaması yok — LAN'a açmak
(`--host 0.0.0.0`) ağdaki herkese durdur/kapat yetkisi verir. `.venv`'ye `fastapi 0.141.1` kuruldu
(uvicorn zaten vardı).

### Uçlar
| Uç | Döndürdüğü |
|---|---|
| `GET /state` | `state.json` + `agent_alive` (state 60 sn'den eskiyse false) + son karar ts/yaşı + `control` + `regime` + `kill_switch{active,reason,detail}` + `cooldown` + bugünkü sayaçlar |
| `GET /feed?n=50` | son n karar, **en yeni önce**, + atlanan bozuk satır sayısı |
| `GET /orders` | `orders.jsonl` tamamı; her satırda `ok` ve `sCode` yüzeye çıkarılmış |
| `POST /control` | `{"mode":"run\|pause\|kill"}` veya `{"flatten":true}`; **kill ve flatten `"confirm": true` ister, yoksa 400** |

`POST /control` `control.json`'u **birleştirerek ve atomik** yazar (geçici dosya + `os.replace`) —
ajan her turun başında okuduğu için yarım JSON görmemeli. Ayrıca `decisions.jsonl`'e
`OPERATOR_*` satırı düşer, `"source": "dashboard"` alanıyla.

### Doğrulama (hepsi gerçek çıktıyla)
- **Sayaçlar dosyayla birebir:** `/state` → `total 61, WAIT 59, OPERATOR 2`;
  `wc -l` 61, `grep` dağılımı `{'WAIT': 59, 'OPERATOR_KILL': 2}`.
- **Onay kapısı:** `{"mode":"kill"}` ve `{"flatten":true}` confirm'siz → **HTTP 400**, gövdede Türkçe
  gerekçe, `control.json` **el değmemiş** (`cat` ile kanıtlandı). Confirm'li kill/flatten hiç
  çalıştırılmadı.
- **pause → run canlı ajanla:** 13:04:47 dashboard `OPERATOR_PAUSE` (`source: dashboard`) →
  13:05:07 ajanın kendi `OPERATOR_PAUSE` onayı → 13:05:12 `WAIT / "operatör pause: emir yok"`.
  Sonra `{"mode":"run"}` → 13:05:25 komut, ajan normal `WAIT` gerekçesine döndü.
  **Test `mode=run` ile bitti** (`control.json` = `{"mode":"run","flatten":false}`).
- **Boş log:** izole dizinde boş `logs/` → "henüz karar yok" / "pozisyon yok" / "emir yok",
  equity "— USDT", ajan rozeti kırmızı "AJAN YANIT VERMİYOR". Ekran bozulmadı.
- **Bozuk satır:** 2 sağlam + 1 bozuk JSON + 1 sözlük olmayan satır → `/feed` 2 satır döndürdü,
  `skipped: 2`, konsola "bozuk JSON satırı atlandı" yazdı. **Akış düşmedi.**
- **Ekran (Playwright, 1440×900):** `scrollWidth/Height == innerWidth/Height` → **kaydırma yok**,
  konsolda **JS hatası yok**. Üst şerit tek satır 7 kart; orta 2/3 karar akışı (kendi içinde kayar);
  sağ 1/3 pozisyon + son emirler; alt çubukta Duraklat / Acil Durdur / Tümünü Kapat + `mode` rozeti.

### Faz 4'te bilinçli bırakılanlar
- **Giriş yasağı (sarı rejim rozeti) akıştan türetiliyor.** `state.json` `vol_ban_until_ms`'i
  taşımıyor; dashboard `gate="volatility"` satırının zamanı + `config.regime.vol_ban_sec` ile
  hesaplıyor. **Sınır:** ajan yeniden başlarsa yasak bellekte sıfırlanır, dashboard süre dolana
  kadar sarı göstermeye devam eder. Kalıcı çözüm: `state.json`'a `vol_ban_until_ms` yazmak.
- **`config.yaml`'a `dashboard:` bloğu eklenmeli.** Dashboard'un iki sayısı (2 sn polling,
  60 sn bayatlık) `config.yaml`'daki isteğe bağlı `dashboard:` bloğundan okunuyor; blok yokken
  spec değerine düşüyor. Blok eklenince kod değişmeden oradan okunur.
- Chart.js yüklenmedi (equity eğrisi Faz 6). LLM paneli, mikro sparkline, "Ajana sor" Faz 5–6.
- Emir satırında yön, `request.side`'dan okunuyor; `orders.jsonl` canlıda hâlâ boş olduğu için
  bu alan yalnızca arşivdeki demo satırlarıyla doğrulandı.

## kill_switch hotfix — operatör kill'i risk bayrağından ayırma (12 Eylül, 13:10 +03:00)

**Sorun:** `state.json`'da `kill_switch: true` duruyordu ve risk kapısının 1. kontrolü her adayı
reddediyordu — ajan canlıda çalışıyor, veri topluyor, karar logluyor ama **emir gönderme yolu
kapalıydı.** Bayrağı 12:47'deki operatör kill yazmıştı.

**Kök neden:** iki farklı kavram tek alanı paylaşıyordu. "Günlük zarar −%1,5'i aştı, bugün bitti"
(kalıcı **risk** kararı) ile "operatör döngüyü durdurdu" (geçici **süreç** kararı) aynı
`state.kill_switch`'e yazıyordu; ikincisi birincinin kalıcılığını miras alıyor ve yeniden
başlatılan ajan sessizce emirsiz kalıyordu.

**Dört dokunuş (`terazi.py`):**
1. `tick()` içindeki operatör kill bloğundan `self.state.kill_switch = True` **silindi** —
   kill döngüyü durdurur, günlük risk kararı vermez.
2. Risk kapısı 1. kontrol ikiye ayrıldı: bayrağı **yalnızca** `daily_pnl_pct ≤ eşik` set eder,
   okuma ayrı dalda. Davranış aynı (zarar eşiği aşılınca gün kapanır), ama bayrağın **tek yazarı** kaldı.
3. Gün başı equity alınırken `kill_switch = False`; `day_start` karar satırının gerekçesi güncellendi.
4. `startup()`: `control.json`'da `mode=kill` bulunursa **bir kerelik tüketilir** → `run`,
   `OPERATOR_KILL_CLEARED` loglanır. Acil Durdur çalışan döngüyü durdurur, **yeniden başlatmayı
   engellemez.** `flatten` bayrağına dokunulmaz.

**Doğrulama — izole sandbox** (scratch dizine kopya + `--dry-run`; canlı `logs/` ve `state.json`'a
ikinci süreç yazmasın diye):
- `mode=kill` ile açılış → `control.json` `run`'a döndü, `OPERATOR_KILL_CLEARED` satırı düştü,
  döngü **ölmedi** (2 tur çalışıp `--max-turns` ile temiz çıktı), `orders.jsonl` hiç oluşmadı.
- Gün ortası (`day_start_equity` dolu) + `kill_switch: true` → bayrak **korundu** (gerçek günlük
  zarar kill'i kaybolmuyor).
- `day_start_equity: null` + `kill_switch: true` → gün başı bloğu bayrağı **sıfırladı**.

**Canlıda:** ajan 13:14'te yeni kodla yeniden başlatıldı; `logs/terazi.out`'ta
`control.json mode=kill tüketildi → run` ve `decisions.jsonl`'de 13:14:21 `OPERATOR_KILL_CLEARED`
göründü. Yol canlıda çalışıyor.

### ⚠️ AÇIK İŞ: `state.json`'daki bayat `kill_switch: true` hâlâ duruyor
Hotfix bayrağın **yeniden yazılmasını** engelliyor ama **mevcut değeri temizlemiyor** — bu değer
eski buggy kodun kalıntısı. Ajan durdurulmadan düzeltilemez (her turda bellekteki durumu dosyaya
yazıyor). Emir yolu açılana kadar ajan hiçbir işlem açamaz:
```bash
cd /Users/osmancanbozali/Desktop/terazi
pkill -f "terazi.py --profile hackathon"
python3 -c "import json,pathlib; p=pathlib.Path('state.json'); d=json.loads(p.read_text()); d['kill_switch']=False; p.write_text(json.dumps(d,ensure_ascii=False,indent=2))"
grep kill_switch state.json          # false görmeli
nohup .venv/bin/python -u terazi.py --profile hackathon > logs/terazi.out 2>&1 & disown
```
Alternatif: `state.json`'daki `day_start_equity`'yi `null` yapmak da bayrağı sıfırlar (3. dokunuş),
ama gün başı tabanını o anki bakiyeye taşır — günlük PnL geçmişi sıfırlanır. Yukarıdaki komut tercih edilir.

## Canlı başlatma düzeltmesi (12 Eylül, 09:40 UTC)

**Sorun:** demo testinden kalan `state.json` canlı ajana taşındı. `day_start_equity` = 100.435
(demo), `equity` = 29,99 (canlı) → `daily_pnl_pct` **−99,97** → risk kapısının 1. kontrolü
(kill switch, eşik −%1,5) her adayı reddediyordu. Ajan canlıda çalışıyor ama **hiç işlem
açamaz** durumdaydı. Ayrıca `logs/*.jsonl` demo satırlarıyla karışıktı (61 karar satırının 46'sı
demo equity'si taşıyordu; `orders.jsonl`'in 4 satırının tamamı demo SOL emirleriydi).

**Düzeltme — durum artık profil damgalı:**
- `state.json`'a **`profile`** ve **`demo`** (`capabilities.demo`) alanları yazılıyor.
- Açılışta damga çalışma anındakiyle uyuşmuyorsa (damga hiç yoksa da) durum **YOK SAYILIR**:
  `state.<eski_profil>-<ts>.json` olarak arşivlenir, `logs/*.jsonl` →
  `logs/archive/<eski_profil>-<ts>/` altına taşınır, sıfırdan başlanır. Gün başı equity o anki
  hesabın **gerçek bakiyesinden** alınır. Uyuşmazlık `decisions.jsonl`'e
  `ERROR` / `gate: state_profile_mismatch` satırı olarak düşer (temiz loga, arşivlemeden sonra).
- Durum yüklemesi `__init__`'ten `startup()`'a taşındı: `capabilities.demo` bilinmeden
  uyuşmazlık tespit edilemez.
- `control.json` `{"mode":"kill"}` artık döngüyü **temiz kapatıyor** (önceden sadece emirleri
  durduruyordu, süreç sonsuza dek dönüyordu). Pozisyonlar kapatılmaz — borsadaki TP/SL korur;
  hepsini kapatmak ayrı eylem (`flatten`). "Ajan asla durmaz" kuralı hatalar için; operatör
  komutu bunun dışında.
- Başlatma komutu **`python -u`** oldu (aşağıda). Tamponlama yüzünden `logs/terazi.out` boş kalıyordu.
- `.gitignore`: `state.*.json` (arşivler).

**Doğrulama:** sahte demo damgalı state ile canlı profil `--dry-run` başlatıldı → arşivleme
çalıştı (`state.hackathondemo-20260912-123447.json`, `logs/archive/hackathondemo-.../` içinde
3 jsonl), gün başı equity canlıdan 29,9919 olarak alındı. `kill` yolu dry-run'da temiz çıktı.

**Canlı yeniden başlatıldı** (12:40 +03:00, `python -u`, `--profile hackathon`). İlk karar satırları:
```
2026-09-12T12:40:26+03:00  WAIT  equity=29.9919  daily_pnl_pct=0.0  (gün başı equity alındı)
2026-09-12T12:40:35+03:00  WAIT  equity=29.9919  daily_pnl_pct=0.0  (kurulum yok)
```
`state.json` damgası: `profile=hackathon`, `demo=False`, `day_start_equity=29.9919`,
`kill_switch=False`, `trade_day=2026-09-12`. **Kill switch artık kapalı, risk kapısı geçirgen.**

**Bu düzeltmeyle kapanan yan bulgu:** eski `decisions.jsonl`'deki 4 `ERROR` satırı,
`ordId` boş kalan başarısız demo emrinin (kod 51094) her turda `spot_get_order` ile
sorgulanmasından geliyordu (kod 51003). `_check_scode` artık başarısız emri pozisyona/bekleyene
hiç çevirmediği için bu döngü kökten imkânsız.

**Ertelendi:** gün devri. `trade_day` yazılıyor ama tarih değişince günlük sayaçların
(`day_start_equity`, `daily_trades`, `consecutive_losses`, `kill_switch`) sıfırlanması
uygulanmadı — yarışma tek gün olduğu için bugün etkisi yok. Ajan gece yarısını aşarsa
gün başı equity dünden kalır.

## Şu anki faz
**Faz 4 — Dashboard MVP: TAMAM** (12 Eylül 2026, 13:20 +03:00). Sıradaki: **Faz 5 — `judge.py`**
(yargıç + rejim yorumcusu, `llm.jsonl`).

**Faz 2 — `terazi.py` + `tools.py` MVP: TAMAM** (12 Eylül 2026, 09:07 UTC).
Demo'da bir emir uçtan uca geçti: giriş → dolum → `algoId` yakalama → kurtarma → kapatma.
**Canlıya emir gönderilmedi.**

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
23. **~~Kapıda reddedilen aday paritenin ufkunu tüketiyor.~~ DÜZELTİLDİ** (canlıya geçmeden,
    12 Eylül 09:18 UTC). Eskiden `SetupTracker` tetik anında HOLDING'e geçtiği için, aday sonradan
    mikro/maliyet/risk/judge kapısında reddedilse bile o parite 12 mum boyunca yeni kurulum
    aramıyordu — bir mikro gürültüsü paritenin 3 saatini yiyordu.
    **Yeni davranış:** tetik `PENDING` durumuna geçirir; ufuk ancak **emir gönderilince**
    (`confirm()`) tüketilir, **herhangi bir kapı reddederse** (`reject()`) tracker `IDLE`'a döner ve
    parite **bir sonraki mumda** yeni kurulum arayabilir. Bu, sınıfta zaten var olan
    "stop bandı reddi ufuk tüketmez" kuralıyla tutarlı hâle geldi.
    `PENDING` çözülmeden `step()` çağrılırsa `RuntimeError` atar — sıra hatası sessiz kalamaz;
    `terazi.py` bu yüzden adayı mumun kendi döngüsü içinde çözüyor.
    **Kalibrasyon etkilenmedi:** backtest'te kapı olmadığı için `scan()` her tetikte `confirm()`
    çağırıyor. Sabit sentetik veride eski/yeni semantik üç eşikte de birebir aynı çıktı
    (kurulum/tetik/kazanç/kayıp/zaman aşımı/maliyet✓ tamamı eşit) ve gerçek tablo yeniden
    üretildiğinde **15 sonuç satırının hepsi değişmeden kaldı** — yalnızca hacim ve RSI çapraz
    kontrol sayıları oynadı, o da 35 dk daha yeni veri penceresinden.
    Öz-testler 7 → **9 vakaya** çıktı: "tetik + kapı reddi → IDLE" ve "PENDING çözülmeden
    step() → RuntimeError".
    **Kalan davranış:** emir gönderilip 90 sn'de dolmazsa ufuk yine tüketilmiş olur (emir gitti
    sayılır). Bunu gevşetmek istersen Faz 7'de konuşulmalı.
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

### Canlı başlatma komutu
```bash
cd /Users/osmancanbozali/Desktop/terazi
# Önce kontrol: config.yaml'da rsi_setup_threshold 36 ve demo_test.enabled false olmalı.
nohup .venv/bin/python -u terazi.py --profile hackathon > logs/terazi.out 2>&1 & disown
```
**`-u` ŞART.** Onsuz stdout tamponlanıyor ve `logs/terazi.out` saatlerce boş kalıyor —
ajan çalışıyor mu diye bakacak yer yok (12 Eylül'de bu yaşandı).

Bayraklar: `--demo` YOK, `--dry-run` YOK (ikisi de emri engeller). `--max-turns` verilmezse
sonsuz döngü. Kontrol `control.json` ile: `{"mode":"pause"}` (veri devam, emir yok) ·
`{"mode":"kill"}` (**ajan temiz çıkar**, pozisyonlar borsadaki TP/SL ile korunur) ·
`{"mode":"run","flatten":true}` (hepsini kapat). Güvenlik kapısı canlıda `expected_demo=false`
bekler; demo MCP'sine yanlışlıkla bağlanılırsa emir gitmez, `decisions.jsonl`'e ERROR düşer.

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
- **ÇALIŞIYOR.** Profil: `hackathon` (demo=False). Son başlatma: **12 Eylül 13:14 +03:00**
  (kill_switch hotfix'li kod), `nohup .venv/bin/python -u terazi.py --profile hackathon > logs/terazi.out 2>&1 &`.
  Canlıya **henüz emir gönderilmedi** (`orders.jsonl` boş).
- **⚠️ `state.json`'da `kill_switch: true` bayat değeri duruyor → emir yolu hâlâ kapalı.**
  Temizleme komutu yukarıda ("AÇIK İŞ" başlığı). Bu yapılmadan ajan işlem açamaz.
- Dashboard: `.venv/bin/uvicorn dashboard:app --port 8787` → http://localhost:8787
- Canlı hesap (`hackathon`) bakiyesi: 30 USDT (totalEq 29.9919 = gün başı tabanı).
- Durdurmak için: `echo '{"mode":"kill","flatten":false}' > control.json` (ajan temiz çıkar).
- Demo hesap (`hackathondemo`): 1 emir atıldı ve kapatıldı. SOL bakiyesi toz seviyesinde
  (1.11e-7), pending algo emri 0 — açık pozisyon kalmadı.
