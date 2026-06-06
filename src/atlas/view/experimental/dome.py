# atlas/src/view/dome.py
# Full-sky dome renderer — azimuthal equidistant projection, interactive body lookup

# Standard Modules
import os
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

# Internal Modules
from atlas.view.base import (
    BaseGLWindow, GlyphAtlas, _RGBA, _ortho, _circle_verts, _glyph_quad,
    _strip_var_selector, _FONT_PATH, _SYMBOL_FONT, TEXT_CHARS, SYMBOL_CHARS,
)

if TYPE_CHECKING:
    from atlas.models.celestial_state import CelestialState
    from atlas.models.location import Location

# External Modules
import moderngl
import moderngl_window
import numpy as np
import swisseph as swe
from PIL import Image, ImageDraw, ImageFont


_SHADER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shaders")
_DATA_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

_PANEL_VERT = """
#version 330 core
in vec2 in_pos; in vec2 in_uv; out vec2 v_uv;
void main() { gl_Position = vec4(in_pos, 0.0, 1.0); v_uv = in_uv; }
"""
_PANEL_FRAG = """
#version 330 core
uniform sampler2D panel_tex; in vec2 v_uv; out vec4 fragColor;
void main() { fragColor = texture(panel_tex, v_uv); }
"""

_VIEWPORT     = 1.15
_DOME_R       = 1.0
_CLICK_RADIUS = 0.045
_PANEL_W      = 300
_PANEL_H      = 295

_PLANET_COLORS: dict[str, _RGBA] = {
    "sun":     (1.0,  0.95, 0.3,  1.0), "moon":    (0.95, 0.95, 0.85, 1.0),
    "mercury": (0.75, 0.75, 0.75, 1.0), "venus":   (0.95, 0.9,  0.7,  1.0),
    "mars":    (0.9,  0.35, 0.2,  1.0), "jupiter": (0.88, 0.78, 0.62, 1.0),
    "saturn":  (0.9,  0.85, 0.65, 1.0), "uranus":  (0.6,  0.85, 0.9,  1.0),
    "neptune": (0.4,  0.5,  0.92, 1.0), "pluto":   (0.8,  0.7,  0.9,  1.0),
}
_DEFAULT_PLANET_COLOR: _RGBA = (0.85, 0.85, 1.0, 1.0)

# Derive constellation centroids from the IAU boundary strips in constellations.dat
@lru_cache(maxsize=1)
def _load_constellation_centers(dat_path: str) -> dict[str, tuple[float, float]]:
    from collections import defaultdict
    strips: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    with open(dat_path) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 4:
                ra_low, ra_high, dec_low = float(parts[0]), float(parts[1]), float(parts[2])
                strips[parts[3]].append((ra_low, ra_high, dec_low))

    centers: dict[str, tuple[float, float]] = {}
    for abbr, strip_list in strips.items():
        # RA midpoint per strip (hours); handle wrap across 0h/24h
        ra_mids = [(s[0] + s[1]) / 2 for s in strip_list]
        if max(ra_mids) - min(ra_mids) > 12.0:
            ra_mids = [r + 24.0 if r < 12.0 else r for r in ra_mids]
        ra_deg = (sum(ra_mids) / len(ra_mids) % 24.0) * 15.0

        # Dec: midpoint between lowest and highest strip boundaries
        dec_deg = (min(s[2] for s in strip_list) + max(s[2] for s in strip_list)) / 2

        centers[abbr] = (ra_deg, dec_deg)
    return centers


def _ci_to_rgb(ci: float) -> tuple[float, float, float]:
    if not math.isfinite(ci):
        ci = 0.6
    ci = max(-0.4, min(2.0, ci))
    if ci < 0.0:
        t = (ci + 0.4) / 0.4
        return (0.55 + 0.45 * t, 0.7 + 0.3 * t, 1.0)
    elif ci < 0.58:
        t = ci / 0.58
        return (1.0, 1.0, 1.0 - 0.05 * t)
    elif ci < 1.0:
        t = (ci - 0.58) / 0.42
        return (1.0, 1.0 - 0.25 * t, 0.95 - 0.45 * t)
    else:
        t = min(1.0, (ci - 1.0) / 1.0)
        return (1.0, 0.75 - 0.65 * t, 0.5 - 0.5 * t)


def _mag_to_size(mag: float) -> float:
    return max(1.0, (7.5 - mag) * 1.6)


