"""Generate r1x.ico (256px, PNG-embedded) using only the Python standard library."""
import struct, zlib

S = 256
data = bytearray(S * S * 4)  # RGBA, row-major


def blend(px, x, y, r, g, b, a):
    # src-over composite with supersampling
    i = (y * S + x) * 4
    sa = a / 255.0
    da = px[i + 3] / 255.0
    oa = sa + da * (1 - sa)
    if oa <= 0:
        px[i + 3] = 0
        return
    px[i] = int((r * sa + px[i] * da * (1 - sa)) / oa)
    px[i + 1] = int((g * sa + px[i + 1] * da * (1 - sa)) / oa)
    px[i + 2] = int((b * sa + px[i + 2] * da * (1 - sa)) / oa)
    px[i + 3] = int(oa * 255)


def lerp(a, b, t):
    return a + (b - a) * t


def grad(t, stops):
    t = max(0.0, min(1.0, t))
    seg = 2
    n = len(stops) - 1
    step = 1.0 / n
    for i in range(n):
        if t <= step * (i + 1):
            local = (t - step * i) / step
            from_ = stops[i]
            to_ = stops[i + 1]
            return (lerp(from_[0], to_[0], local),
                    lerp(from_[1], to_[1], local),
                    lerp(from_[2], to_[2], local))
    return stops[-1]


STOPS = [(0, 229, 255), (124, 77, 255), (255, 45, 111)]


def rounded_rect_alpha(x, y):
    x0, y0, x1, y1, r = 14, 14, S - 14, S - 14, 46
    if x < x0 or x > x1 or y < y0 or y > y1:
        return 0.0
    dx = max(x0 + r - x, x - (x1 - r), 0)
    dy = max(y0 + r - y, y - (y1 - r), 0)
    if dx <= 0 and dy <= 0:
        return 1.0
    d = dx * dx + dy * dy
    if d <= r * r:
        return 1.0
    return 0.0


def in_bolt(x, y):
    pts = [(150, 18), (66, 142), (122, 142), (98, 238), (198, 108), (138, 108), (182, 18)]
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[j]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
            inside = not inside
        j = i
    return inside


for yy in range(S):
    for xx in range(S):
        t = (xx + yy) / (2.0 * S)
        r, g, b = grad(t, STOPS)

        hits = 0
        for sx in (0, 1):
            for sy in (0, 1):
                hits += rounded_rect_alpha(xx + sx * 0.5, yy + sy * 0.5)
        cover = hits / 4.0
        if cover > 0:
            blend(data, xx, yy, r, g, b, int(255 * cover))

        if in_bolt(xx + 0.5, yy + 0.5):
            # white-hot bolt with soft glow
            blend(data, xx, yy, 235, 255, 255, 200)
            for ox, oy in ((2, 0), (-2, 0), (0, 2), (0, -2)):
                bx, by = xx + ox, yy + oy
                if 0 <= bx < S and 0 <= by < S:
                    blend(data, bx, by, 0, 229, 255, 60)


def write_png(path):
    raw = bytearray()
    for y in range(S):
        raw.append(0)
        row = data[y * S * 4:(y + 1) * S * 4]
        raw.extend(row)
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(tag, payload):
        c = tag + payload
        return struct.pack(">I", len(payload)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", compressed)
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return png


def write_ico(path, png):
    # modern ICO wraps PNG directly
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    with open(path, "wb") as f:
        f.write(header + entry + png)


if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    png = write_png("r1x_icon.png")
    write_ico("r1x.ico", png)
    print("[icon] r1x.ico + r1x_icon.png generated")