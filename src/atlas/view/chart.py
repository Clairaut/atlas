# Standard Modules
import math
from typing import Any, Optional
from dataclasses import dataclass

# Internal Modules
from atlas.view.base import (
    BaseGLWindow, GlyphAtlas, _RGBA, _ortho, _circle_verts, _glyph_quad, _strip_var_selector,
)

# External Modules
import moderngl
import moderngl_window
import numpy as np
from PIL import Image


#-----------#
# CONSTANTS #
#-----------#

def _hex(h: str) -> _RGBA:
    h = h.lstrip('#')
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, 1.0)


ZODIAC_SYMBOLS = ['♈', '♉', '♊', '♋', '♌', '♍', '♎', '♏', '♐', '♑', '♒', '♓']

ZODIAC_COLORS: list[_RGBA] = [
    _hex('#756AB6'), _hex('#AC87C5'), _hex('#E0AED0'), _hex('#FFE5E5'),
    _hex('#756AB6'), _hex('#AC87C5'), _hex('#E0AED0'), _hex('#FFE5E5'),
    _hex('#756AB6'), _hex('#AC87C5'), _hex('#E0AED0'), _hex('#FFE5E5'),
]

CELESTIAL_COLORS: dict[str, _RGBA] = {
    'sun':     _hex('#F6FFC1'), 'moon':    _hex('#CCCCCC'), 'mercury': _hex('#B4CDF3'),
    'venus':   _hex('#FFC9E9'), 'mars':    _hex('#CBC9FF'), 'jupiter': _hex('#F3D8B4'),
    'saturn':  _hex('#EDBAE1'), 'uranus':  _hex('#B4EDF3'), 'neptune': _hex('#AFBEE7'),
    'pluto':   _hex('#CAA6F0'), 'lilith':  _hex('#808080'),
    'selena':  (1.0, 1.0, 1.0, 1.0), 'rahu': (1.0, 1.0, 1.0, 1.0),
}

WHITE:     _RGBA = (1.0, 1.0, 1.0, 1.0)
DIM_WHITE: _RGBA = (1.0, 1.0, 1.0, 0.35)
DIM_LINE:  _RGBA = (1.0, 1.0, 1.0, 0.20)

ASPECT_COLORS: dict[str, _RGBA] = {
    'conjunction': (1.0, 1.0, 1.0, 0.50), 'opposition': _hex('#756AB6'),
    'trine':       _hex('#AC87C5'),         'square':     _hex('#E0AED0'),
    'sextile':     _hex('#FFE5E5'),
}

ASPECT_WEIGHTS: dict[str, str] = {
    'opposition': 'hard', 'square': 'med', 'trine': 'med',
    'sextile':    'soft', 'conjunction': 'soft',
}


#----------#
# GEOMETRY #
#----------#

def _line_verts(angle: float, r1: float, r2: float) -> np.ndarray:
    return np.array([
        [r1 * math.cos(angle), r1 * math.sin(angle)],
        [r2 * math.cos(angle), r2 * math.sin(angle)],
    ], dtype='f4')


#------------------#
# LABEL COLLISION  #
#------------------#

@dataclass
class _LabelNode:
    lon:      float
    chart_lon: float
    data:     Any


def _resolve_collisions(nodes: list[_LabelNode], tolerance: float = 5.0, max_iters: int = 10000) -> list[_LabelNode]:
    for n in nodes:
        n.chart_lon = n.lon

    for _ in range(max_iters):
        nodes.sort(key=lambda n: n.chart_lon)
        moved = False

        for i in range(len(nodes) - 1):
            a, b = nodes[i], nodes[i + 1]
            diff = (b.chart_lon - a.chart_lon) % 360
            if diff > 180:
                diff = 360 - diff
            if diff < tolerance:
                adj = (tolerance - diff) / 2
                a.chart_lon = (a.chart_lon - adj) % 360
                b.chart_lon = (b.chart_lon + adj) % 360
                moved = True

        first, last = nodes[0], nodes[-1]
        wrap = (first.chart_lon - last.chart_lon) % 360
        if wrap > 180:
            wrap = 360 - wrap
        if wrap < tolerance:
            adj = (tolerance - wrap) / 2
            first.chart_lon = (first.chart_lon + adj) % 360
            last.chart_lon  = (last.chart_lon  - adj) % 360
            moved = True

        if not moved:
            break

    return nodes


