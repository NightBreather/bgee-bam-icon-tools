#!/usr/bin/env python3
"""BAM ikon onizlemesi: HTML (etiketli) + PNG tabaka + tek tek buyutulmus PNG.

Kullanim:
  python3 tools/bam_preview.py --config game-work/chosen/icons.json
  python3 tools/bam_preview.py game-work/chosen/icons/CHFURYI.bam ...
"""
import argparse
import base64
import json
import os
import struct
import zlib

SCALE = 12
BG = (24, 24, 32)


def load_bam(path):
    d = open(path, 'rb').read()
    if d[:4] == b'BAMC':
        n = struct.unpack_from('<I', d, 8)[0]
        d = zlib.decompress(d[12:12 + n])
    if d[:8] != b'BAM V1  ':
        raise SystemExit("BAM V1/BAMC degil: %s" % path)
    frame_off, pal_off, lut_off = struct.unpack_from('<III', d, 0x0c)
    w, h, x, y, do = struct.unpack_from('<HHhhI', d, frame_off)
    off = do & 0x7fffffff
    idx = d[off:off + w * h]
    pal = d[pal_off:pal_off + 1024]
    return w, h, idx, pal


def to_rgba(w, h, idx, pal):
    out = bytearray(w * h * 4)
    for k, i in enumerate(idx):
        if i == 0:
            continue
        b, g, r, a = pal[i * 4:i * 4 + 4]
        out[k * 4:k * 4 + 4] = bytes([r, g, b, 255])
    return bytes(out)


def scale(w, h, rgba, f):
    nw, nh = w * f, h * f
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        sy = y // f
        row = sy * w * 4
        for x in range(nw):
            sx = x // f
            k = row + sx * 4
            o = (y * nw + x) * 4
            out[o:o + 4] = rgba[k:k + 4]
    return nw, nh, bytes(out)


def on_bg(w, h, rgba, bg=BG):
    out = bytearray(len(rgba))
    for k in range(w * h):
        if rgba[k * 4 + 3] == 0:
            out[k * 4:k * 4 + 4] = bytes([bg[0], bg[1], bg[2], 255])
        else:
            out[k * 4:k * 4 + 4] = rgba[k * 4:k * 4 + 4]
    return bytes(out)


def png_bytes(w, h, rgba):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * w * 4:(y + 1) * w * 4]

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
            + chunk(b'IEND', b''))


def b64_png(w, h, rgba):
    return base64.b64encode(png_bytes(w, h, rgba)).decode('ascii')


def find_bam(out_dir, name):
    for ext in ('.bam', '.bamc'):
        p = os.path.join(out_dir, name + ext)
        if os.path.exists(p):
            return p
    return None


def render_sheet(cells, path):
    pad, gap = 10, 10
    cw = [c[0] for c in cells]
    ch = [c[1] for c in cells]
    W = pad * 2 + sum(cw) + gap * (len(cells) - 1)
    H = pad * 2 + max(ch)
    canvas = bytearray(W * H * 4)
    for k in range(W * H):
        canvas[k * 4:k * 4 + 4] = bytes([BG[0], BG[1], BG[2], 255])
    x0 = pad
    for (w, h, rgba) in cells:
        for y in range(h):
            for x in range(w):
                s = (y * w + x) * 4
                d = ((pad + y) * W + (x0 + x)) * 4
                canvas[d:d + 4] = rgba[s:s + 4]
        x0 += w + gap
    open(path, 'wb').write(png_bytes(W, H, bytes(canvas)))


def main():
    ap = argparse.ArgumentParser(description="BAM ikon onizlemesi")
    ap.add_argument('bams', nargs='*')
    ap.add_argument('--config', help="icons.json (out_dir + etiketler)")
    ap.add_argument('--out', help="onizleme klasoru (varsayilan: <out_dir>/preview)")
    ap.add_argument('--scale', type=int, default=SCALE)
    args = ap.parse_args()

    entries = []
    if args.config:
        cfg = json.load(open(args.config, encoding='utf-8'))
        out_dir = cfg['out_dir']
        for ic in cfg['icons']:
            p = find_bam(out_dir, ic['name'])
            if p:
                entries.append((ic['name'], ic.get('strRef', ''), p))
    for b in args.bams:
        entries.append((os.path.splitext(os.path.basename(b))[0], '', b))
    if not entries:
        raise SystemExit("BAM bulunamadi")

    out = args.out or (os.path.join(os.path.dirname(entries[0][2]), 'preview'))
    os.makedirs(out, exist_ok=True)

    cells = []
    rows = []
    for name, label, p in entries:
        w, h, idx, pal = load_bam(p)
        rgba = on_bg(w, h, to_rgba(w, h, idx, pal))
        small = b64_png(w, h, rgba)
        big = b64_png(*scale(w, h, rgba, args.scale))
        rows.append((name, label, small, big))
        cw, ch, crgba = scale(w, h, rgba, 10)
        cells.append((cw, ch, crgba))
        open(os.path.join(out, name + '.png'), 'wb').write(png_bytes(cw, ch, crgba))

    render_sheet(cells, os.path.join(out, 'sheet.png'))

    css = ("body{background:#181820;color:#e6e6ee;font-family:sans-serif;margin:16px}"
           ".grid{display:flex;flex-wrap:wrap;gap:18px}"
           ".card{background:#22222c;border:1px solid #33333f;border-radius:8px;padding:10px;width:200px;text-align:center}"
           ".card img{image-rendering:pixelated;display:block;margin:0 auto 6px}"
           ".name{font-weight:700;font-size:13px}"
           ".lbl{color:#9aa;font-size:12px;min-height:16px}")
    html = ["<!doctype html><html><head><meta charset='utf-8'><title>Chosen ikon onizleme</title>",
            "<style>%s</style></head><body>" % css,
            "<h2>Chosen ikon onizleme</h2>",
            "<p>Her kart: ustte %dx (gercek boyut), altta %dx buyutulmus.</p>" % (1, args.scale),
            "<div class='grid'>"]
    for name, label, small, big in rows:
        html.append("<div class='card'>"
                    "<img src='data:image/png;base64,%s' width='13' height='13'>"
                    "<img src='data:image/png;base64,%s' width='%d' height='%d'>"
                    "<div class='name'>%s</div><div class='lbl'>%s</div></div>"
                    % (small, big, 13 * args.scale, 13 * args.scale, name, label))
    html.append("</div></body></html>")
    open(os.path.join(out, 'index.html'), 'w').write('\n'.join(html))

    print("onizleme:", out)
    print("  index.html, sheet.png, %d ikon PNG" % len(rows))


if __name__ == '__main__':
    main()
