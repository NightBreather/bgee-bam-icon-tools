#!/usr/bin/env python3
"""32x32 buyu ikonu uretir: vanilla BAM'dan cikarilan tas zemin + kendi sembolumuz.

Kullanim:
  python3 tools/spell_icon.py --config game-work/chosen/spellicons.json \
      --vanilla-dir /data/data/com.termux/files/usr/tmp/opencode/vanicons \
      --out game-work/chosen/icons
"""
import argparse
import collections
import glob
import json
import math
import os
import struct
import zlib

import imgread
from bam_icon import build_bam


def decode_bam(path):
    raw = open(path, 'rb').read()
    if raw[:4] == b'BAMC':
        n = struct.unpack_from('<I', raw, 8)[0]
        d = zlib.decompress(raw[12:12 + n])
    else:
        d = raw
    trans = d[0x0b]
    fo = struct.unpack_from('<I', d, 0x0c)[0]
    po = struct.unpack_from('<I', d, 0x10)[0]
    w, h, x, y, do = struct.unpack_from('<HHhhI', d, fo)
    off = do & 0x7fffffff
    pal = d[po:po + 1024]
    if (do >> 31) & 1:
        idx = list(d[off:off + w * h])
    else:
        idx = []
        i = off
        while len(idx) < w * h and i < len(d):
            b = d[i]
            i += 1
            if b == trans:
                x2 = d[i]
                i += 1
                idx.extend([trans] * (x2 + 1))
            else:
                idx.append(b)
        idx = idx[:w * h]
    return w, h, pal, idx


def _lum(pal, p):
    b, g, r, a = pal[p * 4:p * 4 + 4]
    return (r * 299 + g * 587 + b * 114) // 1000


def _is_symbol(pal, p):
    b, g, r, a = pal[p * 4:p * 4 + 4]
    lum = (r * 299 + g * 587 + b * 114) // 1000
    sat = max(r, g, b) - min(r, g, b)
    return lum > 70 or sat > 42