#------------#
# BASE CHART #
#------------#

class Chart(BaseGLWindow):
    VIEWPORT = 1.2

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        v    = self.VIEWPORT
        proj = _ortho(-v, v, -v, v)
        self._line_prog['proj'].write(proj.tobytes())   # type: ignore
        self._line_prog['u_line_alpha'] = 1.0           # type: ignore
        self._glyph_prog['proj'].write(proj.tobytes())  # type: ignore

        self._line_pts:     list[list[float]] = []
        self._asp_hard_pts: list[list[float]] = []
        self._asp_med_pts:  list[list[float]] = []

        self._line_vao:     Optional[moderngl.VertexArray] = None
        self._asp_hard_vao: Optional[moderngl.VertexArray] = None
        self._asp_med_vao:  Optional[moderngl.VertexArray] = None

    def _add_line(self, angle: float, r1: float, r2: float, color: _RGBA) -> None:
        v = _line_verts(angle, r1, r2)
        r, g, b, a = color
        self._line_pts.append([float(v[0][0]), float(v[0][1]), r, g, b, a])
        self._line_pts.append([float(v[1][0]), float(v[1][1]), r, g, b, a])

    def _add_segment(self, x1: float, y1: float, x2: float, y2: float, color: _RGBA, weight: str = 'soft') -> None:
        r, g, b, a = color
        pt1 = [x1, y1, r, g, b, a]
        pt2 = [x2, y2, r, g, b, a]
        match weight:
            case 'hard':
                self._asp_hard_pts.append(pt1)
                self._asp_hard_pts.append(pt2)
            case 'med':
                self._asp_med_pts.append(pt1)
                self._asp_med_pts.append(pt2)
            case _:
                self._line_pts.append(pt1)
                self._line_pts.append(pt2)

    def _add_circle(self, radius: float, color: _RGBA = WHITE) -> None:
        pairs = _circle_verts(radius)
        r, g, b, a = color
        for i in range(0, len(pairs), 2):
            self._line_pts.append([float(pairs[i][0]),   float(pairs[i][1]),   r, g, b, a])
            self._line_pts.append([float(pairs[i+1][0]), float(pairs[i+1][1]), r, g, b, a])

    def _reset_geometry(self) -> None:
        self._reset_glyphs()
        for vao in (self._line_vao, self._asp_hard_vao, self._asp_med_vao):
            if vao:
                vao.release()
        self._line_vao     = None
        self._asp_hard_vao = None
        self._asp_med_vao  = None
        self._line_pts     = []
        self._asp_hard_pts = []
        self._asp_med_pts  = []

    def _build_line_vao(self, pts: list[list[float]]) -> Optional[moderngl.VertexArray]:
        if not pts:
            return None
        data = np.array(pts, dtype='f4')
        vbo  = self.ctx.buffer(data.tobytes())
        return self.ctx.vertex_array(self._line_prog, [(vbo, '2f 4f', 'in_pos', 'in_color')])

    def _upload_geometry(self) -> None:
        self._line_vao     = self._build_line_vao(self._line_pts)
        self._asp_hard_vao = self._build_line_vao(self._asp_hard_pts)
        self._asp_med_vao  = self._build_line_vao(self._asp_med_pts)
        self._upload_glyphs()

    def on_render(self, time: float, frame_time: float) -> None:
        if not hasattr(self, '_debug_printed'):
            self._debug_printed = True
            print(f"[debug] wnd.size={self.wnd.size}  buffer_size={self.wnd.buffer_size}  pixel_ratio={self.wnd.pixel_ratio}  viewport={self.ctx.viewport}")
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)

        if self._line_vao:
            self._line_vao.render(moderngl.LINES)

        if self._asp_med_vao:
            self.ctx.line_width = 1.5
            self._asp_med_vao.render(moderngl.LINES)
        if self._asp_hard_vao:
            self.ctx.line_width = 2.5
            self._asp_hard_vao.render(moderngl.LINES)
        self.ctx.line_width = 1.0

        if self._sym_glyph_vao:
            self._sym_atlas.texture.use(location=0)
            self._glyph_prog['tex'] = 0
            self._sym_glyph_vao.render(moderngl.TRIANGLES)

        if self._txt_glyph_vao:
            self._txt_atlas.texture.use(location=0)
            self._glyph_prog['tex'] = 0
            self._txt_glyph_vao.render(moderngl.TRIANGLES)

        if self._save_path and not self._save_done:
            self._save_done = True
            self._save_screenshot(self._save_path)
            self.wnd.close()


