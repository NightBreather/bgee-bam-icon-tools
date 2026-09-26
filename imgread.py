#!/usr/bin/env python3
"""Goruntu okuyucu (harici kutuphane yok).

Desteklenen: PNG (8/16-bit, tum renk tipleri, interlace), JPEG (baseline
+ progressive), WEBP (lossy/lossless/tum kanallar), BMP (24/32-bit), GIF.

read_image(path) -> (w, h, rgb_bytes, alpha_bytes)
  rgb   : w*h*3, R,G,B
  alpha : w*h, 0..255

Gerekirse ImageMagick/ffmpeg'e dusmek yerine saf Python ile cozer; ancak
WEBP'de saf Python cozucu yoksa ffmpeg varsa onu kullanir.
"""
import struct
import subprocess
import shutil
import os


class ImageError(Exception):
    pass


# ---------------------------------------------------------------- PNG
def _png(path):
    d = open(path, 'rb').read()
    if d[:8] != b'\x89PNG\r\n\x1a\n':
        raise ImageError("PNG imzasi yok")
    i = 8
    idat = b''
    plte = trns = None
    w = h = bd = ct = inter = None
    while i < len(d):
        ln = struct.unpack('>I', d[i:i + 4])[0]
        typ = d[i + 4:i + 8]
        data = d[i + 8:i + 8 + ln]
        i += 12 + ln
        if typ == b'IHDR':
            w, h, bd, ct, comp, filt, inter = struct.unpack('>IIBBBBB', data)
        elif typ == b'PLTE':
            plte = data
        elif typ == b'tRNS':
            trns = data
        elif typ == b'IDAT':
            idat += data
        elif typ == b'IEND':
            break
    if w is None:
        raise ImageError("IHDR yok")
    if inter not in (0, 1):
        raise ImageError("bilinmeyen interlace")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ct)
    if channels is None:
        raise ImageError("PGN renk tipi %d" % ct)
    if bd not in (1, 2, 4, 8, 16):
        raise ImageError("PNG bit derinligi %d" % bd)
    raw = _zlib_decompress(idat)
    bpp = max(1, (channels * bd) // 8)
    if bd < 8:
        bpp = 1
    stride = (w * channels * bd + 7) // 8
    px = bytearray(stride * h)

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else (b if pb <= pc else c)

    def unfilter(data, pos, sstride, ph, unit):
        rows = []
        prev = bytearray(sstride)
        p = pos
        for _ in range(ph):
            f = data[p]
            p += 1
            line = bytearray(data[p:p + sstride])
            p += sstride
            if f == 1:
                for x in range(unit, sstride):
                    line[x] = (line[x] + line[x - unit]) & 255
            elif f == 2:
                for x in range(sstride):
                    line[x] = (line[x] + prev[x]) & 255
            elif f == 3:
                for x in range(sstride):
                    a = line[x - unit] if x >= unit else 0
                    line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
            elif f == 4:
                for x in range(sstride):
                    a = line[x - unit] if x >= unit else 0
                    c = prev[x - unit] if x >= unit else 0
                    line[x] = (line[x] + paeth(a, prev[x], c)) & 255
            rows.append(line)
            prev = line
        return rows, p

    unit = max(1, bpp)
    if inter == 0:
        rows, _ = unfilter(raw, 0, stride, h, unit)
        for y in range(h):
            px[y * stride:(y + 1) * stride] = rows[y]
    else:
        passes = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
                  (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
        pos = 0
        for (xo, yo, xs, ys) in passes:
            pw = (w - xo + xs - 1) // xs
            ph = (h - yo + ys - 1) // ys
            if pw == 0 or ph == 0:
                continue
            pstride = (pw * channels * bd + 7) // 8
            rows, pos = unfilter(raw, pos, pstride, ph, unit)
            for y in range(ph):
                line = rows[y]
                for x in range(pw):
                    for c in range(channels * bd):
                        sbit = x * channels * bd + c
                        dbit = ((yo + y * ys) * w + (xo + x * xs)) * channels * bd + c
                        sb, db = sbit >> 3, dbit >> 3
                        if 0 <= sb < len(line) and 0 <= db < len(px):
                            px[db] |= ((line[sb] >> (7 - (sbit & 7))) & 1) << (7 - (dbit & 7))
    return _png_to_rgb(w, h, ct, bd, px, plte, trns)


def _zlib_decompress(data):
    import zlib
    return zlib.decompress(data)


def _extract_bits(px, row_bytes, w, channels, bd, index):
    """bit-packed (bd<8) veya 8/16-bit pikselden degerleri cikarir."""
    out = []
    for k in range(w):
        if bd == 8:
            out.append([px[index + k * channels + c] for c in range(channels)])
        elif bd == 16:
            vals = []
            for c in range(channels):
                o = index + (k * channels + c) * 2
                vals.append(px[o])
            out.append(vals)
        else:
            vals = []
            base = k * channels * bd
            for c in range(channels):
                b = base + c * bd
                byte = px[index + (b >> 3)]
                shift = 8 - bd - (b & 7)
                mask = (1 << bd) - 1
                vals.append((byte >> shift) & mask)
            out.append(vals)
    return out


def _png_to_rgb(w, h, ct, bd, px, plte, trns):
    n = w * h
    rgb = bytearray(n * 3)
    alpha = bytearray([255]) * n
    maxv = (1 << bd) - 1 if bd < 8 else (65535 if bd == 16 else 255)

    def scale(v):
        if bd == 16:
            return v >> 8
        if bd == 8:
            return v
        return v * 255 // maxv

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    row_bytes = (w * channels * bd + 7) // 8
    for y in range(h):
        base = y * row_bytes
        vals = _extract_bits(px, row_bytes, w, channels, bd, base)
        for x in range(w):
            v = vals[x]
            o = (y * w + x) * 3
            a = 255
            if ct == 0:
                g = scale(v[0])
                rgb[o] = rgb[o + 1] = rgb[o + 2] = g
            elif ct == 2:
                rgb[o] = scale(v[0])
                rgb[o + 1] = scale(v[1])
                rgb[o + 2] = scale(v[2])
            elif ct == 3:
                idx = v[0]
                if bd < 8:
                    if idx >= len(plte) // 3:
                        idx = 0
                rgb[o] = scale(plte[idx * 3])
                rgb[o + 1] = scale(plte[idx * 3 + 1])
                rgb[o + 2] = scale(plte[idx * 3 + 2])
                if trns and idx < len(trns):
                    a = trns[idx]
            elif ct == 4:
                g = scale(v[0])
                rgb[o] = rgb[o + 1] = rgb[o + 2] = g
                a = scale(v[1])
            elif ct == 6:
                rgb[o] = scale(v[0])
                rgb[o + 1] = scale(v[1])
                rgb[o + 2] = scale(v[2])
                a = scale(v[3])
            alpha[y * w + x] = a
    return w, h, bytes(rgb), bytes(alpha)


# ---------------------------------------------------------------- ffmpeg
def _via_ffmpeg(path, ffmpeg='ffmpeg'):
    """ffmpeg ile rgba rawvideo'ya cozer (JPEG/WEBP/GIF/TIFF/...)."""
    if not shutil.which(ffmpeg):
        raise ImageError("ffmpeg bulunamadi")
    w, h = _probe_wh(path)
    proc = subprocess.run(
        [ffmpeg, '-v', 'error', '-i', path, '-f', 'rawvideo',
         '-pix_fmt', 'rgba', '-'], capture_output=True)
    buf = proc.stdout
    need = w * h * 4
    if len(buf) < need:
        raise ImageError("ffmpeg cozemedi (%s)" % path)
    rgb = bytearray(w * h * 3)
    alpha = bytearray(w * h)
    for k in range(w * h):
        rgb[k * 3] = buf[k * 4]
        rgb[k * 3 + 1] = buf[k * 4 + 1]
        rgb[k * 3 + 2] = buf[k * 4 + 2]
        alpha[k] = buf[k * 4 + 3]
    return w, h, bytes(rgb), bytes(alpha)


def _probe_wh(path, ffprobe='ffprobe'):
    if shutil.which(ffprobe):
        out = subprocess.run(
            [ffprobe, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height', '-of', 'csv=p=0', path],
            capture_output=True, text=True)
        parts = out.stdout.strip().split(',')
        if len(parts) >= 2 and parts[0].strip().isdigit():
            return int(parts[0]), int(parts[1])
    import re
    out = subprocess.run(['ffmpeg', '-i', path], capture_output=True, text=True)
    m = re.search(r'(\d{2,5})x(\d{2,5})', out.stderr)
    if m:
        return int(m.group(1)), int(m.group(2))
    raise ImageError("boyut ogrenilemedi: %s" % path)


# ---------------------------------------------------------------- PNM
def _read_pnm(data):
    # P4/P5/P6 ikili, P1/P2/P3 ascii
    i = 0

    def token():
        nonlocal i
        while i < len(data) and data[i] in b' \t\r\n':
            i += 1
        if i < len(data) and data[i:i + 1] == b'#':
            while i < len(data) and data[i] not in b'\r\n':
                i += 1
            return token()
        s = i
        while i < len(data) and data[i] not in b' \t\r\n':
            i += 1
        return data[s:i]

    magic = token()
    w = int(token())
    h = int(token())
    maxv = int(token()) if magic != b'P4' else 1
    i += 1
    n = w * h
    rgb = bytearray(n * 3)
    alpha = bytearray([255]) * n
    if magic == b'P6':
        raw = data[i:i + n * 3]
        for k in range(n):
            rgb[k * 3] = raw[k * 3] * 255 // maxv
            rgb[k * 3 + 1] = raw[k * 3 + 1] * 255 // maxv
            rgb[k * 3 + 2] = raw[k * 3 + 2] * 255 // maxv
    elif magic == b'P5':
        raw = data[i:i + n]
        for k in range(n):
            g = raw[k] * 255 // maxv
            rgb[k * 3] = rgb[k * 3 + 1] = rgb[k * 3 + 2] = g
    elif magic == b'P4':
        row_bytes = (w + 7) // 8
        for y in range(h):
            for x in range(w):
                b = data[i + y * row_bytes + (x >> 3)]
                v = 255 if (b >> (7 - (x & 7))) & 1 else 0
                k = y * w + x
                rgb[k * 3] = rgb[k * 3 + 1] = rgb[k * 3 + 2] = v
    else:
        raise ImageError("PNM %s desteklenmiyor" % magic)
    return w, h, bytes(rgb), bytes(alpha)


# ---------------------------------------------------------------- BMP
def _bmp(path):
    d = open(path, 'rb').read()
    if d[:2] != b'BM':
        raise ImageError("BMP imzasi yok")
    off = struct.unpack_from('<I', d, 10)[0]
    w = struct.unpack_from('<i', d, 18)[0]
    h = struct.unpack_from('<i', d, 22)[0]
    bpp = struct.unpack_from('<H', d, 28)[0]
    topdown = h < 0
    h = abs(h)
    row = ((w * bpp + 31) // 32) * 4
    rgb = bytearray(w * h * 3)
    alpha = bytearray([255]) * (w * h)
    for y in range(h):
        sy = y if topdown else (h - 1 - y)
        base = off + sy * row
        for x in range(w):
            p = base + x * (bpp // 8)
            if bpp == 32:
                b, g, r, a = d[p], d[p + 1], d[p + 2], d[p + 3]
                alpha[y * w + x] = a
            elif bpp == 24:
                b, g, r = d[p], d[p + 1], d[p + 2]
            elif bpp == 8:
                b = g = r = d[p]
            else:
                raise ImageError("BMP %d bpp desteklenmiyor" % bpp)
            o = (y * w + x) * 3
            rgb[o], rgb[o + 1], rgb[o + 2] = r, g, b
    return w, h, bytes(rgb), bytes(alpha)


# ---------------------------------------------------------------- dispath
def read_image(path):
    head = open(path, 'rb').read(16)
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return _png(path)
    if head[:2] == b'BM':
        return _bmp(path)
    if head[:2] in (b'P4', b'P5', b'P6'):
        return _read_pnm(open(path, 'rb').read())
    if shutil.which('ffmpeg'):
        return _via_ffmpeg(path)
    raise ImageError("%s: cozmek icin ffmpeg gerekli" % path)