def _project(alt: float, az: float) -> tuple[float, float]:
    r    = (90.0 - alt) / 90.0 * _DOME_R
    az_r = math.radians(az)
    return -r * math.sin(az_r), r * math.cos(az_r)


def _radec_to_altaz(
    ra_deg:  np.ndarray,
    dec_deg: np.ndarray,
    lat_deg: float,
    lst_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    H       = np.radians((lst_deg - ra_deg) % 360.0)
    lat_r   = math.radians(lat_deg)
    dec_r   = np.radians(dec_deg)
    sin_alt = math.sin(lat_r) * np.sin(dec_r) + math.cos(lat_r) * np.cos(dec_r) * np.cos(H)
    alt     = np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))
    cos_alt = np.cos(np.radians(alt))
    cos_az  = np.where(
        cos_alt > 1e-6,
        (np.sin(dec_r) - math.sin(lat_r) * sin_alt) / (math.cos(lat_r) * cos_alt + 1e-10),
        1.0,
    )
    az = np.degrees(np.arccos(np.clip(cos_az, -1.0, 1.0)))
    az = np.where(np.sin(H) > 0, 360.0 - az, az)
    return alt, az


@lru_cache(maxsize=1)
def _load_catalog(path: str) -> np.ndarray:
    return np.load(path)


#------------#
# INFO PANEL #
#------------#

class InfoPanel:
    # Manages the click-to-inspect overlay panel: PIL image → GL texture → screen-space quad

    def __init__(self, ctx: moderngl.Context, panel_prog: moderngl.Program):
        self._ctx        = ctx
        self._panel_prog = panel_prog
        self._tex: Optional[moderngl.Texture]     = None
        self._vao: Optional[moderngl.VertexArray] = None

    @property
    def active(self) -> bool:
        return self._tex is not None

    def dismiss(self) -> None:
        if self._tex:
            self._tex.release()
        self._tex = None
        self._vao = None

    def render(self) -> None:
        if self._tex and self._vao:
            self._tex.use()
            self._vao.render(moderngl.TRIANGLE_STRIP)

    def show_state(self, state: "CelestialState", extra: Optional[dict] = None) -> None:
        img  = Image.new("RGBA", (_PANEL_W, _PANEL_H), (10, 11, 20, 225))
        draw = ImageDraw.Draw(img)
        extra = extra or {}

        try:
            font_hd  = ImageFont.truetype(_FONT_PATH,   15)
            font_sm  = ImageFont.truetype(_FONT_PATH,   12)
            font_sym = ImageFont.truetype(_SYMBOL_FONT, 12)
        except Exception:
            font_hd = font_sm = font_sym = ImageFont.load_default()

        val_color = (195, 200, 212, 255)
        lbl_color = (110, 120, 145, 220)

        y = 10
        glyph_str = _strip_var_selector(getattr(state, "glyph", ""))
        draw.text((12, y), glyph_str,       font=font_sym, fill=(220, 218, 200, 255))
        draw.text((28, y), f" {state.name}", font=font_hd,  fill=(220, 218, 200, 255))
        y += 22
        draw.line([(8, y), (_PANEL_W - 8, y)], fill=(45, 50, 70, 200), width=1)
        y += 8

        def row(label: str, val: str, font=None) -> None:
            nonlocal y
            draw.text((12, y), label, font=font_sm,         fill=lbl_color)
            draw.text((90, y), val,   font=font or font_sm, fill=val_color)
            y += 15

        if state.lon is not None:
            try:
                sg, sn = state.sign
                retro  = " Rx" if getattr(state, "retrograde", False) else ""
                row("Sign", f"{_strip_var_selector(sg)} {sn} {state.orb:.1f}°{retro}", font=font_sym)
            except Exception:
                pass

        if state.ra is not None:
            h = state.ra / 15.0
            row("RA / Dec", f"{int(h):02d}h{int((h % 1)*60):02d}m  {state.dec:+.1f}°")  # type: ignore

        try:
            con = state.constellation
            if con:
                row("Constellation", con)
        except Exception:
            pass

        if state.alt is not None:
            row("Alt / Az", f"{state.alt:.1f}° / {state.az:.1f}°")  # type: ignore

        if state.dist is not None:
            row("Distance", f"{state.dist:.4f} AU")

        mag = extra.get("mag") or (f"{state.app_mag:.2f}" if state.app_mag is not None else None)
        if mag:
            row("Magnitude", mag)

        if state.app_diam is not None:
            row("App. Diameter", f"{state.app_diam:.1f}\"")

        if state.elong is not None:
            row("Elongation", f"{state.elong:.1f}°")

        try:
            pt = state.phase
            if pt:
                direction = " (waxing)" if state.phase_waxing is True else (" (waning)" if state.phase_waxing is False else "")
                row("Phase", f"{pt[0]}{direction}")
        except Exception:
            pass

        if state.phase_angle is not None:
            illum = f" / {state.phase_illuminated * 100:.0f}% illum." if state.phase_illuminated is not None else ""
            row("Phase Angle", f"{state.phase_angle:.1f}°{illum}")

        if extra.get("spect"):
            row("Spectral", extra["spect"])

        self._upload(img)

    def show_raw(self, data: dict) -> None:
        img  = Image.new("RGBA", (_PANEL_W, _PANEL_H), (10, 11, 20, 225))
        draw = ImageDraw.Draw(img)
        try:
            font_hd = ImageFont.truetype(_FONT_PATH, 15)
            font_sm = ImageFont.truetype(_FONT_PATH, 12)
        except Exception:
            font_hd = font_sm = ImageFont.load_default()

        glyph = "✦" if data.get("type") == "star" else "◉"
        draw.text((12, 10), f"{glyph}  {data.get('name', '?')}", font=font_hd, fill=(220, 218, 200, 255))
        draw.line([(8, 32), (_PANEL_W - 8, 32)], fill=(45, 50, 70, 200), width=1)

        y = 40
        for key, label in [("constellation", "Constellation"), ("mag", "Magnitude"),
                            ("spect", "Spectral"), ("ci", "B-V Index")]:
            if val := data.get(key):
                draw.text((12, y), label,    font=font_sm, fill=(110, 120, 145, 220))
                draw.text((95, y), str(val), font=font_sm, fill=(195, 200, 212, 255))
                y += 15

        self._upload(img)

    def _upload(self, img: Image.Image) -> None:
        self.dismiss()
        flipped     = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        self._tex   = self._ctx.texture((_PANEL_W, _PANEL_H), 4, flipped.tobytes())
        self._tex.filter = moderngl.LINEAR, moderngl.LINEAR

        _, _, sw, sh = self._ctx.viewport
        pw   = _PANEL_W / sw * 2.0
        ph   = _PANEL_H / sh * 2.0
        x0, y0 = -1.0, -1.0
        x1, y1 = x0 + pw, y0 + ph

        quad = np.array([x0, y0, 0.0, 0.0, x1, y0, 1.0, 0.0,
                         x0, y1, 0.0, 1.0, x1, y1, 1.0, 1.0], dtype="f4")
        vbo  = self._ctx.buffer(quad.tobytes())
        self._vao = self._ctx.vertex_array(self._panel_prog, [(vbo, "2f 2f", "in_pos", "in_uv")])