#--------------#
# RADIX CHART  #
#--------------#

class RadixChart(Chart):
    title = "Radix Chart"

    # Class-level config — set by configure(), copied to instance in __init__
    _cfg_cusps:     list[float] = []
    _cfg_celestials: list       = []
    _cfg_aspects:   list        = []
    _cfg_title:     str         = "Radix Chart"
    _cfg_save_path: Optional[str] = None

    R_INNER     = 0.30
    R_HOUSE_LBL = 0.35
    R_MID       = 0.40
    R_OUTER     = 0.80
    R_RIM       = 1.00

    GLYPH_OFF  = 0.08
    RETRO_OFF  = 0.14
    SIGN_OFF   = 0.205
    ORB_OFF    = 0.275
    GLYPH_SIZE = 0.088
    TEXT_SIZE  = 0.062

    @classmethod
    def configure(cls, cusps: list[float], celestials: list, aspects: list = [],
                  title: str = "Radix Chart", save_path: Optional[str] = None) -> None:
        cls._cfg_cusps      = cusps
        cls._cfg_celestials = celestials
        cls._cfg_aspects    = aspects
        cls._cfg_title      = title
        cls._cfg_save_path  = save_path

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Copy class config to instance — guard lets LiveRadixChart._fetch_data take priority
        if not hasattr(self, '_cusps'):
            self._cusps      = list(self.__class__._cfg_cusps)
            self._celestials = list(self.__class__._cfg_celestials)
            self._aspects    = list(self.__class__._cfg_aspects)
        self._chart_title = self.__class__._cfg_title
        self._save_path   = self.__class__._cfg_save_path
        self._save_done   = False

        self._base_rad = math.radians(self._cusps[0]) - math.pi
        self._mc_rad   = math.radians(self._cusps[9]) - self._base_rad
        self._build()
        self._upload_geometry()

    def _build(self) -> None:
        self._build_base()
        self._build_zodiac()
        self._build_houses()
        self._build_aspects()
        self._build_celestials()

    def _build_base(self) -> None:
        for r in [self.R_INNER, self.R_MID, self.R_OUTER, self.R_RIM]:
            self._add_circle(r, WHITE)
        self._add_text(self._chart_title, 0.0, 1.1, self.TEXT_SIZE * 0.8, WHITE)

        one_deg = np.linspace(0, 2 * math.pi, 360, endpoint=False) + math.radians(15) - self._base_rad
        for angle in one_deg:
            self._add_line(angle, self.R_OUTER, self.R_OUTER + 0.020, DIM_LINE)

        ten_deg = np.linspace(0, 2 * math.pi, 36, endpoint=False) + math.radians(15) - self._base_rad
        for angle in ten_deg:
            self._add_line(angle, self.R_OUTER, self.R_OUTER + 0.030, DIM_WHITE)

    def _build_zodiac(self) -> None:
        for i in range(12):
            boundary = math.radians(i * 30) - self._base_rad
            mid      = boundary + math.radians(15)
            r_mid    = (self.R_OUTER + self.R_RIM) / 2
            self._add_line(boundary, self.R_OUTER, self.R_RIM, DIM_WHITE)
            x = r_mid * math.cos(mid)
            y = r_mid * math.sin(mid)
            self._add_glyph(ZODIAC_SYMBOLS[i], x, y, self.GLYPH_SIZE, ZODIAC_COLORS[i])

    def _build_houses(self) -> None:
        for i, cusp_lon in enumerate(self._cusps):
            next_lon = self._cusps[(i + 1) % 12]
            self._add_line(math.radians(cusp_lon) - self._base_rad, self.R_INNER, self.R_OUTER, DIM_LINE)

            diff = next_lon - cusp_lon
            if diff > 180:    diff -= 360
            elif diff < -180: diff += 360
            mid_angle = math.radians(cusp_lon + diff / 2) - self._base_rad
            r_lbl     = (self.R_INNER + self.R_MID) / 2
            self._add_text(str(i + 1), r_lbl * math.cos(mid_angle), r_lbl * math.sin(mid_angle), self.TEXT_SIZE * 0.75, DIM_WHITE)

        axes = [
            (math.pi,                "ASC"),
            (0.0,                    "DSC"),
            (self._mc_rad,           "MC"),
            (self._mc_rad + math.pi, "IC"),
        ]
        r_lbl = (self.R_INNER + self.R_MID) / 2
        for angle, label in axes:
            self._add_line(angle, self.R_MID, self.R_OUTER, WHITE)
            self._add_text(label, r_lbl * math.cos(angle), r_lbl * math.sin(angle), self.TEXT_SIZE * 0.70, WHITE)

    def _build_aspects(self) -> None:
        for aspect in self._aspects:
            color  = ASPECT_COLORS.get(aspect.name, DIM_WHITE)
            weight = ASPECT_WEIGHTS.get(aspect.name, 'soft')
            if aspect.body_one.lon and aspect.body_two.lon:
                ang1 = math.radians(aspect.body_one.lon) - self._base_rad
                ang2 = math.radians(aspect.body_two.lon) - self._base_rad
                x1 = self.R_INNER * math.cos(ang1)
                y1 = self.R_INNER * math.sin(ang1)
                x2 = self.R_INNER * math.cos(ang2)
                y2 = self.R_INNER * math.sin(ang2)
                self._add_segment(x1, y1, x2, y2, color, weight)

    def _build_celestials(self) -> None:
        if not self._celestials:
            return
        nodes    = [_LabelNode(lon=cel.lon, chart_lon=cel.lon, data=cel)
                    for cel in self._celestials if cel.lon is not None]
        resolved = _resolve_collisions(nodes)

        for node in resolved:
            cel       = node.data
            tick_ang  = math.radians(cel.lon) - self._base_rad
            label_ang = math.radians(node.chart_lon) - self._base_rad
            lx = math.cos(label_ang)
            ly = math.sin(label_ang)
            cel_color = CELESTIAL_COLORS.get(cel.name.lower(), WHITE)

            self._add_line(tick_ang, self.R_OUTER - 0.025, self.R_OUTER, cel_color)
            r = self.R_OUTER - self.GLYPH_OFF
            self._add_glyph(cel.glyph, lx * r, ly * r, self.GLYPH_SIZE, cel_color)

            try:
                if cel.retrograde:
                    r = self.R_OUTER - self.RETRO_OFF
                    self._add_glyph('℞', lx * r, ly * r, self.TEXT_SIZE, (*cel_color[:3], 0.8))
            except (ValueError, AttributeError):
                pass

            try:
                sign_glyph, _ = cel.sign
                r = self.R_OUTER - self.SIGN_OFF
                self._add_glyph(sign_glyph, lx * r, ly * r, self.GLYPH_SIZE * 0.82, cel_color)
            except (ValueError, TypeError, AttributeError):
                pass

            try:
                r = self.R_OUTER - self.ORB_OFF
                self._add_text(f"{round(cel.orb)}°", lx * r, ly * r, self.TEXT_SIZE * 0.65, DIM_WHITE)
            except (ValueError, TypeError, AttributeError):
                pass


