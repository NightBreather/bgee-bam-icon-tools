#!/usr/bin/env python3
"""BGEE BAM icon generator (portre + karakter durum penceresi ikonlari).

Kullanim:
  python3 tools/bam_icon.py make tools/icons.json
  python3 tools/bam_icon.py info STATES.BAM

JSON yapisi:
{
  "out_dir": "game-work/chosen/icons",
  "format": "bamc",          // "bam" | "bamc"  (varsayilan bamc)
  "size": 13,
  "threshold": 28,           // arka plan esigi (8-bit luminance/alpha)
  "steps": 64,               // renk rampasi kademesi
  "palette_base": 182,       // dolu renklerin ilk palette indeksi
  "palette_pool": 64,        // ayrilan palette slotu (base..base+pool)
  "background": "auto",      // "auto" | "dark" | "light" | "alpha"
  "outline": false,          // dis hattaki pikselleri en koyu tona cevir
  "tint": [255, 180, 60],    // varsayilan tek ton
  "icons": [
    {"name": "CHFURYI", "png": "art/flame.png", "index": 209, "tint": [255, 120, 30]},
    {"name": "CHRESI",  "png": "art/shield.png", "index": 210,
     "tint": [[20, 40, 120], [140, 190, 255]]}
  ]
}

`background` aciklamasi:
  alpha : alfa kanalini maske olarak kullan (RGBA sanat; en temiz sonuc)
  dark  : luminance > threshold olan pikseller dolu; koyu sanat icin
  light : luminance < threshold olan pikseller dolu; gri/beyaz sanat icin
  auto  : saydam pikseller varsa "alpha", yoksa "light"
`tint` tek renk ([r,g,b]) ya da [koyu, parlak] iki ton; rampa ikisi arasinda olusur.

Her ikon icin <out_dir>/<name>.<format> uretilir; ayrica index verilirse
(out_dir)/bam_icons.txt olarak ele->BAM eslemesi yazilir.
"""
import argparse
import json
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgread


def load_pixels(path, svg_size=1024):
    """Herhangi bir goruntu dosyasini okur -> (w, h, lum, alpha).

    SVG dosyalari once svgrender ile rasterize edilir (seffaf arka plan).
    """
    head = open(path, 'rb').read(16)
    if head[:5] == b'<?xml' or head[:4] == b'<svg' or path.lower().endswith('.svg'):
        import svgrender
        text = open(path, encoding='utf-8', errors='replace').read()
        w, h, rgb, alpha = svgrender.rasterize(text, svg_size)
    else:
        w, h, rgb, alpha = imgread.read_image(path)
    n = w * h
    lum = bytearray(n)
    for k in range(n):
        o = k * 3
        lum[k] = (rgb[o] * 299 + rgb[o + 1] * 587 + rgb[o + 2] * 114) // 1000
    return w, h, lum, alpha


def _rgb_of(path, svg_size=1024):
    """Yalnizca (w, h, rgb) dondurur; SVG destekli."""
    head = open(path, 'rb').read(16)
    if head[:5] == b'<?xml' or head[:4] == b'<svg' or path.lower().endswith('.svg'):
        import svgrender
        text = open(path, encoding='utf-8', errors='replace').read()
        w, h, rgb, _ = svgrender.rasterize(text, svg_size)
        return w, h, rgb
    return imgread.read_image(path)[:3]


