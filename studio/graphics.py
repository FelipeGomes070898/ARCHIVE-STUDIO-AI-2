"""Animações (motion graphics) desenhadas pelo próprio estúdio: mapas, diagramas e gráficos.

Cada tipo é uma função `render_x(spec, out, seconds, w, h)` registrada em GRAPHICS.
Mapas usam dados do Natural Earth (domínio público), baixados na primeira vez em <pasta do estúdio>/geodata.
"""
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import config, media

GEO_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/{}.geojson"
LAYERS = {"land": "ne_50m_land", "countries": "ne_50m_admin_0_countries",
          "states": "ne_50m_admin_1_states_provinces_lakes", "lakes": "ne_10m_lakes",
          "rivers": "ne_10m_rivers_lake_centerlines"}
_geo = {}

OCEAN, LAND = (34, 22, 10), (31, 38, 43)          # cores em BGR para o OpenCV
STATE, BORDER, LAKE, RIVER = (70, 80, 88), (110, 125, 135), (92, 66, 30), (110, 85, 45)
CYAN, GOLD, WHITE = (255, 214, 64), (40, 200, 255), (245, 245, 245)


def _cv2():
    import cv2  # noqa: PLC0415
    return cv2


def geo(layer):
    """Carrega (e baixa na 1ª vez) uma camada do Natural Earth."""
    if layer not in _geo:
        d = config.HOME / "geodata"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{LAYERS[layer]}.geojson"
        if not f.exists():
            req = urllib.request.Request(GEO_URL.format(LAYERS[layer]), headers={"User-Agent": "ArchiveStudioAI"})
            with urllib.request.urlopen(req, timeout=300) as r:
                f.write_bytes(r.read())
        _geo[layer] = json.loads(f.read_text(encoding="utf-8"))["features"]
    return _geo[layer]


def _parts(geom):
    """Lista de anéis/linhas [(lon, lat), ...] de qualquer geometria."""
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString":
        return [c]
    if t in ("MultiLineString", "Polygon"):
        return list(c)
    if t == "MultiPolygon":
        return [ring for poly in c for ring in poly]
    return []


def _polys(geom):
    t, c = geom["type"], geom["coordinates"]
    return [c] if t == "Polygon" else (list(c) if t == "MultiPolygon" else [])


class View:
    """Projeção simples (equiretangular corrigida pela latitude) ajustada a uma caixa de lon/lat."""

    def __init__(self, bbox, w, h, pad=0.04):
        lon0, lon1, lat0, lat1 = bbox
        self.lonc, self.latc = (lon0 + lon1) / 2, (lat0 + lat1) / 2
        self.kx = math.cos(math.radians(self.latc))
        self.w, self.h = w, h
        self.s = min(w * (1 - 2 * pad) / ((lon1 - lon0) * self.kx), h * (1 - 2 * pad) / (lat1 - lat0))

    def xy(self, pts):
        a = np.asarray(pts, dtype=np.float64)[:, :2]
        x = self.w / 2 + (a[:, 0] - self.lonc) * self.kx * self.s
        y = self.h / 2 - (a[:, 1] - self.latc) * self.s
        return np.stack([x, y], axis=1)

    def visible(self, pts, margin=200):
        p = self.xy(pts)
        return (p[:, 0].max() > -margin and p[:, 0].min() < self.w + margin
                and p[:, 1].max() > -margin and p[:, 1].min() < self.h + margin)


def _poly(img, view, rings, color, fill=True, thick=1):
    cv2 = _cv2()
    pts = [np.round(view.xy(r) * 4).astype(np.int32) for r in rings if len(r) > 2 and view.visible(r)]
    if not pts:
        return
    if fill:
        cv2.fillPoly(img, pts, color, cv2.LINE_AA, shift=2)
    else:
        cv2.polylines(img, pts, False, color, thick, cv2.LINE_AA, shift=2)


