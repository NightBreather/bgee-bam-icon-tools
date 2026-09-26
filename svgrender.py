#!/usr/bin/env python3
"""Basit SVG -> raster (RGBA) cozucu (saf Python, harici arac yok).

Desteklenen: <path> (M/L/H/V/C/S/Q/T/A/Z, mutlak+bagil), <circle>, <ellipse>,
<rect>, <polygon>, <polyline>, <line>; fill, fill-rule (nonzero/evenodd),
transform: translate/scale/matrix/rotate.

Doldurma: tarama cizgisi (scanline) + nonzero/evenodd winding. Kontur (stroke)
yok sayilir; game-icons.net tarzi dolu ikonlarda gerekmez.

rasterize(svg_text, out_w, out_h=None, bg=None) -> (w, h, rgb, alpha)
  bg None  -> seffaf
  bg (r,g,b) -> bu renkle doldurulur
"""
import math
import re

NUM = r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?'


class Image:
    def __init__(self, w, h, bg=None):
        self.w = w
        self.h = h
        self.r = [0] * (w * h)
        self.g = [0] * (w * h)
        self.b = [0] * (w * h)
        self.a = [0] * (w * h)
        if bg is not None:
            for i in range(w * h):
                self.r[i], self.g[i], self.b[i], self.a[i] = bg[0], bg[1], bg[2], 255

    def blend(self, x, y, r, g, b, cov):
        if cov <= 0 or x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        i = y * self.w + x
        sa = min(255, max(0, cov))
        da = self.a[i]
        out_a = sa + da * (255 - sa) // 255
        if out_a <= 0:
            return
        for idx, sc in ((0, r), (1, g), (2, b)):
            dc = (self.r, self.g, self.b)[idx][i]
            nc = (sc * sa + dc * da * (255 - sa) // 255) // out_a
            self.r[i] if idx == 0 else (self.g if idx == 1 else self.b)
            if idx == 0:
                self.r[i] = min(255, max(0, nc))
            elif idx == 1:
                self.g[i] = min(255, max(0, nc))
            else:
                self.b[i] = min(255, max(0, nc))
        self.a[i] = min(255, out_a)


def parse_color(s):
    s = s.strip().lower()
    if s in ('none', 'transparent', ''):
        return None
    if s.startswith('#'):
        h = s[1:]
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        if len(h) == 8:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.match(r'rgba?\(([^)]+)\)', s)
    if m:
        parts = re.split(r'[,\s/]+', m.group(1).strip())
        try:
            vals = []
            for p in parts:
                if p.endswith('%'):
                    vals.append(int(float(p[:-1]) * 2.55))
                else:
                    vals.append(int(float(p)))
            if len(vals) >= 3:
                return (vals[0], vals[1], vals[2])
        except ValueError:
            return None
    named = {
        'black': (0, 0, 0), 'white': (255, 255, 255), 'red': (255, 0, 0),
        'green': (0, 128, 0), 'blue': (0, 0, 255), 'gray': (128, 128, 128),
        'grey': (128, 128, 128), 'yellow': (255, 255, 0), 'orange': (255, 165, 0),
        'purple': (128, 0, 128), 'silver': (192, 192, 192),
        'currentcolor': (0, 0, 0),
    }
    return named.get(s)


# ---------------------------------------------------------------- path
class Tokenizer:
    def __init__(self, d):
        self.d = d
        self.i = 0

    def skip(self):
        while self.i < len(self.d) and self.d[self.i] in ' \t\r\n,':
            self.i += 1

    def peek(self):
        self.skip()
        return self.d[self.i] if self.i < len(self.d) else ''

    def num(self):
        self.skip()
        m = re.match(NUM, self.d[self.i:])
        if not m:
            return None
        self.i += m.end()
        return float(m.group())

    def flag(self):
        self.skip()
        if self.i < len(self.d) and self.d[self.i] in '01':
            v = self.d[self.i] == '1'
            self.i += 1
            return v
        return None


def flatten_path(d, flat=0.4, maxseg=64):
    """SVG path -> kapali alt-yollar listesi [(x,y), ...] (mutlak koord)."""
    tk = Tokenizer(d)
    subs = []
    cur = None
    start = None
    x = y = 0.0
    prev_ctrl = None
    cmd = None
    while True:
        c = tk.peek()
        if c == '':
            break
        if c.isalpha():
            cmd = c
            tk.i += 1
            if cmd in 'Zz':
                if cur and len(cur) > 1:
                    if cur[0] != cur[-1]:
                        cur.append(cur[0])
                    subs.append(cur)
                cur = [] if cur else None
                x, y = start if start else (x, y)
                prev_ctrl = None
                continue
            continue
        rel = cmd.islower() if cmd else False
        C = (cmd or 'L').upper()

        def pt(nx, ny):
            return (x + nx, y + ny) if rel else (nx, ny)

        if C == 'M':
            nx, ny = tk.num(), tk.num()
            px, py = pt(nx, ny)
            if cur and len(cur) > 1:
                subs.append(cur)
            cur = [(px, py)]
            x, y = px, py
            start = (px, py)
            cmd = 'l' if rel else 'L'
            prev_ctrl = None
        elif C == 'L':
            nx, ny = tk.num(), tk.num()
            x, y = pt(nx, ny)
            cur.append((x, y))
            prev_ctrl = None
        elif C == 'H':
            nx = tk.num()
            x = x + nx if rel else nx
            cur.append((x, y))
            prev_ctrl = None
        elif C == 'V':
            ny = tk.num()
            y = y + ny if rel else ny
            cur.append((x, y))
            prev_ctrl = None
        elif C in ('C', 'S'):
            if C == 'C':
                x1, y1 = pt(tk.num(), tk.num())
            else:
                if prev_ctrl:
                    x1 = 2 * x - prev_ctrl[0]
                    y1 = 2 * y - prev_ctrl[1]
                else:
                    x1, y1 = x, y
            x2, y2 = pt(tk.num(), tk.num())
            nx, ny = pt(tk.num(), tk.num())
            _cubic(cur, x, y, x1, y1, x2, y2, nx, ny, flat, maxseg)
            prev_ctrl = (x2, y2)
            x, y = nx, ny
        elif C in ('Q', 'T'):
            if C == 'Q':
                x1, y1 = pt(tk.num(), tk.num())
            else:
                if prev_ctrl:
                    x1 = 2 * x - prev_ctrl[0]
                    y1 = 2 * y - prev_ctrl[1]
                else:
                    x1, y1 = x, y
            nx, ny = pt(tk.num(), tk.num())
            _quad(cur, x, y, x1, y1, nx, ny, flat, maxseg)
            prev_ctrl = (x1, y1)
            x, y = nx, ny
        elif C == 'A':
            rx, ry = tk.num(), tk.num()
            rot = tk.num()
            laf = tk.flag()
            sf = tk.flag()
            nx, ny = tk.num(), tk.num()
            ex, ey = pt(nx, ny)
            _arc(cur, x, y, rx, ry, rot, laf, sf, ex, ey, flat, maxseg)
            x, y = ex, ey
            prev_ctrl = None
        else:
            break
    if cur and len(cur) > 1:
        if cur[0] != cur[-1]:
            cur.append(cur[0])
        subs.append(cur)
    return subs


def _cubic(cur, x0, y0, x1, y1, x2, y2, x3, y3, flat, maxseg):
    approx = (abs(x1 - x0) + abs(y1 - y0) + abs(x2 - x1) + abs(y2 - y1) +
              abs(x3 - x2) + abs(y3 - y2))
    n = max(2, min(maxseg, int(approx / max(flat, 0.01)) * 2))
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        a = mt ** 3
        b = 3 * mt * mt * t
        c = 3 * mt * t * t
        dd = t ** 3
        cur.append((a * x0 + b * x1 + c * x2 + dd * x3,
                    a * y0 + b * y1 + c * y2 + dd * y3))


def _quad(cur, x0, y0, x1, y1, x2, y2, flat, maxseg):
    approx = abs(x1 - x0) + abs(y1 - y0) + abs(x2 - x1) + abs(y2 - y1)
    n = max(2, min(maxseg, int(approx / max(flat, 0.01)) * 2))
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        cur.append((mt * mt * x0 + 2 * mt * t * x1 + t * t * x2,
                    mt * mt * y0 + 2 * mt * t * y1 + t * t * y2))


def _arc(cur, x0, y0, rx, ry, rot, laf, sf, x1, y1, flat, maxseg):
    if rx == 0 or ry == 0:
        cur.append((x1, y1))
        return
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(rot)
    cosp, sinp = math.cos(phi), math.sin(phi)
    dx = (x0 - x1) / 2
    dy = (y0 - y1) / 2
    x1p = cosp * dx + sinp * dy
    y1p = -sinp * dx + cosp * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    c = math.sqrt(max(0, num / den)) if den else 0
    if laf == sf:
        c = -c
    cxp = c * rx * y1p / ry
    cyp = -c * ry * x1p / rx
    cx = cosp * cxp - sinp * cyp + (x0 + x1) / 2
    cy = sinp * cxp + cosp * cyp + (y0 + y1) / 2

    def ang(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        n = math.hypot(ux, uy) * math.hypot(vx, vy)
        if n == 0:
            return 0
        a = math.acos(max(-1, min(1, dot / n)))
        return -a if (ux * vy - uy * vx) < 0 else a

    th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry,
              (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sf and dth > 0:
        dth -= 2 * math.pi
    elif sf and dth < 0:
        dth += 2 * math.pi
    seg = max(4, min(maxseg, int(abs(dth) * max(rx, ry) / max(flat, 0.05))))
    for i in range(1, seg + 1):
        t = th1 + dth * i / seg
        px = cosp * rx * math.cos(t) - sinp * ry * math.sin(t) + cx
        py = sinp * rx * math.cos(t) + cosp * ry * math.sin(t) + cy
        cur.append((px, py))


# ---------------------------------------------------------------- transform
def parse_transform(s):
    m = re.findall(r'(\w+)\s*\(([^)]*)\)', s or '')
    mat = (1, 0, 0, 1, 0, 0)

    def mul(a, b):
        return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
                a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
                a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])

    for name, arg in m:
        v = [float(t) for t in re.split(r'[,\s]+', arg.strip()) if t]
        if name == 'translate':
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == 'scale':
            sx = v[0]
            sy = v[1] if len(v) > 1 else sx
            t = (sx, 0, 0, sy, 0, 0)
        elif name == 'matrix':
            t = tuple(v[:6])
        elif name == 'rotate':
            a = math.radians(v[0])
            ca, sa = math.cos(a), math.sin(a)
            t = (ca, sa, -sa, ca, 0, 0)
            if len(v) >= 3:
                t = mul((1, 0, 0, 1, v[1], v[2]), mul(t, (1, 0, 0, 1, -v[1], -v[2])))
        elif name == 'skewX':
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == 'skewY':
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        mat = mul(mat, t)
    return mat


def apply_mat(mat, pts):
    a, b, c, d, e, f = mat
    return [(a * x + c * y + e, b * x + d * y + f) for (x, y) in pts]


# ---------------------------------------------------------------- fill
def fill_polygon(img, rings, color, evenodd=False):
    r, g, b = color
    if not rings:
        return
    ymin = min(p[1] for ring in rings for p in ring)
    ymax = max(p[1] for ring in rings for p in ring)
    y0 = max(0, int(math.floor(ymin)))
    y1 = min(img.h - 1, int(math.ceil(ymax)))
    # tum kenarlar
    edges = []
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, yy1 = ring[i]
            x2, yy2 = ring[(i + 1) % n]
            if yy1 != yy2:
                edges.append((x1, yy1, x2, yy2))
    for py in range(y0, y1 + 1):
        yc = py + 0.5
        xs = []
        for (x1, yy1, x2, yy2) in edges:
            if (yy1 <= yc < yy2) or (yy2 <= yc < yy1):
                t = (yc - yy1) / (yy2 - yy1)
                xs.append(x1 + t * (x2 - x1))
        if not xs:
            continue
        xs.sort()
        if evenodd:
            for i in range(0, len(xs) - 1, 2):
                _span(img, xs[i], xs[i + 1], py, r, g, b)
        else:
            _span_winding(img, edges, xs, py, r, g, b)


def _span(img, xa, xb, y, r, g, b):
    x_start = max(0, int(math.floor(xa)))
    x_end = min(img.w - 1, int(math.ceil(xb)) - 1)
    for px in range(x_start, x_end + 1):
        cov = _coverage(xa, xb, px)
        if cov > 0:
            img.blend(px, y, r, g, b, cov)


def _coverage(xa, xb, px):
    left = max(xa, px - 0.0)
    right = min(xb, px + 1.0)
    c = right - left
    if c <= 0:
        return 0
    # basit kenar yumusatma
    return int(min(1.0, c) * 255)


def _span_winding(img, edges, xs, y, r, g, b):
    yc = y + 0.5
    # her kesiste kenarin yonunu hesapla
    w = 0
    prev = None
    # nonzero: winding sayisi
    cross = []
    for (x1, yy1, x2, yy2) in edges:
        if (yy1 <= yc < yy2) or (yy2 <= yc < yy1):
            t = (yc - yy1) / (yy2 - yy1)
            xx = x1 + t * (x2 - x1)
            dirn = 1 if yy2 > yy1 else -1
            cross.append((xx, dirn))
    cross.sort()
    wind = 0
    start = 0.0
    for (xx, dirn) in cross:
        prev_wind = wind
        wind += dirn
        if prev_wind == 0 and wind != 0:
            start = xx
        elif prev_wind != 0 and wind == 0:
            _span(img, start, xx, y, r, g, b)


# ---------------------------------------------------------------- tag parse
TAG_RE = re.compile(r'<(\w+)([^>]*?)/?>', re.S)
ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')


def parse_attrs(s):
    return {k: v for k, v in ATTR_RE.findall(s)}


def rasterize(svg_text, out_w, out_h=None, bg=None, skip_full_canvas=True,
              icon_fill=None):
    """SVG'yi rasterize eder.

    skip_full_canvas: viewBox'i neredeyse tamamen kaplayan ve tek renkli olan
                      "arka plan" path'lerini atlar (game-icons.net'te
                      ffffff/000000 varyantinda ilk path siyah zemindir).
    icon_fill       : yalnizca bu renkteki path'leri cizer (ornek: (255,255,255)
                      ise beyaz ikon; digerleri yok sayilir).
    """
    vb = re.search(r'viewBox\s*=\s*"([^"]*)"', svg_text)
    if vb:
        vbvals = [float(v) for v in re.split(r'[ ,]+', vb.group(1).strip()) if v]
        vx, vy, vw, vh = vbvals
    else:
        m = re.search(r'width\s*=\s*"([\d.]+)', svg_text)
        mh = re.search(r'height\s*=\s*"([\d.]+)', svg_text)
        vx = vy = 0
        vw = float(m.group(1)) if m else 100
        vh = float(mh.group(1)) if mh else vw
    if out_h is None:
        out_h = out_w
    base_mat = (out_w / vw, 0, 0, out_h / vh, -vx * out_w / vw, -vy * out_h / vh)

    img = Image(out_w, out_h, bg)
    inher_fill = (0, 0, 0)
    inher_rule = 'nonzero'

    parsed = []
    for m in TAG_RE.finditer(svg_text):
        tag = m.group(1).lower()
        attrs = parse_attrs(m.group(2))
        if tag == 'g':
            if 'fill' in attrs:
                fc = parse_color(attrs['fill'])
                if fc is not None:
                    inher_fill = fc
            if 'fill-rule' in attrs:
                inher_rule = attrs['fill-rule']
            continue
        fill = parse_color(attrs.get('fill', '')) if 'fill' in attrs else inher_fill
        if 'fill' in attrs and attrs.get('fill', '').startswith('url'):
            fill = inher_fill
        rule = attrs.get('fill-rule', inher_rule)
        style = attrs.get('style', '')
        if style:
            sm = re.search(r'fill\s*:\s*([^;]+)', style)
            if sm:
                fc = parse_color(sm.group(1))
                if fc is not None:
                    fill = fc
            rm = re.search(r'fill-rule\s*:\s*([^;]+)', style)
            if rm:
                rule = rm.group(1).strip()
        mat = base_mat
        if 'transform' in attrs:
            mat = _mul_tuple(parse_transform(attrs['transform']), base_mat)
        rings = []
        if tag == 'path' and 'd' in attrs:
            rings = flatten_path(attrs['d'])
        elif tag == 'circle':
            cx, cy = float(attrs.get('cx', 0)), float(attrs.get('cy', 0))
            r = float(attrs.get('r', 0))
            rings = [_ellipse_ring(cx, cy, r, r)]
        elif tag == 'ellipse':
            cx, cy = float(attrs.get('cx', 0)), float(attrs.get('cy', 0))
            rx, ry = float(attrs.get('rx', 0)), float(attrs.get('ry', 0))
            rings = [_ellipse_ring(cx, cy, rx, ry)]
        elif tag == 'rect':
            x = float(attrs.get('x', 0))
            y = float(attrs.get('y', 0))
            w = float(attrs.get('width', 0))
            h = float(attrs.get('height', 0))
            rings = [[(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]]
        elif tag in ('polygon', 'polyline'):
            nums = [float(t) for t in re.split(r'[,\s]+', attrs.get('points', '').strip()) if t]
            pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
            if tag == 'polygon' and pts:
                pts.append(pts[0])
            rings = [pts]
        elif tag == 'line':
            rings = [[(float(attrs.get('x1', 0)), float(attrs.get('y1', 0))),
                      (float(attrs.get('x2', 0)), float(attrs.get('y2', 0)))]]
        if not rings:
            continue
        rings = [apply_mat(mat, ring) for ring in rings]
        parsed.append((rings, fill, rule))

    # arka plan (tum tuvali kaplayan ilk path) tespiti
    skip_idx = -1
    if skip_full_canvas and len(parsed) > 1:
        r0, f0, _ = parsed[0]
        xs = [p[0] for ring in r0 for p in ring]
        ys = [p[1] for ring in r0 for p in ring]
        if xs and ys:
            cw = max(xs) - min(xs)
            ch = max(ys) - min(ys)
            if cw >= out_w * 0.97 and ch >= out_h * 0.97:
                skip_idx = 0

    for i, (rings, fill, rule) in enumerate(parsed):
        if i == skip_idx:
            continue
        eff = fill
        if icon_fill is not None:
            if fill is None or not _close(fill, icon_fill):
                # beyaz ikon istenirse ve fill belirtilmemisse varsayilan beyaz kalabilir;
                # renkli path'ler de kabul edilir
                if fill is None:
                    eff = icon_fill
                elif not _dominant(inher_fill):
                    continue
        if eff is None:
            continue
        fill_polygon(img, rings, eff, evenodd=(rule == 'evenodd'))
    return _to_bytes(img)


def _close(a, b, tol=40):
    return all(abs(a[i] - b[i]) <= tol for i in range(3))


def _dominant(c):
    return sum(c) > 200


def _ellipse_ring(cx, cy, rx, ry, n=64):
    return [(cx + rx * math.cos(2 * math.pi * i / n),
             cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def _mul_tuple(a, b):
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def _to_bytes(img):
    n = img.w * img.h
    rgb = bytearray(n * 3)
    alpha = bytearray(n)
    for i in range(n):
        rgb[i * 3] = img.r[i]
        rgb[i * 3 + 1] = img.g[i]
        rgb[i * 3 + 2] = img.b[i]
        alpha[i] = img.a[i]
    return img.w, img.h, bytes(rgb), bytes(alpha)


if __name__ == '__main__':
    import sys
    w, h, rgb, a = rasterize(open(sys.argv[1]).read(), 64)
    print(w, h, len(rgb), min(a), max(a))