def detect_background(w, h, rgb, alpha, border=2):
    """Kenar/corner piksellerinden arka plan rengini tahmin eder.

    Donus: (is_transparent, bg_lum, bg_rgb)
      is_transparent: alfa kanali gercekten maske olarak kullanilabilir mi
      bg_lum         : arka planin ortalama luminance'i (0..255)
    """
    n = w * h
    alphas = [alpha[k] for k in range(n)]
    trans_ratio = sum(1 for a in alphas if a < 128) / n
    # Kenar ornekleri
    edge = []
    for y in range(h):
        for x in range(w):
            if x < border or y < border or x >= w - border or y >= h - border:
                edge.append((x, y))
    if not edge:
        edge = [(0, 0)]
    lums = []
    for (x, y) in edge:
        k = y * w + x
        o = k * 3
        lums.append((rgb[o] * 299 + rgb[o + 1] * 587 + rgb[o + 2] * 114) // 1000)
    bg_lum = sum(lums) // len(lums)
    return trans_ratio > 0.02, bg_lum


def to_lum_alpha(w, h, lum_rgb, alpha):
    return lum_rgb, alpha


def box_downscale(w, h, buf, ow, oh):
    out = bytearray(ow * oh)
    for oy in range(oh):
        y0 = oy * h // oh
        y1 = max(y0 + 1, (oy + 1) * h // oh)
        for ox in range(ow):
            x0 = ox * w // ow
            x1 = max(x0 + 1, (ox + 1) * w // ow)
            s = cnt = 0
            for y in range(y0, y1):
                row = y * w
                for x in range(x0, x1):
                    s += buf[row + x]
                    cnt += 1
            out[oy * ow + ox] = s // max(1, cnt)
    return out


def coverage_from(lum, alpha, threshold, background, bg_lum=None):
    n = len(lum)
    cov = bytearray(n)
    shade = bytearray(n)
    if background == 'auto':
        if any(a < 250 for a in alpha):
            background = 'alpha'
        elif bg_lum is not None:
            # arka plan koyuysa (bg_lum dusuk) -> acik ikonu doldur (dark modu)
            # arka plan acikken -> koyu ikonu doldur (light modu)
            background = 'dark' if bg_lum < 128 else 'light'
        else:
            background = 'dark'
    span = max(1, 255 - threshold)
    for k in range(n):
        if background == 'alpha':
            cov[k] = alpha[k]
            shade[k] = lum[k]
        elif background == 'dark':
            cov[k] = 255 if lum[k] > threshold else 0
            shade[k] = int(max(0.0, min(1.0, (lum[k] - threshold) / span)) * 255)
        else:
            cov[k] = 255 if lum[k] < (256 - threshold) else 0
            shade[k] = int(max(0.0, min(1.0, (255 - lum[k]) / span)) * 255)
    return cov, shade, background


def tint_ramp(tint, steps):
    if isinstance(tint[0], (list, tuple)):
        c0, c1 = tint[0], tint[1]
    else:
        c1 = tint
        c0 = [int(v * 0.30) for v in tint]
    ramp = []
    for i in range(steps):
        t = i / (steps - 1) if steps > 1 else 1.0
        ramp.append(tuple(int(c0[j] + (c1[j] - c0[j]) * t) for j in range(3)))
    return ramp


def build_indexed(shade, cov, base, span, threshold, outline, size):
    idx = bytearray(size * size)
    for k in range(size * size):
        if cov[k] < max(1, threshold):
            idx[k] = 0
            continue
        idx[k] = base + min(span - 1, (shade[k] * span) // 256)
    if outline:
        src = bytes(idx)
        for y in range(size):
            for x in range(size):
                p = y * size + x
                if src[p] == 0:
                    continue
                edge = False
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if nx < 0 or ny < 0 or nx >= size or ny >= size:
                        edge = True
                    elif src[ny * size + nx] == 0:
                        edge = True
                if edge:
                    idx[p] = base
    return idx


def make_palette(ramp, base, pool):
    pal = bytearray(1024)
    pal[0:4] = bytes([0, 255, 0, 0])
    for k in range(pool):
        i = base + 1 + k
        if i > 255:
            break
        c = ramp[min(len(ramp) - 1, k)]
        off = i * 4
        pal[off:off + 4] = bytes([c[2] & 255, c[1] & 255, c[0] & 255, 0])
    return bytes(pal)


def build_bam(size, idx, pal):
    frame_off = 0x18
    pal_off = frame_off + 12 + 4
    lut_off = pal_off + 1024
    data_off = lut_off + 2
    hdr = b'BAM ' + b'V1  '
    hdr += struct.pack('<H', 1)
    hdr += struct.pack('<B', 1)
    hdr += struct.pack('<B', 0)
    hdr += struct.pack('<I', frame_off)
    hdr += struct.pack('<I', pal_off)
    hdr += struct.pack('<I', lut_off)
    fe = struct.pack('<HHhhI', size, size, 0, size, data_off | 0x80000000)
    cy = struct.pack('<HH', 1, 0)
    lut = struct.pack('<H', 0)
    return hdr + fe + cy + pal + lut + bytes(idx)


def wrap_bamc(bam):
    return b'BAMC' + b'V1  ' + struct.pack('<I', len(bam)) + zlib.compress(bam, 9)


def cmd_make(args):
    cfg = json.load(open(args.config, encoding='utf-8'))
    out_dir = cfg['out_dir']
    fmt = cfg.get('format', 'bamc').lower()
    size = cfg.get('size', 13)
    threshold = cfg.get('threshold', 28)
    steps = min(cfg.get('steps', 64), 255)
    base = cfg.get('palette_base', 182)
    pool = cfg.get('palette_pool', 64)
    if base + pool > 256:
        raise SystemExit("palette_base + palette_pool <= 256 olmali")
    background = cfg.get('background', 'auto')
    outline = cfg.get('outline', False)
    default_tint = cfg.get('tint', [255, 180, 60])
    os.makedirs(out_dir, exist_ok=True)
    mapping = []
    for icon in cfg['icons']:
        w, h, lum_full, alpha_full = load_pixels(icon['png'])
        bg_lum = None
        if background == 'auto':
            w2, h2, rgb2 = _rgb_of(icon['png'])
            _, bg_lum = detect_background(w2, h2, rgb2, alpha_full)
        lum = box_downscale(w, h, lum_full, size, size)
        alpha = box_downscale(w, h, alpha_full, size, size)
        cov, shade, bg = coverage_from(lum, alpha, threshold, background, bg_lum)
        ramp = tint_ramp(icon.get('tint', default_tint), steps)
        span = min(steps, pool)
        idx = build_indexed(shade, cov, base, span, threshold, outline, size)
        pal = make_palette(ramp, base, pool)
        bam = build_bam(size, idx, pal)
        data = wrap_bamc(bam) if fmt == 'bamc' else bam
        path = os.path.join(out_dir, icon['name'] + '.' + fmt)
        open(path, 'wb').write(data)
        visible = sum(1 for v in idx if v)
        print("%-12s %-4s %5d B  (%d dolu px, %dx%d, bg=%s)" %
              (icon['name'], fmt, len(data), visible, w, h, bg))
        if 'index' in icon:
            mapping.append((icon['index'], icon['name'], icon.get('strRef', '')))
    if mapping:
        mp = os.path.join(out_dir, 'bam_icons.txt')
        with open(mp, 'w') as f:
            for index, name, strref in mapping:
                f.write("%s\t%s\t%s\n" % (index, name, strref))
        print("esleme:", mp)
    print("cikti:", out_dir)


def parse_bam(d):
    if d[:4] == b'BAMC':
        size = struct.unpack_from('<I', d, 8)[0]
        d = zlib.decompress(d[12:12 + size])
    if d[:8] != b'BAM V1  ':
        raise SystemExit("BAM V1/BAMC degil")
    frame_cnt = struct.unpack_from('<H', d, 8)[0]
    cycle_cnt = d[0x0a]
    comp = d[0x0b]
    frame_off, pal_off, lut_off = struct.unpack_from('<III', d, 0x0c)
    frames = []
    for i in range(frame_cnt):
        w, h, x, y, do = struct.unpack_from('<HHhhI', d, frame_off + i * 12)
        frames.append((w, h, x, y, do & 0x7fffffff, bool(do >> 31)))
    cycles = []
    for i in range(cycle_cnt):
        c, l = struct.unpack_from('<HH', d, frame_off + frame_cnt * 12 + i * 4)
        cycles.append((c, l))
    return frame_cnt, cycle_cnt, comp, frames, cycles


def cmd_info(args):
    for path in args.bams:
        d = open(path, 'rb').read()
        frame_cnt, cycle_cnt, comp, frames, cycles = parse_bam(d)
        print("%s: %d frame, %d cycle, comp=%d, %d B" %
              (os.path.basename(path), frame_cnt, cycle_cnt, comp, len(d)))
        for i, (w, h, x, y, off, unc) in enumerate(frames[:args.frames]):
            print("  frame %d: %dx%d centre=(%d,%d) %s off=0x%x" %
                  (i, w, h, x, y, "raw" if unc else "rle", off))
        if args.cycles:
            for i, (c, l) in enumerate(cycles):
                print("  cycle %d: cnt=%d lut=%d" % (i, c, l))

def _download(url, dest):
    import urllib.request
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (bam_icon; +https://github.com/NightBreather)'})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    if not data:
        raise SystemExit("indirilemedi: %s" % url)
    with open(dest, 'wb') as f:
        f.write(data)
    return dest


def cmd_fetch(args):
    """URL'den gorsel(ler) indirip dogrudan BAM'a cevirir.

    Kullanim:
      bam_icon.py fetch --out game-work/chosen/icons --name CHFURYI \
          --tint 255,120,30 https://ornek.com/flame.png
      bam_icon.py fetch --out out --name X --tint 40,160,255 \
          --index 213 --size 13 --format bam URL
    """
    os.makedirs(args.out, exist_ok=True)
    tmpdir = os.path.join(args.out, '.fetch_tmp')
    os.makedirs(tmpdir, exist_ok=True)
    names = args.name or []
    if args.name and len(args.name) == 1 and len(args.urls) > 1:
        names = None
    entries = []
    for i, url in enumerate(args.urls):
        base = os.path.basename(url.split('?')[0]) or ('img%d' % i)
        base = ''.join(c if c.isalnum() or c in '._-' else '_' for c in base)
        local = os.path.join(tmpdir, base)
        _download(url, local)
        name = names[i] if names and i < len(names) else os.path.splitext(base)[0]
        entry = {"name": name.upper(), "png": local}
        if args.index is not None:
            entry["index"] = args.index + i
        if args.tint:
            if ':' in args.tint or ';' in args.tint:
                parts = args.tint.replace(';', ':').split(':')
                entry["tint"] = [[int(v) for v in p.split(',')] for p in parts]
            else:
                entry["tint"] = [int(v) for v in args.tint.split(',')]
        entries.append(entry)
    cfg = {
        "out_dir": args.out,
        "format": args.format,
        "size": args.size,
        "threshold": args.threshold,
        "background": args.background,
        "outline": args.outline,
        "icons": entries,
    }
    cfg_path = os.path.join(tmpdir, 'fetch.json')
    with open(cfg_path, 'w') as f:
        json.dump(cfg, f, indent=2)
    cmd_make(argparse.Namespace(config=cfg_path))


def _game_icons_repo(cache_dir=None, use_git=True):
    """game-icons.net ikon listesini dondurur: [[yazar, ad, dosya_yolu], ...].

    Kota sorunu olmadigi icin (git clone) tercih edilen yontem. Depoyu
    ~/.cache/bam_icon/game-icons icine sparse olarak bir kez klonlar.
    use_git=False ise GitHub API'yi dener.
    """
    import json
    import subprocess
    import time
    if cache_dir is None:
        cache_dir = os.path.join(os.path.expanduser('~'), '.cache', 'bam_icon')
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, 'icons.json')
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 30 * 86400:
        return json.load(open(cache, encoding='utf-8'))
    out = []
    if use_git and shutil_which('git'):
        repo = os.path.join(cache_dir, 'game-icons')
        if not os.path.isdir(os.path.join(repo, '.git')):
            subprocess.run(['git', 'clone', '--depth', '1', '--filter=blob:none',
                            '--sparse', 'https://github.com/game-icons/icons.git', repo],
                           capture_output=True)
        if os.path.isdir(os.path.join(repo, '.git')):
            subprocess.run(['git', 'sparse-checkout', 'set', '--no-cone', '*/'],
                           cwd=repo, capture_output=True)
            for root, dirs, files in os.walk(repo):
                if '.git' in root.split(os.sep):
                    continue
                for fn in files:
                    if fn.endswith('.svg'):
                        rel = os.path.relpath(os.path.join(root, fn), repo)
                        parts = rel.split(os.sep)
                        author = parts[0] if len(parts) > 1 else ''
                        url = ('https://raw.githubusercontent.com/game-icons/icons/'
                               'master/' + rel.replace(os.sep, '/'))
                        out.append([author, fn[:-4], url])
    if not out:
        out = _github_icon_list(cache_dir)
    if out:
        with open(cache, 'w', encoding='utf-8') as f:
            json.dump(out, f)
    return out


def shutil_which(name):
    import shutil
    return shutil.which(name)


def _github_icon_list(cache_dir=None):
    """GitHub API alternatifi (kota dolunca calismaz)."""
    import urllib.request
    import json
    api = 'https://api.github.com/repos/game-icons/icons/contents/'
    req = urllib.request.Request(api, headers={'User-Agent': 'bam_icon'})
    dirs = [x['name'] for x in json.load(urllib.request.urlopen(req, timeout=60))
            if x['type'] == 'dir' and x['name'] not in ('badges', '.github')]
    out = []
    for d in dirs:
        req = urllib.request.Request(api + d, headers={'User-Agent': 'bam_icon'})
        try:
            items = json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            continue
        for it in items:
            if it['name'].endswith('.svg'):
                out.append([d, it['name'][:-4], it['download_url']])
    return out


def cmd_search(args):
    """game-icons.net'te terimle ikon arar (ad icinde gecen)."""
    icons = _game_icons_repo()
    terms = [t.lower() for t in args.terms]
    hits = []
    for author, name, url in icons:
        low = name.lower()
        if all(t in low for t in terms):
            hits.append((author, name, url))
    if args.author:
        hits = [h for h in hits if h[0] == args.author]
    if args.separator:
        hits = [h for h in hits if h[1] == args.separator]
    if args.list or not args.out or not args.name:
        for author, name, url in hits[:args.limit]:
            print("%-14s %s" % (author, name))
        print("toplam %d eslesme" % len(hits))
        if not args.list and (not args.out or not args.name):
            print("(indirmek icin --out ve --name ver)")
            return
        if args.list:
            return
    if not hits:
        raise SystemExit("eslesme yok: %s" % ' '.join(args.terms))
    tmp = os.path.join(args.out, '.search_tmp')
    os.makedirs(tmp, exist_ok=True)
    entries = []
    for i, (author, name, url) in enumerate(hits[:args.limit]):
        dest = os.path.join(tmp, name + '.svg')
        _download(url, dest)
        if args.render:
            png = os.path.join(tmp, name + '.png')
            _svg_to_png(dest, png, args.render_size)
            dest = png
        nameout = (args.name + ('_%02d' % i if len(hits[:args.limit]) > 1 else '')).upper()
        entry = {"name": nameout, "png": dest}
        if args.index is not None:
            entry["index"] = args.index + i
        if args.tint:
            entry["tint"] = _parse_tint(args.tint)
        entries.append(entry)
    cfg = {
        "out_dir": args.out,
        "format": args.format,
        "size": args.size,
        "threshold": args.threshold,
        "background": args.background,
        "outline": args.outline,
        "icons": entries,
    }
    cfg_path = os.path.join(tmp, 'search.json')
    with open(cfg_path, 'w') as f:
        json.dump(cfg, f, indent=2)
    cmd_make(argparse.Namespace(config=cfg_path))


def _svg_to_png(svg_path, png_path, size):
    import svgrender
    w, h, rgb, alpha = svgrender.rasterize(open(svg_path, encoding='utf-8',
                                                 errors='replace').read(), size)
    _write_rgba_png(png_path, w, h, rgb, alpha)
    return png_path


def _write_rgba_png(path, w, h, rgb, alpha):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            k = y * w + x
            raw += bytes([rgb[k * 3], rgb[k * 3 + 1], rgb[k * 3 + 2], alpha[k]])

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    png += chunk(b'IEND', b'')
    open(path, 'wb').write(png)


def _parse_tint(s):
    if ':' in s or ';' in s:
        return [[int(v) for v in p.split(',')] for p in s.replace(';', ':').split(':')]
    return [int(v) for v in s.split(',')]


def main():
    ap = argparse.ArgumentParser(description="BGEE BAM ikon uretici")
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('make', help="JSON'dan BAM ikon(lar) uret")
    m.add_argument('config')
    m.set_defaults(func=cmd_make)
    f = sub.add_parser('fetch', help='URL indir + BAM uret')
    f.add_argument('urls', nargs='+')
    f.add_argument('--out', required=True, help='cikti klasoru')
    f.add_argument('--name', action='append', help='BAM adi (tekrarlanabilir)')
    f.add_argument('--index', type=int, help='ilk STATDESC satiri')
    f.add_argument('--tint', help='R,G,B veya koyu:R,G,B:parlak:R,G,B')
    f.add_argument('--size', type=int, default=13)
    f.add_argument('--format', default='bamc', choices=['bam', 'bamc'])
    f.add_argument('--threshold', type=int, default=28)
    f.add_argument('--background', default='auto',
                   choices=['auto', 'alpha', 'dark', 'light'])
    f.add_argument('--outline', action='store_true')
    f.set_defaults(func=cmd_fetch)
    s = sub.add_parser('search', help='game-icons.net terimle ara (+indir)')
    s.add_argument('terms', nargs='+')
    s.add_argument('--list', action='store_true', help='sadece listele')
    s.add_argument('--author', help='yazara gore filtrele')
    s.add_argument('--separator', help='tam ikon adina gore sec')
    s.add_argument('--out', help='indirilecek klasor')
    s.add_argument('--name', help='BAM adi oneki')
    s.add_argument('--index', type=int, help='ilk STATDESC satiri')
    s.add_argument('--tint', help='R,G,B veya koyu:R,G,B:parlak:R,G,B')
    s.add_argument('--limit', type=int, default=8)
    s.add_argument('--render', action='store_true', help='SVG -> PNG cevir')
    s.add_argument('--render-size', type=int, default=512)
    s.add_argument('--size', type=int, default=13)
    s.add_argument('--format', default='bamc', choices=['bam', 'bamc'])
    s.add_argument('--threshold', type=int, default=28)
    s.add_argument('--background', default='auto',
                   choices=['auto', 'alpha', 'dark', 'light'])
    s.add_argument('--outline', action='store_true')
    s.set_defaults(func=cmd_search)
    n = sub.add_parser('info', help='BAM yapisini yazdir')
    n.add_argument('bams', nargs='+')
    n.add_argument('--frames', type=int, default=4)
    n.add_argument('--cycles', action='store_true')
    n.set_defaults(func=cmd_info)
    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