def _ring_color(pal, idx, w, h):
    cols = []
    for y in range(h):
        for x in range(w):
            k = y * w + x
            if idx[k] == 0:
                continue
            if x in (0, 1, w - 2, w - 1) or y in (0, 1, h - 2, h - 1):
                b, g, r, a = pal[idx[k] * 4:idx[k] * 4 + 4]
                cols.append((r, g, b))
    if not cols:
        return (34, 34, 30)
    cols.sort(key=lambda c: c[0] * 299 + c[1] * 587 + c[2] * 114)
    m = cols[len(cols) // 2]
    return m


def extract_bg(path, size):
    w, h, pal, idx = decode_bam(path)
    n = w * h
    ring = _ring_color(pal, idx, w, h)

    def sym_pixel(k):
        if idx[k] == 0:
            return False
        b, g, r, a = pal[idx[k] * 4:idx[k] * 4 + 4]
        lum = (r * 299 + g * 587 + b * 114) // 1000
        sat = max(r, g, b) - min(r, g, b)
        dist = max(abs(r - ring[0]), abs(g - ring[1]), abs(b - ring[2]))
        return lum > 64 or sat > 30 or dist > 38

    sym = [sym_pixel(k) for k in range(n)]
    fill = [None] * n
    q = collections.deque()
    for k in range(n):
        if idx[k] != 0 and not sym[k]:
            fill[k] = idx[k]
            q.append(k)
    while q:
        k = q.popleft()
        x = k % w
        y = k // w
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                j = ny * w + nx
                if idx[j] != 0 and fill[j] is None:
                    fill[j] = fill[k]
                    q.append(j)
    minx, miny, maxx, maxy = w, h, -1, -1
    for k in range(n):
        if idx[k] != 0 and fill[k] is not None:
            x = k % w
            y = k // w
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
    if maxx < 0:
        return [[None] * size for _ in range(size)]
    bw = maxx - minx + 1
    bh = maxy - miny + 1
    out = [[None] * size for _ in range(size)]
    for y in range(size):
        fy0 = miny + (y + 0.5) * bh / size - 0.5
        for x in range(size):
            fx0 = minx + (x + 0.5) * bw / size - 0.5
            x0 = math.floor(fx0)
            y0 = math.floor(fy0)
            fx = fx0 - x0
            fy = fy0 - y0
            acc = [0, 0, 0]
            wsum = 0.0
            for dx, dy, wgt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                                (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
                if wgt <= 0:
                    continue
                xx = min(w - 1, max(0, x0 + dx))
                yy = min(h - 1, max(0, y0 + dy))
                k = yy * w + xx
                if idx[k] != 0 and fill[k] is not None:
                    b, g, r, a = pal[fill[k] * 4:fill[k] * 4 + 4]
                    acc[0] += r * wgt
                    acc[1] += g * wgt
                    acc[2] += b * wgt
                    wsum += wgt
            if wsum > 0.45:
                r = int(acc[0] / wsum)
                g = int(acc[1] / wsum)
                b = int(acc[2] / wsum)
                L = (r * 299 + g * 587 + b * 114) // 1000
                out[y][x] = (L, L, L)
    return out


def relight(grid, size, strength, dir_range=0):
    def lum(c):
        return (c[0] * 299 + c[1] * 587 + c[2] * 114) // 1000
    L = [[None] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            c = grid[y][x]
            if c:
                L[y][x] = lum(c)
    out = [[None] * size for _ in range(size)]
    denom = max(1, 2 * (size - 1))
    for y in range(size):
        for x in range(size):
            if not grid[y][x]:
                continue
            h0 = L[y][x]

            def gv(dx, dy):
                nx, ny = x + dx, y + dy
                if 0 <= nx < size and 0 <= ny < size and L[ny][nx] is not None:
                    return L[ny][nx]
                return h0
            emb = ((gv(-1, -1) - gv(1, 1)) + (gv(1, -1) - gv(-1, 1))) // 2
            add = int(emb * strength)
            if dir_range:
                t = (x + y) / denom
                add += int((0.5 - t) * dir_range)
            c = grid[y][x]
            out[y][x] = (max(0, min(255, c[0] + add)),
                         max(0, min(255, c[1] + add)),
                         max(0, min(255, c[2] + add)))
    return out


def texture(grid, size, sigma, seed=0):
    import random
    rnd = random.Random(seed)
    n = [rnd.gauss(0, sigma) for _ in range(size * size)]
    b = [0.0] * (size * size)
    for y in range(size):
        for x in range(size):
            s = 0.0
            c = 0
            for dy in (-1, 0, 1):
                yy = y + dy
                if yy < 0 or yy >= size:
                    continue
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if xx < 0 or xx >= size:
                        continue
                    s += n[yy * size + xx]
                    c += 1
            b[y * size + x] = s / c
    out = [[None] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            cc = grid[y][x]
            if cc is None:
                continue
            L = (cc[0] * 299 + cc[1] * 587 + cc[2] * 114) // 1000
            d = b[y * size + x] * (0.6 + 0.4 * (L / 255.0))
            out[y][x] = (max(0, min(255, int(cc[0] + d))),
                         max(0, min(255, int(cc[1] + d))),
                         max(0, min(255, int(cc[2] + d))))
    return out


def grade(grid, target, size):
    vals = [grid[y][x] for y in range(size) for x in range(size) if grid[y][x]]
    if not vals:
        return grid
    n = len(vals)
    m = (sum(v[0] for v in vals) // n, sum(v[1] for v in vals) // n, sum(v[2] for v in vals) // n)
    d = (target[0] - m[0], target[1] - m[1], target[2] - m[2])
    out = [[None] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            c = grid[y][x]
            if c:
                out[y][x] = (max(0, min(255, c[0] + d[0])),
                             max(0, min(255, c[1] + d[1])),
                             max(0, min(255, c[2] + d[2])))
    return out


def average_bg(paths, size):
    acc = [[[0, 0, 0, 0] for _ in range(size)] for _ in range(size)]
    for p in paths:
        g = extract_bg(p, size)
        for y in range(size):
            for x in range(size):
                c = g[y][x]
                if c:
                    acc[y][x][0] += c[0]
                    acc[y][x][1] += c[1]
                    acc[y][x][2] += c[2]
                    acc[y][x][3] += 1
    out = [[None] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            a = acc[y][x]
            if a[3]:
                out[y][x] = (a[0] // a[3], a[1] // a[3], a[2] // a[3])
    return out


def mask_full(w, h, rgb, alpha):
    if min(alpha) >= 250:
        lums = [(rgb[k * 3] * 299 + rgb[k * 3 + 1] * 587 + rgb[k * 3 + 2] * 114) // 1000
                for k in range(w * h)]
        bd = [lums[k] for k in range(w * h)
              if (k % w in (0, 1, w - 2, w - 1) or k // w in (0, 1, h - 2, h - 1))]
        bl = sum(bd) // max(1, len(bd))
        return bytearray(255 if (lums[k] > bl + 55 if bl < 128 else lums[k] < bl - 55) else 0
                         for k in range(w * h))
    return bytearray(alpha)


def dscale(w, h, buf, ow, oh):
    out = bytearray(ow * oh)
    for oy in range(oh):
        y0 = oy * h // oh
        y1 = max(y0 + 1, (oy + 1) * h // oh)
        for ox in range(ow):
            x0 = ox * w // ow
            x1 = max(x0 + 1, (ox + 1) * w // ow)
            s = c = 0
            for y in range(y0, y1):
                r = y * w
                for x in range(x0, x1):
                    s += buf[r + x]
                    c += 1
            out[oy * ow + ox] = s // c
    return out


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _max_box(bg, size):
    c = size // 2
    for r in range(c, 3, -1):
        ok = True
        for y in range(c - r, c + r):
            for x in range(c - r, c + r):
                if bg[y][x] is None:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            return 2 * r
    return size // 2


def compose(bg, art, tint, size, box, margin=4):
    w, h, rgb, alpha = imgread.read_image(art)
    mf = mask_full(w, h, rgb, alpha)
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        row = y * w
        for x in range(w):
            if mf[row + x]:
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
    sm = [[False] * size for _ in range(size)]
    if maxx < 0:
        return [row[:] for row in bg]
    cw = maxx - minx + 1
    ch = maxy - miny + 1
    cm = bytearray(cw * ch)
    for y in range(ch):
        for x in range(cw):
            cm[y * cw + x] = mf[(miny + y) * w + (minx + x)]
    scale0 = box / max(cw, ch)
    nw0 = max(1, int(cw * scale0 + 0.5))
    nh0 = max(1, int(ch * scale0 + 0.5))
    m0 = dscale(cw, ch, cm, nw0, nh0)
    pxs = [x for y in range(size) for x in range(size) if bg[y][x] is not None]
    pys = [y for y in range(size) for x in range(size) if bg[y][x] is not None]
    cx = sum(pxs) / len(pxs) if pxs else (size - 1) / 2.0
    cy = sum(pys) / len(pys) if pys else (size - 1) / 2.0
    fit = None
    for bb in range(box, 5, -1):
        f = bb / float(box)
        nw = max(1, int(nw0 * f + 0.5))
        nh = max(1, int(nh0 * f + 0.5))
        m = m0 if (nw == nw0 and nh == nh0) else dscale(nw0, nh0, m0, nw, nh)
        oxp = max(0, min(size - nw, int(round(cx - nw / 2.0))))
        oyp = max(0, min(size - nh, int(round(cy - nh / 2.0))))
        ok = True
        for y in range(nh):
            for x in range(nw):
                if m[y * nw + x] >= 120 and bg[oyp + y][oxp + x] is None:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            fit = bb
            break
    if fit is None:
        fit = 8
    bb = max(6, fit - margin)
    f = bb / float(box)
    nw = max(1, int(nw0 * f + 0.5))
    nh = max(1, int(nh0 * f + 0.5))
    m = m0 if (nw == nw0 and nh == nh0) else dscale(nw0, nh0, m0, nw, nh)
    oxp = max(0, min(size - nw, int(round(cx - nw / 2.0))))
    oyp = max(0, min(size - nh, int(round(cy - nh / 2.0))))
    for y in range(nh):
        for x in range(nw):
            if m[y * nw + x] >= 120:
                sm[oyp + y][oxp + x] = True
    ys = [y for y in range(size) for x in range(size) if sm[y][x]]
    ymin, ymax = (min(ys), max(ys)) if ys else (0, 1)
    c0, c1 = (tint if isinstance(tint[0], (list, tuple))
              else ([int(v * 0.30) for v in tint], tint))
    out = [row[:] for row in bg]
    for y in range(size):
        for x in range(size):
            if not sm[y][x]:
                continue
            up = not (y > 0 and sm[y - 1][x])
            dn = not (y < size - 1 and sm[y + 1][x])
            le = not (x > 0 and sm[y][x - 1])
            ri = not (x < size - 1 and sm[y][x + 1])
            t = (y - ymin) / max(1, ymax - ymin)
            G = (96, 96, 96)
            if t < 0.5:
                body = lerp(c1, G, t / 0.5)
            else:
                body = lerp(G, c0, (t - 0.5) / 0.5)
            if up or le:
                col = tuple(min(255, int(v * 1.35 + 25)) for v in c1)
            elif dn or ri:
                col = tuple(int(v * 0.55) for v in c0)
            else:
                col = body
            out[y][x] = col
    return out


def write_bam(path, grid, size):
    colors = {}
    for y in range(size):
        for x in range(size):
            c = grid[y][x]
            if c is not None:
                colors.setdefault(c, 0)
    if len(colors) > 255:
        for step in (2, 4, 8, 16):
            colors = {}
            for y in range(size):
                for x in range(size):
                    c = grid[y][x]
                    if c is not None:
                        colors.setdefault(tuple((v // step) * step for v in c), 0)
            if len(colors) <= 255:
                grid = [[None if grid[y][x] is None
                         else tuple((v // step) * step for v in grid[y][x])
                         for x in range(size)] for y in range(size)]
                break
    keys = list(colors.keys())
    pal = bytearray(1024)
    pal[0:4] = bytes([0, 255, 0, 0])
    idxmap = {c: i + 1 for i, c in enumerate(keys)}
    for c, i in idxmap.items():
        pal[i * 4:i * 4 + 4] = bytes([c[2] & 255, c[1] & 255, c[0] & 255, 0])
    idx = bytearray(size * size)
    for y in range(size):
        for x in range(size):
            c = grid[y][x]
            if c is not None:
                idx[y * size + x] = idxmap[c]
    bam = build_bam(size, bytes(idx), bytes(pal))
    open(path, 'wb').write(bam)
    return len(keys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--vanilla-dir', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--size', type=int, default=32)
    ap.add_argument('--box', type=int, default=25)
    ap.add_argument('--margin', type=int, default=4,
                    help='sembol ile plaka kenari arasinda bosluk (px)')
    ap.add_argument('--texture', type=float, default=None,
                    help='zemine eklenecek ince doku (gurultu sigma; or. 13)')
    ap.add_argument('--avg-bg', action='store_true',
                    help='tum vanilla zeminlerin ortalamasini tek zemin olarak kullan')
    ap.add_argument('--tone', help='tum zeminleri bu tona derecelendir: R,G,B')
    ap.add_argument('--relight', type=float, default=None,
                    help='zemine kabartma/isik-golge katsayisi (or. 1.0)')
    ap.add_argument('--dir-range', type=int, default=0,
                    help='sol-ust aydinlik -> sag-alt golge yonlu isik siddeti')
    args = ap.parse_args()
    tone = None
    if args.tone:
        tone = tuple(int(v) for v in args.tone.split(','))

    cfg = json.load(open(args.config, encoding='utf-8'))
    bgs = sorted(glob.glob(os.path.join(args.vanilla_dir, '*.BAM')))
    if not bgs:
        raise SystemExit("vanilla BAM bulunamadi: %s" % args.vanilla_dir)
    cache = {}
    os.makedirs(args.out, exist_ok=True)
    shared = average_bg(bgs, args.size) if args.avg_bg else None
    for i, ic in enumerate(cfg['icons']):
        if shared is not None:
            bg = shared
            tag = 'ORTALAMA'
        else:
            b = None
            if ic.get('bg'):
                want = ic['bg'].lower()
                b = next((p for p in bgs if os.path.basename(p).lower() == want), None)
            if b is None:
                b = bgs[i % len(bgs)]
            if b not in cache:
                g = extract_bg(b, args.size)
                if args.relight is not None:
                    g = relight(g, args.size, args.relight, args.dir_range)
                if args.texture is not None:
                    g = texture(g, args.size, args.texture, seed=i * 7 + 1)
                if tone:
                    g = grade(g, tone, args.size)
                cache[b] = g
            bg = cache[b]
            tag = os.path.basename(b)
        grid = compose(bg, ic['png'], ic.get('tint', [200, 200, 200]), args.size,
                       args.box, ic.get('margin', args.margin))
        ncol = write_bam(os.path.join(args.out, ic['name'] + '.bam'), grid, args.size)
        print("%-10s bg=%-14s renk=%d" % (ic['name'], tag, ncol))
    print("cikti:", args.out)


if __name__ == '__main__':
    main()