#-----------#
# DOME VIEW #
#-----------#

class DomeView(BaseGLWindow):
    _TEXT_SPACING = 0.38

    # Class-level config — set by configure(), copied to instance in __init__
    _cfg_lat:        float              = 0.0
    _cfg_lon:        float              = 0.0
    _cfg_jd:         float              = 0.0
    _cfg_mag_limit:  float              = 6.5
    _cfg_brightness: float              = 1.0
    _cfg_planets:    list               = []
    _cfg_fetch_fn:   Optional[Callable] = None
    _cfg_save_path:  Optional[str]      = None
    _cfg_title_str:  str                = ""

    @classmethod
    def configure(
        cls,
        dt:         datetime,
        location:   "Location",
        planets:    list,
        fetch_fn:   Optional[Callable] = None,
        mag_limit:  float              = 6.5,
        brightness: float              = 1.0,
        save_path:  Optional[str]      = None,
        title:      str                = "",
    ) -> None:
        hour              = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
        cls._cfg_jd        = swe.julday(dt.year, dt.month, dt.day, hour)
        cls._cfg_lat       = location.lat
        cls._cfg_lon       = location.lon
        cls._cfg_mag_limit = mag_limit
        cls._cfg_brightness = brightness
        cls._cfg_planets   = planets
        cls._cfg_fetch_fn  = staticmethod(fetch_fn) if fetch_fn is not None else None
        cls._cfg_save_path = save_path
        cls._cfg_title_str = title

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Copy class config to instance
        cls = self.__class__
        self._lat        = cls._cfg_lat
        self._lon        = cls._cfg_lon
        self._jd         = cls._cfg_jd
        self._mag_limit  = cls._cfg_mag_limit
        self._brightness = cls._cfg_brightness
        self._planets    = list(cls._cfg_planets)
        self._fetch_fn   = cls._cfg_fetch_fn
        self._save_path  = cls._cfg_save_path
        self._save_done  = False
        self._title_str  = cls._cfg_title_str

        self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)

        self._star_prog  = self._load_program('star')
        self._panel_prog = self.ctx.program(vertex_shader=_PANEL_VERT, fragment_shader=_PANEL_FRAG)

        v    = _VIEWPORT
        proj = _ortho(-v, v, -v, v)
        for prog in (self._star_prog, self._line_prog, self._glyph_prog):
            prog['proj'].write(proj.tobytes())  # type: ignore
        self._star_prog['u_brightness'] = 1.0  # type: ignore
        self._line_prog['u_line_alpha'] = 1.0  # type: ignore

        self._panel = InfoPanel(self.ctx, self._panel_prog)

        self._star_xy:    np.ndarray       = np.empty((0, 2), dtype=np.float32)
        self._star_radec: np.ndarray       = np.empty((0, 2), dtype=np.float32)
        self._star_names: list[str]        = []
        self._star_mags:  list[float]      = []
        self._star_ci:    list[float]      = []
        self._star_spect: list[str]        = []
        self._planet_xy:    list[tuple[float, float]] = []
        self._planet_names: list[str]      = []

        self._zoom:       float = 1.0
        self._pan_x:      float = 0.0
        self._pan_y:      float = 0.0
        self._mouse_x:    float = 0.0
        self._mouse_y:    float = 0.0
        self._drag_pan:   bool  = False
        self._shift_held: bool  = False

        self._lst:                float = 0.0
        self._ecliptic_vao:       Optional[moderngl.VertexArray] = None
        self._n_ecliptic:         int   = 0
        self._sun_vao:            Optional[moderngl.VertexArray] = None
        self._const_boundary_vao: Optional[moderngl.VertexArray] = None
        self._n_const_boundary:   int   = 0

        self._compute_stars()
        self._build_vaos()

    def _compute_stars(self) -> None:
        self._lst = (swe.sidtime(self._jd) * 15.0 + self._lon) % 360.0

        cat_path = str(Path(_DATA_DIR) / "stars.npy")
        if not Path(cat_path).exists():
            logging.warning("stars.npy not found — run scripts/convert_hyg.py")
            self._star_vbo_data = np.empty((0, 6), dtype=np.float32)
            self._n_stars = 0
            return

        cat  = _load_catalog(cat_path)
        cat  = cat[(cat["mag"] <= self._mag_limit) & (cat["name"] != b"Sol")]
        alt, az = _radec_to_altaz(cat["ra"], cat["dec"], self._lat, self._lst)

        vis = alt > -0.5
        cat, alt, az = cat[vis], alt[vis], az[vis]

        r    = (90.0 - alt) / 90.0 * _DOME_R
        az_r = np.radians(az)
        xs   = (-r * np.sin(az_r)).astype(np.float32)
        ys   = (r * np.cos(az_r)).astype(np.float32)

        rgb   = np.array([_ci_to_rgb(float(c)) for c in cat["ci"]], dtype=np.float32)
        sizes = np.array([_mag_to_size(float(m)) for m in cat["mag"]], dtype=np.float32)

        self._star_vbo_data = np.column_stack([xs, ys, sizes, rgb]).astype(np.float32)
        self._n_stars        = len(xs)
        self._star_xy        = np.column_stack([xs, ys])
        self._star_radec     = np.column_stack([cat["ra"].astype(np.float32), cat["dec"].astype(np.float32)])
        self._star_names     = [n.decode("ascii", errors="replace").strip() for n in cat["name"]]
        self._star_mags      = [float(m) for m in cat["mag"]]
        self._star_ci        = [float(c) for c in cat["ci"]]
        self._star_spect     = [s.decode("ascii", errors="replace").strip() for s in cat["spect"]]

    def _build_vaos(self) -> None:
        # Reset glyph accumulators before rebuild
        self._reset_glyphs()
        self._planet_xy    = []
        self._planet_names = []

        vbo = self.ctx.buffer(self._star_vbo_data.tobytes())
        self._star_vao = self.ctx.vertex_array(
            self._star_prog, [(vbo, "2f 1f 3f", "in_pos", "in_size", "in_color")]
        )

        circ    = _circle_verts(_DOME_R, segments=360)
        ccolors = np.full((len(circ), 4), [0.22, 0.24, 0.34, 0.55], dtype="f4")
        vbo     = self.ctx.buffer(np.hstack([circ, ccolors]).astype("f4").tobytes())
        self._horizon_vao = self.ctx.vertex_array(
            self._line_prog, [(vbo, "2f 4f", "in_pos", "in_color")]
        )

        self._build_ecliptic()

        planet_pts: list[list[float]] = []
        sun_pts:    list[list[float]] = []
        for state in self._planets:
            if state.alt is None or state.az is None or state.alt < 0:
                continue
            x, y       = _project(state.alt, state.az)
            color      = _PLANET_COLORS.get(state.name.lower(), _DEFAULT_PLANET_COLOR)
            size       = _mag_to_size(state.app_mag) if state.app_mag is not None else 9.0
            halo_color = (color[0] * 0.35, color[1] * 0.35, color[2] * 0.35)
            pts        = sun_pts if state.name.lower() == "sun" else planet_pts
            pts.append([x, y, size * 3.2, halo_color[0], halo_color[1], halo_color[2]])
            pts.append([x, y, size,       color[0],       color[1],       color[2]])
            self._planet_xy.append((x, y))
            self._planet_names.append(state.name)
            sym_color: _RGBA = (color[0] * 0.6, color[1] * 0.6, color[2] * 0.6, 0.55)  # type: ignore
            self._add_glyph(state.glyph, x, y, 0.068, sym_color)

        def _make_pt_vao(pts: list) -> Optional[moderngl.VertexArray]:
            if not pts:
                return None
            vbo = self.ctx.buffer(np.array(pts, dtype="f4").tobytes())
            return self.ctx.vertex_array(
                self._star_prog, [(vbo, "2f 1f 3f", "in_pos", "in_size", "in_color")]
            )

        self._planet_vao: Optional[moderngl.VertexArray] = _make_pt_vao(planet_pts)
        self._sun_vao    = _make_pt_vao(sun_pts)

        label_r = _DOME_R + 0.08
        for label, az in [("N", 0), ("E", 90), ("S", 180), ("W", 270)]:
            x = -label_r * math.sin(math.radians(az))
            y =  label_r * math.cos(math.radians(az))
            self._add_text(label, x, y, 0.065, (0.45, 0.5, 0.62, 0.75))

        if self._title_str:
            self._add_text(self._title_str, 0.0, -_VIEWPORT + 0.06, 0.038, (0.35, 0.4, 0.52, 0.65))

        self._build_constellation_boundaries()
        self._build_constellation_labels()
        self._upload_glyphs()

    def _build_ecliptic(self) -> None:
        from atlas.models.celestial_state import SIGNS
        T      = (self._jd - 2451545.0) / 36525.0
        eps    = math.radians(23.439291111 - 0.013004167 * T)
        lons   = np.arange(0, 361, 1.0)
        l_rad  = np.radians(lons)
        ra_deg  = np.degrees(np.arctan2(np.sin(l_rad) * math.cos(eps), np.cos(l_rad))) % 360.0
        dec_deg = np.degrees(np.arcsin(np.clip(np.sin(eps) * np.sin(l_rad), -1.0, 1.0)))
        alt, az = _radec_to_altaz(ra_deg, dec_deg, self._lat, self._lst)
        above   = alt > 0.0

        # Brighten the ecliptic at night, fade toward day
        sun_alt   = next((s.alt for s in self._planets if s.name.lower() == "sun" and s.alt is not None), -18.0)
        night_t   = max(0.0, min(1.0, (-sun_alt - 6.0) / 12.0))  # 0 at day, 1 at night
        ecl_alpha = 0.12 + 0.53 * night_t
        ecl_c: _RGBA = (0.82, 0.75, 0.38, ecl_alpha)
        segs: list[float] = []
        for i in range(len(lons) - 1):
            if above[i] and above[i + 1]:
                x0, y0 = _project(float(alt[i]),   float(az[i]))
                x1, y1 = _project(float(alt[i+1]), float(az[i+1]))
                segs += [x0, y0, *ecl_c, x1, y1, *ecl_c]

        if segs:
            vbo = self.ctx.buffer(np.array(segs, dtype="f4").tobytes())
            self._ecliptic_vao = self.ctx.vertex_array(
                self._line_prog, [(vbo, "2f 4f", "in_pos", "in_color")]
            )
            self._n_ecliptic = len(segs) // 6
        else:
            self._ecliptic_vao = None
            self._n_ecliptic   = 0

        # Zodiac glyphs along the ecliptic — brighter and larger than the line itself
        glyph_c: _RGBA = (0.82, 0.75, 0.38, min(1.0, ecl_alpha * 1.6 + 0.10))
        for i, (glyph, _) in enumerate(SIGNS):
            lon = i * 30.0 + 15.0
            l   = math.radians(lon)
            ra  = math.degrees(math.atan2(math.sin(l) * math.cos(eps), math.cos(l))) % 360.0
            dec = math.degrees(math.asin(max(-1.0, min(1.0, math.sin(eps) * math.sin(l)))))
            a, z = _radec_to_altaz(np.array([ra]), np.array([dec]), self._lat, self._lst)
            if float(a[0]) > 3.0:
                x, y = _project(float(a[0]), float(z[0]))
                self._add_glyph(glyph, x, y, 0.068, glyph_c)

    def _build_constellation_labels(self) -> None:
        dat_path = str(Path(_DATA_DIR) / "constellations.dat")
        if not Path(dat_path).exists():
            return
        centers = _load_constellation_centers(dat_path)

        sun_alt   = next((s.alt for s in self._planets if s.name.lower() == "sun" and s.alt is not None), -18.0)
        night_t   = max(0.0, min(1.0, (-sun_alt - 6.0) / 12.0))
        lbl_alpha = 0.15 + 0.70 * night_t
        lbl_c: _RGBA = (1.0, 1.0, 1.0, lbl_alpha)

        for abbr, (ra_deg, dec_deg) in centers.items():
            a, z = _radec_to_altaz(np.array([ra_deg]), np.array([dec_deg]), self._lat, self._lst)
            if float(a[0]) > 8.0:
                x, y = _project(float(a[0]), float(z[0]))
                self._add_text(abbr, x, y, 0.048, lbl_c)

    def _build_constellation_boundaries(self) -> None:
        dat_path = str(Path(_DATA_DIR) / "constellations.dat")
        if not Path(dat_path).exists():
            return

        from collections import defaultdict

        strips = []
        with open(dat_path) as f:
            for line in f:
                parts = line.split()
                if len(parts) == 4:
                    strips.append((float(parts[0]), float(parts[1]), float(parts[2]), parts[3]))
        strips.sort(key=lambda s: (s[2], s[0]))

        dec_vals = sorted(set(s[2] for s in strips))
        by_dec: dict = defaultdict(list)
        for ra_l, ra_h, dec_l, abbr in strips:
            by_dec[dec_l].append((ra_l, ra_h, abbr))
        for dec in by_dec:
            by_dec[dec].sort()

        sun_alt   = next((s.alt for s in self._planets if s.name.lower() == "sun" and s.alt is not None), -18.0)
        night_t   = max(0.0, min(1.0, (-sun_alt - 6.0) / 12.0))
        bnd_alpha = 0.04 + 0.18 * night_t
        c         = (1.0, 1.0, 1.0, bnd_alpha)

        line_segs: list[list[float]] = []

        def _proj_seg(ra1_h: float, d1: float, ra2_h: float, d2: float) -> None:
            a1, z1 = _radec_to_altaz(np.array([ra1_h * 15.0]), np.array([d1]), self._lat, self._lst)
            a2, z2 = _radec_to_altaz(np.array([ra2_h * 15.0]), np.array([d2]), self._lat, self._lst)
            if float(a1[0]) > 0.0 and float(a2[0]) > 0.0:
                x1, y1 = _project(float(a1[0]), float(z1[0]))
                x2, y2 = _project(float(a2[0]), float(z2[0]))
                line_segs.append([x1, y1, *c, x2, y2, *c])

        # Horizontal boundaries: at each dec level, only draw where the constellation
        # above differs from the constellation below (i.e. an actual boundary, not interior)
        for i in range(1, len(dec_vals)):
            dec      = dec_vals[i]
            prev_dec = dec_vals[i - 1]
            for ra_l, ra_h, abbr in by_dec[dec]:
                for p_ra_l, p_ra_h, p_abbr in by_dec[prev_dec]:
                    ol = max(ra_l, p_ra_l)
                    oh = min(ra_h, p_ra_h)
                    if ol < oh - 1e-4 and p_abbr != abbr:
                        step, ra = 0.5, ol
                        while ra < oh - 1e-4:
                            nr = min(ra + step, oh)
                            _proj_seg(ra, dec, nr, dec)
                            ra = nr

        # Vertical boundaries: adjacent strips at the same dec level with different constellations.
        # Height of each vertical segment = from this dec to the next dec level.
        for i, dec in enumerate(dec_vals):
            next_dec = dec_vals[i + 1] if i + 1 < len(dec_vals) else dec + 2.0
            for j in range(len(by_dec[dec]) - 1):
                _, ra_h1, abbr1 = by_dec[dec][j]
                ra_l2, _,  abbr2 = by_dec[dec][j + 1]
                if abs(ra_h1 - ra_l2) < 1e-3 and abbr1 != abbr2:
                    step, d = 1.0, dec
                    while d < next_dec - 1e-4:
                        nd = min(d + step, next_dec)
                        _proj_seg(ra_h1, d, ra_h1, nd)
                        d = nd

        if line_segs:
            data = np.array(line_segs, dtype="f4").reshape(-1, 6)
            vbo  = self.ctx.buffer(data.tobytes())
            self._const_boundary_vao: Optional[moderngl.VertexArray] = self.ctx.vertex_array(
                self._line_prog, [(vbo, "2f 4f", "in_pos", "in_color")]
            )
            self._n_const_boundary = len(data)
        else:
            self._const_boundary_vao = None
            self._n_const_boundary   = 0

    def _sky_color(self) -> tuple[float, float, float]:
        sun_alt = next(
            (s.alt for s in self._planets if s.name.lower() == "sun" and s.alt is not None), None
        )
        if sun_alt is None or sun_alt < -18.0:
            return (0.01, 0.01, 0.04)
        if sun_alt < -12.0:
            t = (sun_alt + 18.0) / 6.0
            return (0.01 + 0.04 * t, 0.01 + 0.02 * t, 0.04 + 0.06 * t)
        if sun_alt < -6.0:
            t = (sun_alt + 12.0) / 6.0
            return (0.05 + 0.10 * t, 0.03 + 0.05 * t, 0.10 + 0.08 * t)
        if sun_alt < 0.0:
            t = (sun_alt + 6.0) / 6.0
            return (0.15 + 0.25 * t, 0.08 + 0.22 * t, 0.18 + 0.17 * t)
        if sun_alt < 10.0:
            t = sun_alt / 10.0
            return (0.40 + 0.16 * t, 0.30 + 0.27 * t, 0.35 + 0.30 * t)
        t = min(1.0, (sun_alt - 10.0) / 30.0)
        return (0.56 + 0.14 * t, 0.57 + 0.23 * t, 0.65 + 0.25 * t)

    def on_render(self, time: float, frame_time: float) -> None:
        r, g, b = self._sky_color()
        self.ctx.clear(r, g, b)

        sun_alt = next(
            (s.alt for s in self._planets if s.name.lower() == "sun" and s.alt is not None), -18.0
        )
        star_brightness   = max(0.08, min(2.0, (-sun_alt) / 6.0 * self._brightness))
        planet_brightness = max(0.25, min(1.0, (-sun_alt + 6.0) / 12.0))
        sky_lum = sum(self._sky_color()) / 3.0
        self._line_prog["u_line_alpha"] = 1.0 + sky_lum * 3.5  # type: ignore

        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
        self._star_prog["u_brightness"] = star_brightness  # type: ignore
        self._star_vao.render(moderngl.POINTS, vertices=self._n_stars)
        if self._planet_vao:
            self._star_prog["u_brightness"] = planet_brightness  # type: ignore
            self._planet_vao.render(moderngl.POINTS)
        if self._sun_vao:
            self._star_prog["u_brightness"] = 1.0  # type: ignore
            self._sun_vao.render(moderngl.POINTS)

        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self._horizon_vao.render(moderngl.LINES)
        if self._const_boundary_vao:
            self._const_boundary_vao.render(moderngl.LINES, vertices=self._n_const_boundary)
        if self._ecliptic_vao:
            self._ecliptic_vao.render(moderngl.LINES, vertices=self._n_ecliptic)
        if self._sym_glyph_vao:
            self._sym_atlas.texture.use()
            self._sym_glyph_vao.render(moderngl.TRIANGLES)
        if self._txt_glyph_vao:
            self._txt_atlas.texture.use()
            self._txt_glyph_vao.render(moderngl.TRIANGLES)

        self._panel.render()

        if self._save_path and not self._save_done:
            self._save_done = True
            self._save_screenshot(self._save_path)
            self.wnd.close()

    def on_mouse_press_event(self, x: float, y: float, button: int) -> None:
        if button == 1 and self._shift_held:
            self._drag_pan = True
            return
        if button != 1:
            return
        cx, cy       = self._pixel_to_chart(x, y)
        star_click_r = _CLICK_RADIUS / self._zoom
        plan_click_r = star_click_r * 2.5

        for i, (px, py) in enumerate(self._planet_xy):
            if math.hypot(cx - px, cy - py) < plan_click_r:
                self._select_planet(self._planet_names[i])
                return

        if self._n_stars > 0:
            diff = self._star_xy - np.array([cx, cy], dtype=np.float32)
            dist = np.hypot(diff[:, 0], diff[:, 1])
            idx  = int(np.argmin(dist))
            if dist[idx] < star_click_r:
                self._select_star(idx)
                return

        self._panel.dismiss()

    def on_key_event(self, key, action, modifiers) -> None:  # type: ignore
        self._shift_held = bool(modifiers.shift)
        if action == self.wnd.keys.ACTION_PRESS and key == self.wnd.keys.ESCAPE:
            if self._panel.active:
                self._panel.dismiss()
            else:
                self.wnd.close()

    def _select_planet(self, name: str) -> None:
        if self._fetch_fn:
            try:
                self._panel.show_state(self._fetch_fn(name))
                return
            except Exception as e:
                logging.warning(f"fetch failed for '{name}': {e}")
        self._panel.show_raw({"name": name, "type": "planet"})

    def _select_star(self, idx: int) -> None:
        from atlas.utils.constellation import identify_constellation
        name = self._star_names[idx]
        con  = None
        if idx < len(self._star_radec):
            ra, dec = float(self._star_radec[idx, 0]), float(self._star_radec[idx, 1])
            con = identify_constellation(ra, dec)
        extra = {
            "mag":           f"{self._star_mags[idx]:.2f}",
            "ci":            f"{self._star_ci[idx]:.3f}",
            "spect":         self._star_spect[idx],
            "constellation": con or "",
        }
        if self._fetch_fn and name and not name.startswith("HYG-"):
            try:
                self._panel.show_state(self._fetch_fn(name), extra=extra)
                return
            except Exception:
                pass
        self._panel.show_raw({"name": name or "Unknown", "type": "star", **extra})

    def _pixel_to_chart(self, px: float, py: float) -> tuple[float, float]:
        w, h  = self.wnd.size
        side  = min(w, h)
        ox    = (w - side) / 2
        oy    = (h - side) / 2
        ndc_x = ((px - ox) / side) * 2.0 - 1.0
        ndc_y = 1.0 - ((py - oy) / side) * 2.0
        half  = _VIEWPORT / self._zoom
        return self._pan_x + ndc_x * half, self._pan_y + ndc_y * half

    def _update_projection(self) -> None:
        half = _VIEWPORT / self._zoom
        proj = _ortho(
            self._pan_x - half, self._pan_x + half,
            self._pan_y - half, self._pan_y + half,
        )
        for prog in (self._star_prog, self._line_prog, self._glyph_prog):
            prog["proj"].write(proj.tobytes())  # type: ignore

    def on_mouse_position_event(self, x: float, y: float, dx: float, dy: float) -> None:  # type: ignore
        self._mouse_x = x
        self._mouse_y = y

    def on_mouse_scroll_event(self, x_offset: float, y_offset: float) -> None:  # type: ignore
        cx, cy   = self._pixel_to_chart(self._mouse_x, self._mouse_y)
        half_old = _VIEWPORT / self._zoom
        factor   = 1.15 if y_offset > 0 else 1.0 / 1.15
        new_zoom = max(1.0, min(30.0, self._zoom * factor))

        if new_zoom <= 1.0:
            self._zoom  = 1.0
            self._pan_x = 0.0
            self._pan_y = 0.0
        else:
            half_new    = _VIEWPORT / new_zoom
            ndc_x       = (cx - self._pan_x) / half_old
            ndc_y       = (cy - self._pan_y) / half_old
            self._pan_x = cx - ndc_x * half_new
            self._pan_y = cy - ndc_y * half_new
            self._zoom  = new_zoom

        self._update_projection()

    def on_mouse_drag_event(self, x: float, y: float, dx: float, dy: float) -> None:  # type: ignore
        self._mouse_x = x
        self._mouse_y = y
        if self._drag_pan:
            w, h  = self.wnd.size
            side  = min(w, h)
            half  = _VIEWPORT / self._zoom
            self._pan_x -= (dx / side) * 2.0 * half
            self._pan_y += (dy / side) * 2.0 * half
            self._update_projection()

    def on_mouse_release_event(self, x: float, y: float, button: int) -> None:  # type: ignore
        if button == 1:
            self._drag_pan = False