def chain_river(name, start, end, bbox):
    """Une os trechos do rio em um caminho contínuo da nascente (start) até a foz (end)."""
    lon0, lon1, lat0, lat1 = bbox
    segs = []
    for f in geo("rivers"):
        if f["properties"].get("name") != name:
            continue
        for part in _parts(f["geometry"]):
            if any(lon0 - 1 <= p[0] <= lon1 + 1 and lat0 - 1 <= p[1] <= lat1 + 1 for p in part):
                segs.append([tuple(p[:2]) for p in part])
    if not segs:
        return []

    def d(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    first = min(range(len(segs)), key=lambda i: min(d(segs[i][0], start), d(segs[i][-1], start)))
    seg = segs.pop(first)
    path = seg if d(seg[0], start) <= d(seg[-1], start) else seg[::-1]
    while segs and d(path[-1], end) > 0.05:
        i = min(range(len(segs)), key=lambda k: min(d(segs[k][0], path[-1]), d(segs[k][-1], path[-1])))
        s = segs[i]
        if min(d(s[0], path[-1]), d(s[-1], path[-1])) > 0.35:
            break
        segs.pop(i)
        path += s if d(s[0], path[-1]) <= d(s[-1], path[-1]) else s[::-1]
    return path


def _partial(points, frac):
    """Primeira fração `frac` de uma linha (pelo comprimento)."""
    p = np.asarray(points, dtype=np.float64)
    if len(p) < 2 or frac <= 0:
        return p[:1]
    seg = np.hypot(*np.diff(p, axis=0).T)
    cum = np.concatenate([[0], np.cumsum(seg)])
    target = cum[-1] * min(1.0, frac)
    k = int(np.searchsorted(cum, target))
    if k >= len(p):
        return p
    r = (target - cum[k - 1]) / max(seg[k - 1], 1e-9)
    return np.vstack([p[:k], p[k - 1] + (p[k] - p[k - 1]) * r])


def _glow_line(img, pts, color, width):
    cv2 = _cv2()
    if len(pts) < 2:
        return
    q = np.round(pts * 4).astype(np.int32)
    glow = np.zeros_like(img)
    cv2.polylines(glow, [q], False, color, width * 4, cv2.LINE_AA, shift=2)
    glow = cv2.GaussianBlur(glow, (0, 0), width * 2.5)
    cv2.add(img, (glow * 0.8).astype(np.uint8), dst=img)
    cv2.polylines(img, [q], False, color, width, cv2.LINE_AA, shift=2)


def _bgr(rgb, default):
    """Cores no spec são RGB; o OpenCV desenha em BGR."""
    return tuple(int(c) for c in reversed(rgb)) if rgb else default


def _ramp(t, t0, t1):
    return float(np.clip((t - t0) / max(1e-6, t1 - t0), 0, 1))


def _ease(p):
    return 0.5 - 0.5 * math.cos(math.pi * p)


def _text(draw, xy, text, size, fill=(255, 255, 255), anchor="la", bold=True, alpha=1.0):
    if alpha <= 0:
        return
    f = media._font(int(size), bold)
    col = tuple(int(c) for c in fill) + (int(255 * alpha),)
    draw.text(xy, text, font=f, fill=col, anchor=anchor, stroke_width=max(2, int(size / 9)),
              stroke_fill=(0, 0, 0, int(220 * alpha)))


def render_map(spec, out, seconds, w, h, fps=media.FPS):
    cv2 = _cv2()
    margin = 1.12
    bw, bh = round(w * margin), round(h * margin)
    view = View(spec["bbox"], bw, bh)
    base = np.zeros((bh, bw, 3), np.uint8)
    base[:] = OCEAN
    for f in geo("land"):
        for poly in _polys(f["geometry"]):
            _poly(base, view, poly[:1], LAND)
    hidden = (spec.get("fill") or {}).get("lake")          # o lago que "enche" não aparece no fundo
    for f in geo("lakes"):
        if f["properties"].get("name") == hidden:
            continue
        for poly in _polys(f["geometry"]):
            _poly(base, view, poly[:1], LAKE)
    for f in geo("rivers"):
        if f["properties"].get("scalerank", 10) <= 7:
            _poly(base, view, _parts(f["geometry"]), RIVER, fill=False, thick=2)
    for f in geo("states"):
        if f["properties"].get("adm0_a3") in ("USA", "MEX"):
            for poly in _polys(f["geometry"]):
                _poly(base, view, poly[:1], STATE, fill=False, thick=1)
    for f in geo("countries"):
        for poly in _polys(f["geometry"]):
            _poly(base, view, poly[:1], BORDER, fill=False, thick=3)
    # Vinheta para foco no centro.
    yy, xx = np.mgrid[0:bh, 0:bw].astype(np.float32)
    vig = 1 - 0.55 * (((xx - bw / 2) / (bw / 2)) ** 2 + ((yy - bh / 2) / (bh / 2)) ** 2) / 2
    base = (base * np.clip(vig, 0.35, 1)[..., None]).astype(np.uint8)

    rivers = []
    for r in spec.get("rivers", []):
        path = chain_river(r["name"], r["from"], r["to"], spec["bbox"])
        if path:
            rivers.append((r, view.xy(path)))
    routes = [(r, view.xy(r["coords"])) for r in spec.get("routes", [])]
    lake_shapes = {}
    for want in [x["name"] for x in spec.get("lakes", [])] + ([spec["fill"]["lake"]] if spec.get("fill") else []):
        for f in geo("lakes"):
            if f["properties"].get("name") == want:
                lake_shapes[want] = [view.xy(poly[0]) for poly in _polys(f["geometry"])]
    focus = view.xy([spec.get("focus") or [view.lonc, view.latc]])[0]
    zoom_end = float(spec.get("zoom", 1.08))
    n = max(1, round(seconds * fps))
    with media.FrameWriter(out, w, h, fps) as wr:
        for i in range(n):
            t = i / max(1, n - 1)
            img = base.copy()
            if spec.get("fill"):
                fl = spec["fill"]
                k = _ease(_ramp(t, fl["t0"], fl["t1"]))
                for shape in lake_shapes.get(fl["lake"], []):
                    c = shape.mean(axis=0)
                    pts = c + (shape - c) * max(0.02, k)
                    layer = img.copy()
                    cv2.fillPoly(layer, [np.round(pts * 4).astype(np.int32)], (230, 160, 60), cv2.LINE_AA, shift=2)
                    cv2.addWeighted(layer, 0.85, img, 0.15, 0, dst=img)
            for lk in spec.get("lakes", []):
                a = _ramp(t, lk.get("t", 0.3), lk.get("t", 0.3) + 0.12)
                if a <= 0:
                    continue
                pulse = 0.5 + 0.5 * math.sin(t * 14)
                layer = img.copy()
                for shape in lake_shapes.get(lk["name"], []):
                    q = np.round(shape * 4).astype(np.int32)
                    cv2.fillPoly(layer, [q], (255, 200, 90), cv2.LINE_AA, shift=2)
                    cv2.polylines(layer, [q], True, CYAN, 3 + int(4 * pulse), cv2.LINE_AA, shift=2)
                cv2.addWeighted(layer, a, img, 1 - a, 0, dst=img)
            for r, pts in rivers:
                frac = _ease(_ramp(t, r.get("t0", 0.0), r.get("t1", 0.7)))
                _glow_line(img, _partial(pts, frac), _bgr(r.get("color"), CYAN), int(r.get("width", 5)))
            for r, pts in routes:
                frac = _ease(_ramp(t, r.get("t0", 0.3), r.get("t1", 0.8)))
                _glow_line(img, _partial(pts, frac), _bgr(r.get("color"), GOLD), int(r.get("width", 5)))
            # Câmera: aproximação lenta em direção ao foco.
            z = 1 + (zoom_end - 1) * _ease(t)
            cx = bw / 2 + (focus[0] - bw / 2) * (z - 1) / max(zoom_end - 1, 1e-6) * 0.5
            cy = bh / 2 + (focus[1] - bh / 2) * (z - 1) / max(zoom_end - 1, 1e-6) * 0.5
            sc = z * w / bw * margin
            m = np.float32([[sc, 0, w / 2 - cx * sc], [0, sc, h / 2 - cy * sc]])
            frame = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
            over = Image.new("RGBA", pil.size, (0, 0, 0, 0))
            dr = ImageDraw.Draw(over)
            size = h * 0.022
            for p in spec.get("points", []):
                a = _ramp(t, p.get("t", 0.2), p.get("t", 0.2) + 0.08)
                if a <= 0:
                    continue
                x, y = view.xy([[p["lon"], p["lat"]]])[0]
                x, y = x * sc + m[0, 2], y * sc + m[1, 2]
                rad = size * (0.32 if p.get("kind") != "dam" else 0.42)
                col = (255, 200, 40) if p.get("kind") == "dam" else (255, 255, 255)
                ring = rad * (1 + 2.5 * ((t * 1.6 + p.get("t", 0)) % 1))
                dr.ellipse((x - ring, y - ring, x + ring, y + ring), outline=col + (int(120 * a),), width=3)
                dr.ellipse((x - rad, y - rad, x + rad, y + rad), fill=col + (int(255 * a),))
                dx, dy = p.get("dx", 1), p.get("dy", 0)
                anchor = "lm" if dx >= 0 else "rm"
                _text(dr, (x + (rad * 2.2) * (1 if dx >= 0 else -1), y + dy * size), p["name"], size * p.get("scale", 1),
                      anchor=anchor, alpha=a)
            for lab in spec.get("labels", []):
                a = _ramp(t, lab.get("t", 0.3), lab.get("t", 0.3) + 0.1)
                x, y = view.xy([[lab["lon"], lab["lat"]]])[0]
                _text(dr, (x * sc + m[0, 2], y * sc + m[1, 2]), lab["text"], size * lab.get("scale", 0.9),
                      fill=lab.get("color", (120, 220, 255)), anchor="mm", alpha=a)
            if spec.get("note"):
                _text(dr, (w * 0.05, h * 0.785), spec["note"], h * 0.0135, fill=(200, 200, 200), bold=False)
            pil = Image.alpha_composite(pil, over).convert("RGB")
            wr.write(np.asarray(pil))
    return out


# ------------------------------------------------------------------ diagrama: resfriamento do concreto
def render_cooling(spec, out, seconds, w, h, fps=media.FPS):
    """Corte simplificado de uma barragem em blocos com tubos de água gelada (ilustração, não foto)."""
    n = max(1, round(seconds * fps))
    rows, top_w, base_w = 9, 0.22, 0.86
    y0, y1 = h * 0.30, h * 0.66
    hot, cool = np.array([255, 110, 30]), np.array([150, 170, 190])
    with media.FrameWriter(out, w, h, fps) as wr:
        for i in range(n):
            t = i / max(1, n - 1)
            img = Image.new("RGB", (w, h), (10, 22, 36))
            d = ImageDraw.Draw(img, "RGBA")
            step = w // 18
            for gx in range(0, w, step):
                d.line((gx, 0, gx, h), fill=(30, 55, 80, 120), width=1)
            for gy in range(0, h, step):
                d.line((0, gy, w, gy), fill=(30, 55, 80, 120), width=1)
            build = _ramp(t, 0.0, 0.35)
            for r in range(rows):
                if (r + 1) / rows > build + 1e-6 and build < 1:
                    continue
                fy0 = y1 - (r + 1) * (y1 - y0) / rows
                fy1 = y1 - r * (y1 - y0) / rows
                frac = (r + 0.5) / rows
                width = w * (base_w + (top_w - base_w) * frac)
                cols = max(2, int(width / (w * 0.09)))
                bwid = width / cols
                cool_k = _ramp(t, 0.42 + 0.04 * r / rows, 0.95)
                for c in range(cols):
                    bx0 = w / 2 - width / 2 + c * bwid
                    col = hot + (cool - hot) * cool_k
                    flick = 0.9 + 0.1 * math.sin(t * 30 + c + r)
                    d.rectangle((bx0 + 2, fy0 + 2, bx0 + bwid - 2, fy1 - 2),
                                fill=tuple(int(v * (flick if cool_k < 1 else 1)) for v in col) + (235,),
                                outline=(20, 30, 40, 255), width=2)
                    if t > 0.38:
                        py = (fy0 + fy1) / 2
                        d.line((bx0 + 6, py, bx0 + bwid - 6, py), fill=(170, 235, 255, 255), width=4)
                        off = (t * 600 + c * 13) % 26
                        x = bx0 + 6 + off
                        while x < bx0 + bwid - 6:
                            d.line((x, py, min(x + 9, bx0 + bwid - 6), py), fill=(40, 120, 255, 255), width=6)
                            x += 26
            a1 = _ramp(t, 0.12, 0.2) * (1 - _ramp(t, 0.5, 0.58))
            a2 = _ramp(t, 0.45, 0.53)
            _text(d, (w / 2, h * 0.255), "HEAT RELEASED AS CONCRETE HARDENS", h * 0.02, fill=(255, 150, 60),
                  anchor="mm", alpha=a1)
            _text(d, (w / 2, h * 0.255), "CHILLED WATER FLOWS THROUGH PIPES", h * 0.02, fill=(120, 210, 255),
                  anchor="mm", alpha=a2)
            _text(d, (w * 0.05, h * 0.785), "Simplified illustration, not to scale", h * 0.0135,
                  fill=(200, 200, 200), bold=False)
            wr.write(np.asarray(img))
    return out


# ------------------------------------------------------------------ gráfico: nível de um reservatório
def render_levels(spec, out, seconds, w, h, fps=media.FPS):
    """Corte de um cânion com o nível da água descendo e o 'anel de banheira' aparecendo."""
    hi, lo = spec["high"], spec["low"]             # {"value": 1225, "label": "1983: ~1,225 ft"}
    vmin, vmax = spec.get("axis", (lo["value"] - 60, hi["value"] + 40))
    top, bot = h * 0.27, h * 0.70

    def y_of(v):
        return bot - (v - vmin) / (vmax - vmin) * (bot - top)

    n = max(1, round(seconds * fps))
    wall_l = [(0, top - 120), (w * 0.16, top - 40), (w * 0.24, top + 140), (w * 0.33, bot - 120), (w * 0.43, bot), (0, bot)]
    wall_r = [(w, top - 160), (w * 0.86, top - 30), (w * 0.77, top + 180), (w * 0.69, bot - 100), (w * 0.57, bot), (w, bot)]
    # Fundo fixo: céu, paredes com camadas de rocha e o leito.
    bg = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(bg)
    for yy in range(h):
        k = yy / h
        d.line((0, yy, w, yy), fill=(int(20 + 90 * k), int(28 + 55 * k), int(48 + 20 * k)))
    rock = Image.new("RGB", (w, h), (126, 74, 42))
    rd = ImageDraw.Draw(rock)
    rng = np.random.default_rng(3)
    yy = top - 200
    while yy < h:
        th = int(rng.integers(6, 22))
        shade = int(rng.integers(-28, 18))
        rd.rectangle((0, yy, w, yy + th), fill=(126 + shade, 74 + shade // 2, 42 + shade // 3))
        yy += th
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.polygon(wall_l, fill=255)
    md.polygon(wall_r, fill=255)
    md.rectangle((0, bot, w, h), fill=255)
    with media.FrameWriter(out, w, h, fps) as wr:
        for i in range(n):
            t = i / max(1, n - 1)
            k = _ease(_ramp(t, 0.15, 0.75))
            level = hi["value"] + (lo["value"] - hi["value"]) * k
            yl, yh = y_of(level), y_of(hi["value"])
            img = bg.copy()
            d = ImageDraw.Draw(img, "RGBA")
            d.rectangle((0, yl, w, bot), fill=(22, 86, 128, 255))
            d.rectangle((0, yl, w, yl + 5), fill=(140, 210, 235, 255))
            walls = rock.copy()
            ImageDraw.Draw(walls, "RGBA").rectangle((0, yh, w, yl), fill=(240, 232, 214, 175))
            img.paste(walls, (0, 0), mask)
            d = ImageDraw.Draw(img, "RGBA")
            for v, lab, a in ((hi["value"], hi["label"], 1.0), (lo["value"], lo["label"], _ramp(t, 0.72, 0.8))):
                y = y_of(v)
                x = 0
                while x < w:
                    d.line((x, y, x + 24, y), fill=(255, 255, 255, int(220 * a)), width=3)
                    x += 40
                _text(d, (w * 0.95, y - h * 0.012), lab, h * 0.022, fill=(255, 220, 60), anchor="rb", alpha=a)
            ring_a = _ramp(t, 0.55, 0.7)
            _text(d, (w * 0.5, (yh + yl) / 2), spec.get("ring_label", ""), h * 0.018, fill=(255, 255, 255), anchor="mm",
                  alpha=ring_a * (1 if spec.get("ring_label") else 0))
            _text(d, (w * 0.05, h * 0.785), spec.get("note", ""), h * 0.0135, fill=(225, 225, 225), bold=False)
            wr.write(np.asarray(img))
    return out


GRAPHICS = {"map": render_map, "cooling": render_cooling, "levels": render_levels}


def render(spec, out, seconds, w, h):
    fn = GRAPHICS.get(spec.get("type"))
    if not fn:
        raise RuntimeError(f"Tipo de animação desconhecido: {spec.get('type')}")
    return fn(spec, Path(out), seconds, w, h)