#--------------#
# LIVE CHART   #
#--------------#

class LiveRadixChart(RadixChart):
    title = "Live Chart"

    import time as _time_mod

    UPDATE_INTERVAL: float = 10.0

    # Class-level config — set by configure_live(), copied to instance in __init__
    _cfg_atlas:    Any       = None
    _cfg_location: Any       = None
    _cfg_zodiac:   str       = "tropical"
    _cfg_targets:  list[str] = []

    @classmethod
    def configure_live(cls, atlas: Any, location: Any, zodiac: str, targets: list[str]) -> None:
        cls._cfg_atlas    = atlas
        cls._cfg_location = location
        cls._cfg_zodiac   = zodiac
        cls._cfg_targets  = targets

    def __init__(self, **kwargs):
        cls = self.__class__
        self._atlas     = cls._cfg_atlas
        self._location  = cls._cfg_location
        self._zodiac    = cls._cfg_zodiac
        self._targets   = list(cls._cfg_targets)
        self._prev_cusps: list[float] = []
        self._fetch_data()
        self._last_update: float = self._time_mod.monotonic()
        super().__init__(**kwargs)

    def _fetch_data(self) -> None:
        from datetime import datetime
        from atlas.utils.chrono import convert_to_utc

        now = convert_to_utc(datetime.now(), self._location)
        self.__class__.title = datetime.now().strftime("Live  —  %Y-%m-%d  %H:%M:%S")

        celestials = []
        for target in self._targets:
            try:
                state = self._atlas.build_celestial_state(
                    dt         = now,
                    location   = self._location,
                    target     = target,
                    zodiac     = self._zodiac,
                    properties = ["position"],
                    systems    = ["ecliptic"],
                )
                celestials.append(state)
            except Exception:
                pass

        cusps = self._atlas.build_houses(dt=now, location=self._location, zodiac=self._zodiac)
        self._prev_cusps = list(getattr(self, '_cusps', []))
        self._cusps      = cusps
        self._celestials = celestials

    def _get_step_secs(self) -> float:
        return self.__class__.UPDATE_INTERVAL

    def _rebuild_interpolated(self, t: float) -> None:
        from copy import copy
        from atlas.models.aspect import build_aspects

        step_days = self._get_step_secs() / 86400.0
        interp    = []
        for c in self._celestials:
            if t > 0.0 and c.lon is not None and c.dlon is not None:
                ci     = copy(c)
                ci.lon = (c.lon + c.dlon * step_days * t) % 360
                interp.append(ci)
            else:
                interp.append(c)

        prev = self._prev_cusps if self._prev_cusps else self._cusps
        interp_cusps = [
            (prev[i] + ((self._cusps[i] - prev[i] + 180) % 360 - 180) * t) % 360.0
            for i in range(len(self._cusps))
        ]

        orig_celestials, orig_cusps, orig_aspects = self._celestials, self._cusps, self._aspects
        self._celestials = interp
        self._cusps      = interp_cusps
        self._aspects    = build_aspects(interp)
        self._reset_geometry()
        self._base_rad = math.radians(interp_cusps[0]) - math.pi
        self._mc_rad   = math.radians(interp_cusps[9]) - self._base_rad
        self._build()
        self._upload_geometry()
        self._celestials, self._cusps, self._aspects = orig_celestials, orig_cusps, orig_aspects

    def on_render(self, time: float, frame_time: float) -> None:
        now     = self._time_mod.monotonic()
        elapsed = now - self._last_update
        if elapsed >= self.UPDATE_INTERVAL:
            self._last_update = now
            self._fetch_data()
            elapsed = 0.0
        t = min(elapsed / self.UPDATE_INTERVAL, 1.0) if self.UPDATE_INTERVAL > 0 else 1.0
        self._rebuild_interpolated(t)
        super().on_render(time, frame_time)


