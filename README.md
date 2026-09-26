# BGEE BAM Icon Tools

Baldur's Gate: Enhanced Edition (Infinity Engine) için **saf Python** ikon araçları.
ImageMagick/PIL gerekmez. PNG/JPEG/WEBP/BMP/SVG → BAM ikon üretir, vanilla BAM'lardan
zemin/sembol işler, önizleme üretir.

Öne çıkanlar:
- `bam_icon.py` — PNG/JPEG/WEBP/BMP/SVG → BGEE **BAM** ikon üreticisi
  (`make`, `search`/`fetch` game-icons.net, `info`).
- `spell_icon.py` — 32/64/90px büyü ikonu: vanilla BAM'dan **zemin/plaka çıkarır**,
  sembolü bindirir; `--tone`, `--relight`, `--texture`, `--dir-range` ile stil ayarı.
- `bam_preview.py` — BAM → PNG/HTML **önizleme** (13×13 + büyütülmüş).
- `imgread.py` — saf Python görüntü okuyucu (PNG tüm tipler + ffmpeg fallback).
- `svgrender.py` — saf Python **SVG rasterizer** (game-icons.net ikonları).
- `icons.example.json`, `art/` — örnek config + gri ikon sanatı.

Gereksinim: Python 3. İsteğe bağlı: `ffmpeg` (okunamayan formatlar için).

## Lisans / atıf

- Araç kodu: **MIT**.
- `art/` altındaki ikonlar **game-icons.net** (CC BY 3.0) kaynaklıdır — kullanırken atıf verin.

---

## bam_icon.py — BGEE BAM ikon üretici

Portre ve **karakter durum penceresinde** görünen efekt ikonlarını (13×13) üretir.
Girdi **her boyut ve her formatta** olabilir: 1080×1080 RGBA PNG, JPEG, WEBP, BMP,
veya game-icons.net SVG'si. Araç otomatik olarak ölçekler, arka planı ayırır ve
BAM'a çevirir.

### Mekanizma (motorda doğrulandı: `CGameSprite::AddPortraitIcon`)

1. Efekt `opcode 142`, `parameter2 = N` ile ikon ister.
2. `STATDESC.2DA` satır `N`, `BAM_FILE` sütunu okunur:
   - değer `****`/boş → **`STATES.BAM`, sequence `N+65`**
   - değer gerçek BAM adı → **o BAM, sequence `0`** (bizim durum)
3. Kayıt ekranı Lua'sı (`UI.MENU`, `statusEffects[rowNumber].bam/.current`)
   motorun doldurduğu değeri çizer → **tek standalone BAM hem portrede hem
   durum penceresinde görünür.**

Yani modda `STATDESC.2DA` satırına BAM adını yazmak (ör. 209 → `CHFURYI`) yeterli;
`STATES.BAM`'e frame eklemeye gerek yok.

### Komutlar

```bash
# JSON'dan üret
python3 tools/bam_icon.py make tools/icons.example.json

# BAM yapısını incele
python3 tools/bam_icon.py info game-work/chosen/icons/CHFURYI.bam --cycles

# URL'den indir + BAM yap
python3 tools/bam_icon.py fetch --out out/ --name ICON --tint 40,160,255 URL

# game-icons.net'te ara (git tabanlı, kota yok)
python3 tools/bam_icon.py search shield --list
python3 tools/bam_icon.py search spider --separator spider-alt \
    --out out/ --name SPIDER --index 221 --tint 170,110,230 \
    --render --render-size 256 --format bam
```

`search` çıktısındaki `--out` + `--name` verilince eşleşenleri indirir; `--render`
ile SVG'yi PNG'ye çevirir ve ardından BAM'ı üretir.

### JSON ayarları

| alan | anlam |
|------|-------|
| `out_dir` | çıktı klasörü |
| `format` | `bamc` (varsayılan) veya `bam` |
| `size` | kare boyutu (varsayılan 13) |
| `threshold` | arka plan eşiği (varsayılan 28) |
| `steps` | renk rampası kademesi (varsayılan 64) |
| `palette_base` | dolu renklerin ilk palette indeksi (varsayılan 182) |
| `palette_pool` | ayrılan slot sayısı (varsayılan 64) |
| `background` | `alpha` \| `dark` \| `light` \| `auto` |
| `outline` | dış hattı en koyu tona çevir (varsayılan `false`) |
| `tint` | varsayılan ton: `[r,g,b]` ya da `[koyu, parlak]` |
| `icons[]` | `name`, `png`, `index` (STATDESC satırı), `strRef`, `tint` |

`background` seçimi:
- **alpha** – alfa kanalını maske olarak kullan (RGBA sanat; en temiz).
- **dark** – `luminance > threshold` dolu (koyu arka plan üstü açık ikon).
- **light** – `luminance < threshold` dolu (açık arka plan üstü koyu ikon).
- **auto** – saydam piksel varsa `alpha`; yoksa kenar piksellerinden arka plan
  parlaklığını ölçüp `dark`/`light` seçer (akıllı ayrım).

### BAM biçimi

- Varsayılan **BAMC V1** (zlib sıkıştırılmış; WeiDU bundle üyeleriyle aynı).
  `format: "bam"` ile ham BAM V1 de yazılabilir.
- Tek frame, tek cycle, **13×13**. `frame entry centre = (0, 13)` (vanilla states
  frame'leriyle aynı: x=0, y=h). Ham (uncompressed) piksel verisi, `comp=0`.
- **Palet indeksi 0 = şeffaf.** Vanilla `STATES.BAM`'de görünür renkler yüksek
  indekslerdedir (ör. 182–240); düşük indeksler luminans ölçeğidir. Bu yüzden
  renkler varsayılan olarak **`palette_base=182`**'den itibaren yazılır.

### Ikon sanatı nereden bulunur

- **game-icons.net** (CC BY 3.0) — `search` komutu buradan çeker; 4.239 ikon.
  Atıf gerekir.
- **BG topluluk modları** — Gibberlings3 / Spellhold Studios modlarının `icons/`.
- **EE oyunlarının BAM'leri** — BG2/IWD/PST `STATES.BAM` ve spell ikonları.
- Mevcut gri ikonlar `tools/art/` altında (game-icons.net kaynaklı).