#----------------#
# PLAYBACK CHART #
#----------------#

class PlaybackChart(LiveRadixChart):
    title = "Playback Chart"

    import time as _time_mod

    UPDATE_INTERVAL: float = 1.0

    # Class-level config — set by configure_playback(), copied to instance in __init__
    _cfg_start_dt:    Any          = None
    _cfg_end_dt:      Any          = None
    _cfg_play_step:   Any          = None
    _cfg_total_steps: int          = 1
    _cfg_ff_speed_max: int         = 1
    _cfg_video_path:  Optional[str] = None

    @classmethod
    def configure_playback(cls, atlas: Any, location: Any, zodiac: str, targets: list[str],
                           start_dt: Any, end_dt: Any, step: Any, speed: float = 1.0,
                           save_path: Optional[str] = None) -> None:
        cls.configure_live(atlas=atlas, location=location, zodiac=zodiac, targets=targets)
        cls._cfg_start_dt   = start_dt
        cls._cfg_end_dt     = end_dt
        cls._cfg_play_step  = step
        cls._cfg_video_path = save_path
        cls.UPDATE_INTERVAL = 1.0 / max(speed, 0.01)

        total_secs         = (end_dt - start_dt).total_seconds()
        step_secs          = step.total_seconds()
        cls._cfg_total_steps  = max(1, int(total_secs / step_secs) + 1)
        cls._cfg_ff_speed_max = max(1, int(36000 / step_secs))

    def __init__(self, **kwargs):
        cls = self.__class__
        self._start_dt     = cls._cfg_start_dt
        self._end_dt       = cls._cfg_end_dt
        self._play_step    = cls._cfg_play_step
        self._current_dt   = cls._cfg_start_dt
        self._current_step = 0
        self._total_steps  = cls._cfg_total_steps
        self._paused       = False
        self._ff_speed     = 1
        self._ff_speed_prev = 0
        self._ff_speed_max = cls._cfg_ff_speed_max
        self._video_path   = cls._cfg_video_path
        self._frame_buffer: list = []
        super().__init__(**kwargs)

    def _update_title(self, dt: Any = None, step: int = 0) -> None:
        dt    = dt or self._current_dt
        pct   = int(step / self._total_steps * 100)
        speed = f"  {self._ff_speed}x" if self._ff_speed > 1 else ""
        self.__class__.title = dt.strftime(f"Playback  —  %Y-%m-%d  %H:%M  [{step}/{self._total_steps}  {pct}%]{speed}")

    def _load_at(self, dt: Any, step: int) -> None:
        self._update_title(dt, step)
        celestials = []
        for target in self._targets:
            try:
                state = self._atlas.build_celestial_state(
                    dt=dt, location=self._location, target=target,
                    zodiac=self._zodiac, properties=["position"], systems=["ecliptic"],
                )
                celestials.append(state)
            except Exception:
                pass
        cusps = self._atlas.build_houses(dt=dt, location=self._location, zodiac=self._zodiac)
        self._prev_cusps = list(self._cusps)
        self._cusps      = cusps
        self._celestials = celestials

    def _fetch_data(self) -> None:
        if not getattr(self, '_current_dt', None):
            super()._fetch_data()
            return
        dt  = self._current_dt
        cur = self._current_step
        self._load_at(dt, cur)
        skip    = self._ff_speed
        next_dt = dt + self._play_step * skip
        if next_dt <= self._end_dt:
            self._current_dt   = next_dt
            self._current_step = cur + skip

    def _step(self, direction: int) -> None:
        if self._current_dt is None:
            return
        new_dt   = self._current_dt + self._play_step * direction
        new_dt   = max(self._start_dt, min(new_dt, self._end_dt))
        new_step = round((new_dt - self._start_dt).total_seconds() / self._play_step.total_seconds())
        new_step = max(0, min(new_step, self._total_steps - 1))
        self._current_dt   = new_dt
        self._current_step = new_step
        self._load_at(new_dt, new_step)
        self._rebuild_interpolated(0.0)

    def on_key_event(self, key: Any, action: Any, modifiers: Any) -> None:
        if action != self.wnd.keys.ACTION_PRESS:
            return
        if key == self.wnd.keys.SPACE:
            self._paused = not self._paused
            self._rebuild_interpolated(0.0)
        elif key == self.wnd.keys.RIGHT:
            if modifiers.shift:
                if self._ff_speed < self._ff_speed_max:
                    new = self._ff_speed * 2
                    if new >= self._ff_speed_max:
                        self._ff_speed_prev = self._ff_speed
                        self._ff_speed      = self._ff_speed_max
                    else:
                        self._ff_speed = new
                self._update_title(step=self._current_step)
            else:
                self._step(1)
        elif key == self.wnd.keys.LEFT:
            if modifiers.shift:
                if self._ff_speed >= self._ff_speed_max and self._ff_speed_prev:
                    self._ff_speed      = self._ff_speed_prev
                    self._ff_speed_prev = 0
                else:
                    self._ff_speed = max(1, self._ff_speed // 2)
                self._update_title(step=self._current_step)
            else:
                self._step(-1)

    def _get_step_secs(self) -> float:
        return self._play_step.total_seconds() * self._ff_speed

    def on_render(self, time: float, frame_time: float) -> None:
        if not self._paused:
            now     = self._time_mod.monotonic()
            elapsed = now - self._last_update
            if elapsed >= self.UPDATE_INTERVAL:
                self._last_update = now
                self._fetch_data()
                elapsed = 0.0
            t = min(elapsed / self.UPDATE_INTERVAL, 1.0) if self.UPDATE_INTERVAL > 0 else 1.0
            self._rebuild_interpolated(t)

        super(LiveRadixChart, self).on_render(time, frame_time)

        if self._video_path:
            self._frame_buffer.append(self.ctx.screen.read())
            if self._current_dt >= self._end_dt:
                self._encode_video(self._video_path)
                self.wnd.close()

    def _build(self) -> None:
        super()._build()
        self._build_playback_hud()

    def _build_playback_hud(self) -> None:
        dt  = self._current_dt
        cur = self._current_step
        tot = self._total_steps
        if dt is None:
            return

        pct   = cur / tot
        speed = self._ff_speed
        label = dt.strftime("%Y-%m-%d  %H:%M")
        if speed > 1:              label += f"  {speed}x"
        if self._paused:           label += "  paused"
        self._add_text(label, 0.0, -1.08, self.TEXT_SIZE * 0.9, WHITE)

        bar_w  = 1.6
        bar_y  = -1.14
        bar_x0 = -bar_w / 2
        bar_x1 =  bar_w / 2
        fill_x1 = bar_x0 + bar_w * pct
        self._add_segment(bar_x0, bar_y, bar_x1, bar_y, DIM_LINE, 'soft')
        if pct > 0:
            self._add_segment(bar_x0, bar_y, fill_x1, bar_y, WHITE, 'soft')

        if self._paused:
            self._add_text("space  play    arrows  step    shift+arrows  speed", 0.0, -1.19, self.TEXT_SIZE * 0.7, DIM_LINE)

    def _encode_video(self, path: str) -> None:
        try:
            import imageio  # type: ignore
            w, h = self.wnd.size
            fps  = max(1, round(1.0 / self.UPDATE_INTERVAL))
            with imageio.get_writer(path, fps=fps, macro_block_size=None) as writer:
                for frame_bytes in self._frame_buffer:
                    arr = np.frombuffer(frame_bytes, dtype=np.uint8).reshape(h, w, 3)
                    arr = np.flipud(arr)
                    writer.append_data(arr)
            logging.info("video saved: %s", path)
        except ImportError:
            logging.error("imageio required for video export: pip install imageio[ffmpeg]")


#---------------#
# TRANSIT CHART #
#---------------#

class TransitChart(RadixChart):
    title = "Transit Chart"

    VIEWPORT = 1.4

    _cfg_transit_cusps:      list[float] = []
    _cfg_transit_celestials: list        = []
    _cfg_transit_aspects:    list        = []

    R_TRANSIT_RIM      = 1.25
    TRANSIT_GLYPH_OFF  = 0.08
    TRANSIT_SIGN_OFF   = 0.14
    TRANSIT_ORB_OFF    = 0.20

    @classmethod
    def configure_transit(cls, cusps: list[float], celestials: list,
                          transit_cusps: list[float], transit_celestials: list,
                          transit_aspects: list = [],
                          title: str = "Transit Chart", save_path: Optional[str] = None) -> None:
        cls.configure(cusps=cusps, celestials=celestials, title=title, save_path=save_path)
        cls._cfg_transit_cusps      = transit_cusps
        cls._cfg_transit_celestials = transit_celestials
        cls._cfg_transit_aspects    = transit_aspects

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._transit_cusps      = list(self.__class__._cfg_transit_cusps)
        self._transit_celestials = list(self.__class__._cfg_transit_celestials)
        self._transit_aspects    = list(self.__class__._cfg_transit_aspects)

    def _build_aspects(self) -> None:
        pass  # suppress natal-only aspects

    def _build(self) -> None:
        super()._build()
        self._build_transit_base()
        self._build_transit_houses()
        self._build_transit_celestials()
        self._build_transit_aspects()

    def _build_transit_base(self) -> None:
        self._add_circle(self.R_TRANSIT_RIM, WHITE)
        one_deg = np.linspace(0, 2 * math.pi, 360, endpoint=False) + math.radians(15) - self._base_rad
        for angle in one_deg:
            self._add_line(angle, self.R_RIM, self.R_RIM - 0.020, DIM_LINE)
        ten_deg = np.linspace(0, 2 * math.pi, 36, endpoint=False) + math.radians(15) - self._base_rad
        for angle in ten_deg:
            self._add_line(angle, self.R_RIM, self.R_RIM - 0.030, DIM_WHITE)

    def _build_transit_houses(self) -> None:
        for cusp_lon in self._transit_cusps:
            self._add_line(math.radians(cusp_lon) - self._base_rad, self.R_RIM, self.R_TRANSIT_RIM, DIM_LINE)

    def _build_transit_celestials(self) -> None:
        if not self._transit_celestials:
            return
        nodes    = [_LabelNode(lon=cel.lon, chart_lon=cel.lon, data=cel)
                    for cel in self._transit_celestials if cel.lon is not None]
        resolved = _resolve_collisions(nodes)

        for node in resolved:
            cel       = node.data
            tick_ang  = math.radians(cel.lon) - self._base_rad
            label_ang = math.radians(node.chart_lon) - self._base_rad
            lx = math.cos(label_ang)
            ly = math.sin(label_ang)
            cel_color = CELESTIAL_COLORS.get(cel.name.lower(), WHITE)

            self._add_line(tick_ang, self.R_RIM, self.R_RIM + 0.025, cel_color)
            r = self.R_RIM + self.TRANSIT_GLYPH_OFF
            self._add_glyph(cel.glyph, lx * r, ly * r, self.GLYPH_SIZE, cel_color)

            try:
                sign_glyph, _ = cel.sign
                r = self.R_RIM + self.TRANSIT_SIGN_OFF
                self._add_glyph(sign_glyph, lx * r, ly * r, self.GLYPH_SIZE * 0.82, cel_color)
            except (ValueError, TypeError, AttributeError):
                pass

            try:
                r = self.R_RIM + self.TRANSIT_ORB_OFF
                self._add_text(f"{round(cel.orb)}°", lx * r, ly * r, self.TEXT_SIZE * 0.65, DIM_WHITE)
            except (ValueError, TypeError, AttributeError):
                pass

    def _build_transit_aspects(self) -> None:
        for aspect in self._transit_aspects:
            color  = ASPECT_COLORS.get(aspect.name, DIM_WHITE)
            weight = ASPECT_WEIGHTS.get(aspect.name, 'soft')
            if aspect.body_one.lon and aspect.body_two.lon:
                ang1 = math.radians(aspect.body_one.lon) - self._base_rad
                ang2 = math.radians(aspect.body_two.lon) - self._base_rad
                x1 = self.R_INNER * math.cos(ang1)
                y1 = self.R_INNER * math.sin(ang1)
                x2 = self.R_INNER * math.cos(ang2)
                y2 = self.R_INNER * math.sin(ang2)
                self._add_segment(x1, y1, x2, y2, color, weight)
