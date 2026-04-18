# Standard libraries
import os
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

# Internal libraries
from atlas.utils.logger import handle_log

# External libraries
import moderngl
import moderngl_window
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# RGBA float tuple alias used throughout
_RGBA = tuple[float, float, float, float]


#-----------#
# CONSTANTS #
#-----------#

_STATIC_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../static')
_SHADER_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shaders')
_FONT_PATH   = os.path.join(_STATIC_DIR, 'fonts/NotoSans-Regular.ttf')
_SYMBOL_FONT = os.path.join(_STATIC_DIR, 'fonts/NotoSansSymbols-Regular.ttf')

ATLAS_SIZE  = 512
GLYPH_CELL  = 48

# Characters pre-rendered into the symbol atlas (astronomical glyphs)
SYMBOL_CHARS = "♈♉♊♋♌♍♎♏♐♑♒♓☉☽☿♀♂♃♄♅♆⯓⚸⚷⯛⚳⚴⚵⚶"

# Characters pre-rendered into the text atlas (Latin, digits, punctuation, retrograde)
TEXT_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz℞°. "

ZODIAC_SYMBOLS = ['♈', '♉', '♊', '♋', '♌', '♍', '♎', '♏', '♐', '♑', '♒', '♓']


def _hex(h: str) -> _RGBA:
    # Convert a CSS hex color string to a normalized RGBA float tuple
    h = h.lstrip('#')
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, 1.0)


# Per-sign RGBA colors (exact legacy chart palette — 4-color repeating cycle)
ZODIAC_COLORS: list[_RGBA] = [
    _hex('#756AB6'),  # Aries
    _hex('#AC87C5'),  # Taurus
    _hex('#E0AED0'),  # Gemini
    _hex('#FFE5E5'),  # Cancer
    _hex('#756AB6'),  # Leo
    _hex('#AC87C5'),  # Virgo
    _hex('#E0AED0'),  # Libra
    _hex('#FFE5E5'),  # Scorpio
    _hex('#756AB6'),  # Sagittarius
    _hex('#AC87C5'),  # Capricorn
    _hex('#E0AED0'),  # Aquarius
    _hex('#FFE5E5'),  # Pisces
]

# Per-celestial RGBA colors (exact legacy chart palette)
CELESTIAL_COLORS: dict[str, _RGBA] = {
    'sun':     _hex('#F6FFC1'),
    'moon':    _hex('#CCCCCC'),
    'mercury': _hex('#B4CDF3'),
    'venus':   _hex('#FFC9E9'),
    'mars':    _hex('#CBC9FF'),
    'jupiter': _hex('#F3D8B4'),
    'saturn':  _hex('#EDBAE1'),
    'uranus':  _hex('#B4EDF3'),
    'neptune': _hex('#AFBEE7'),
    'pluto':   _hex('#CAA6F0'),
    'lilith':  _hex('#808080'),
    'selena':  (1.0, 1.0, 1.0, 1.0),
    'rahu':    (1.0, 1.0, 1.0, 1.0),
}

WHITE:     _RGBA = (1.0, 1.0, 1.0, 1.0)
DIM_WHITE: _RGBA = (1.0, 1.0, 1.0, 0.35)
DIM_LINE:  _RGBA = (1.0, 1.0, 1.0, 0.20)

# Per-aspect RGBA colors (exact legacy palette; conjunction not in legacy — using dim white)
ASPECT_COLORS: dict[str, _RGBA] = {
    'conjunction': (1.0, 1.0, 1.0, 0.50),
    'opposition':  _hex('#756AB6'),
    'trine':       _hex('#AC87C5'),
    'square':      _hex('#E0AED0'),
    'sextile':     _hex('#FFE5E5'),
}

# Line weight tier per aspect: 'hard' > 'med' > 'soft'
ASPECT_WEIGHTS: dict[str, str] = {
    'opposition':  'hard',
    'square':      'med',
    'trine':       'med',
    'sextile':     'soft',
    'conjunction': 'soft',
}



#----------#
# GEOMETRY #
#----------#

def _ortho(l: float, r: float, b: float, t: float) -> np.ndarray:
    # Column-major 4x4 orthographic projection matrix
    return np.array([
        [2/(r-l), 0,       0, -(r+l)/(r-l)],
        [0,       2/(t-b), 0, -(t+b)/(t-b)],
        [0,       0,      -1,  0           ],
        [0,       0,       0,  1           ],
    ], dtype='f4')


def _circle_verts(radius: float, segments: int = 180) -> np.ndarray:
    # Generates line-pair vertices forming a closed circle
    angles = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    pts = np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])
    pairs = np.empty((segments * 2, 2), dtype='f4')
    pairs[0::2] = pts
    pairs[1::2] = np.roll(pts, -1, axis=0)
    return pairs


def _line_verts(angle: float, r1: float, r2: float) -> np.ndarray:
    return np.array([
        [r1 * math.cos(angle), r1 * math.sin(angle)],
        [r2 * math.cos(angle), r2 * math.sin(angle)],
    ], dtype='f4')


def _glyph_quad(x: float, y: float, size: float, uv: tuple[float, float, float, float], color: _RGBA) -> np.ndarray:
    # Two triangles forming a quad; each vertex: x, y, u, v, r, g, b, a
    u0, v0, u1, v1 = uv
    r, g, b, a = color
    hs = size / 2
    return np.array([
        [x-hs, y-hs, u0, v0, r, g, b, a],
        [x+hs, y-hs, u1, v0, r, g, b, a],
        [x+hs, y+hs, u1, v1, r, g, b, a],
        [x+hs, y+hs, u1, v1, r, g, b, a],
        [x-hs, y+hs, u0, v1, r, g, b, a],
        [x-hs, y-hs, u0, v0, r, g, b, a],
    ], dtype='f4')


def _strip_var_selector(ch: str) -> str:
    # Remove Unicode variation selectors that can attach to astrological glyphs
    return ch.replace('\uFE0E', '').replace('\uFE0F', '')


#-----------#
# GLYPH ATLAS #
#-----------#

class GlyphAtlas:
    def __init__(self, ctx: moderngl.Context, font_path: str, chars: str, cell_size: int = GLYPH_CELL):
        self.uv_map: dict[str, tuple[float, float, float, float]] = {}
        cols     = ATLAS_SIZE // cell_size
        rows     = math.ceil(len(chars) / cols)
        atlas_h  = max(rows * cell_size, 1)

        img  = Image.new("RGBA", (ATLAS_SIZE, atlas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype(font_path, size=cell_size - 8)
        except Exception:
            handle_log("warning", "glyph atlas: font not found at %s, using default", font_path)
            font = ImageFont.load_default()

        for i, ch in enumerate(chars):
            col = i % cols
            row = i // cols
            px  = col * cell_size + cell_size // 2
            py  = row * cell_size + cell_size // 2
            draw.text((px, py), ch, font=font, fill=(255, 255, 255, 255), anchor="mm")

            # Compute UV coords; flip V after image flip below
            u0 = (col * cell_size)         / ATLAS_SIZE
            v0 = (row * cell_size)         / atlas_h
            u1 = ((col + 1) * cell_size)   / ATLAS_SIZE
            v1 = ((row + 1) * cell_size)   / atlas_h
            self.uv_map[ch] = (u0, v0, u1, v1)

        # Flip image vertically for OpenGL and re-map V coords
        img = img.transpose(Image.FLIP_TOP_BOTTOM) # type: ignore
        for ch in self.uv_map:
            u0, v0, u1, v1 = self.uv_map[ch]
            self.uv_map[ch] = (u0, 1.0 - v1, u1, 1.0 - v0)

        self.texture = ctx.texture((ATLAS_SIZE, atlas_h), 4, img.tobytes())
        self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)


#------------------#
# LABEL COLLISION #
#------------------#

@dataclass
class _LabelNode:
    lon: float        # true ecliptic longitude
    chart_lon: float  # display longitude (adjusted for collision avoidance)
    data: Any         # the CelestialState


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

        # Wrap-around check between last and first nodes
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

class Chart(moderngl_window.WindowConfig): # type: ignore
    gl_version   = (3, 3)
    window_size  = (900, 900)
    aspect_ratio = 1.0
    resizable    = True

    # Chart-space half-extent; NDC maps to [-VIEWPORT, VIEWPORT]
    VIEWPORT = 1.2

    # Static-export state (set via configure before show())
    _save_path: Optional[str] = None
    _save_done: bool          = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        # Shader programs
        self._line_prog  = self._load_program('line')
        self._glyph_prog = self._load_program('glyph')

        # Orthographic projection
        v    = self.VIEWPORT
        proj = _ortho(-v, v, -v, v)
        self._line_prog['proj'].write(proj.tobytes())  # type: ignore
        self._line_prog['u_line_alpha'] = 1.0          # type: ignore
        self._glyph_prog['proj'].write(proj.tobytes()) # type: ignore

        # Glyph atlases
        self._sym_atlas = GlyphAtlas(self.ctx, _SYMBOL_FONT, SYMBOL_CHARS)
        self._txt_atlas = GlyphAtlas(self.ctx, _FONT_PATH,   TEXT_CHARS)

        # Geometry accumulators
        self._line_pts:      list[list[float]] = []  # [[x, y, r, g, b, a], ...]
        self._asp_hard_pts:  list[list[float]] = []  # opposition weight tier
        self._asp_med_pts:   list[list[float]] = []  # square/trine weight tier
        self._sym_quads:     list[np.ndarray]  = []
        self._txt_quads:     list[np.ndarray]  = []

        # VAOs (built after geometry is collected)
        self._line_vao:      Optional[moderngl.VertexArray] = None
        self._asp_hard_vao:  Optional[moderngl.VertexArray] = None
        self._asp_med_vao:   Optional[moderngl.VertexArray] = None
        self._sym_glyph_vao: Optional[moderngl.VertexArray] = None
        self._txt_glyph_vao: Optional[moderngl.VertexArray] = None

    # Keep viewport square and pixel-ratio correct when window is resized or moves monitors
    def on_resize(self, width: int, height: int):
        side = min(width, height)
        x    = (width  - side) // 2
        y    = (height - side) // 2
        self.ctx.viewport = (x, y, side, side)

    def _load_program(self, name: str) -> moderngl.Program:
        vert = open(os.path.join(_SHADER_DIR, f'{name}.vert')).read()
        frag = open(os.path.join(_SHADER_DIR, f'{name}.frag')).read()
        return self.ctx.program(vertex_shader=vert, fragment_shader=frag)

    # Capture the current framebuffer and save as a PNG image
    def _save_screenshot(self, path: str):
        x, y, w, h = self.wnd.viewport
        data = self.ctx.screen.read(viewport=(x, y, w, h))
        img  = Image.frombytes('RGB', (w, h), data)
        img  = img.transpose(Image.FLIP_TOP_BOTTOM) # type: ignore
        img.save(path)
        handle_log("info", "chart saved: %s", path, source="chart")

    # Add a single radial line segment to the geometry batch
    def _add_line(self, angle: float, r1: float, r2: float, color: _RGBA):
        v = _line_verts(angle, r1, r2)
        r, g, b, a = color
        self._line_pts.append([float(v[0][0]), float(v[0][1]), r, g, b, a])
        self._line_pts.append([float(v[1][0]), float(v[1][1]), r, g, b, a])

    # Add an arbitrary point-to-point line segment; weight routes to the correct thickness bucket
    def _add_segment(self, x1: float, y1: float, x2: float, y2: float, color: _RGBA, weight: str = 'soft'):
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

    # Add a circle (as line segments) to the geometry batch
    def _add_circle(self, radius: float, color: _RGBA = WHITE):
        pairs = _circle_verts(radius)
        r, g, b, a = color
        for i in range(0, len(pairs), 2):
            self._line_pts.append([float(pairs[i][0]),   float(pairs[i][1]),   r, g, b, a])
            self._line_pts.append([float(pairs[i+1][0]), float(pairs[i+1][1]), r, g, b, a])

    # Add a single glyph quad to the appropriate atlas batch
    def _add_glyph(self, ch: str, x: float, y: float, size: float, color: _RGBA):
        ch = _strip_var_selector(ch)
        if ch in self._sym_atlas.uv_map:
            self._sym_quads.append(_glyph_quad(x, y, size, self._sym_atlas.uv_map[ch], color))
        elif ch in self._txt_atlas.uv_map:
            self._txt_quads.append(_glyph_quad(x, y, size, self._txt_atlas.uv_map[ch], color))

    # Add a string of characters centered at (x, y)
    def _add_text(self, text: str, x: float, y: float, size: float, color: _RGBA):
        spacing   = size * 0.50
        total_w   = len(text) * spacing
        start_x   = x - total_w / 2 + spacing / 2
        for i, ch in enumerate(text):
            self._add_glyph(ch, start_x + i * spacing, y, size, color)

    # Compute all aspects between a list of celestial states using the shared model
    # Release all VAOs and reset geometry accumulators for a fresh rebuild
    def _reset_geometry(self):
        for vao in [self._line_vao, self._asp_hard_vao, self._asp_med_vao,
                    self._sym_glyph_vao, self._txt_glyph_vao]:
            if vao:
                vao.release()
        self._line_vao      = None
        self._asp_hard_vao  = None
        self._asp_med_vao   = None
        self._sym_glyph_vao = None
        self._txt_glyph_vao = None
        self._line_pts     = []
        self._asp_hard_pts = []
        self._asp_med_pts  = []
        self._sym_quads    = []
        self._txt_quads    = []

    # Build a line VAO from a flat list of [x, y, r, g, b, a] points
    def _build_line_vao(self, pts: list[list[float]]) -> Optional[moderngl.VertexArray]:
        if not pts:
            return None
        data = np.array(pts, dtype='f4')
        vbo  = self.ctx.buffer(data.tobytes())
        return self.ctx.vertex_array(self._line_prog, [(vbo, '2f 4f', 'in_pos', 'in_color')])

    # Upload all accumulated geometry to GPU and build VAOs
    def _upload_geometry(self):
        self._line_vao     = self._build_line_vao(self._line_pts)
        self._asp_hard_vao = self._build_line_vao(self._asp_hard_pts)
        self._asp_med_vao  = self._build_line_vao(self._asp_med_pts)

        if self._sym_quads:
            data = np.vstack(self._sym_quads).astype('f4')
            vbo  = self.ctx.buffer(data.tobytes())
            self._sym_glyph_vao = self.ctx.vertex_array(
                self._glyph_prog,
                [(vbo, '2f 2f 4f', 'in_pos', 'in_uv', 'in_color')]
            )

        if self._txt_quads:
            data = np.vstack(self._txt_quads).astype('f4')
            vbo  = self.ctx.buffer(data.tobytes())
            self._txt_glyph_vao = self.ctx.vertex_array(
                self._glyph_prog,
                [(vbo, '2f 2f 4f', 'in_pos', 'in_uv', 'in_color')]
            )

    def on_render(self, time: float, frame_time: float):
        if not hasattr(self, '_debug_printed'):
            self._debug_printed = True
            print(f"[debug] wnd.size={self.wnd.size}  buffer_size={self.wnd.buffer_size}  pixel_ratio={self.wnd.pixel_ratio}  viewport={self.ctx.viewport}")
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)

        if self._line_vao:
            self._line_vao.render(moderngl.LINES)

        # Aspect web — drawn after base lines so they sit on top
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

        # Static-chart save: capture the first fully-rendered frame then close
        if self.__class__._save_path and not self.__class__._save_done:
            self.__class__._save_done = True
            self._save_screenshot(self.__class__._save_path)
            self.wnd.close()


#--------------#
# RADIX CHART  #
#--------------#

class RadixChart(Chart):
    title        = "Radix Chart"
    _chart_title = "Radix Chart"   # user-set title, never overwritten by dynamic updates

    # Class-level data (set via configure() before run_window_config())
    _cusps:      list[float] = []
    _celestials: list        = []
    _aspects:    list        = []

    # Ring radii in chart-space units
    R_INNER      = 0.30   # inner boundary (aspect web)
    R_HOUSE_LBL  = 0.35   # house number label radius
    R_MID        = 0.40   # ASC/DSC/MC/IC label ring
    R_OUTER      = 0.80   # celestial tick ring / zodiac inner
    R_RIM        = 1.00   # zodiac outer

    # Inward offsets from R_OUTER for celestial labels
    GLYPH_OFF  = 0.08
    RETRO_OFF  = 0.14
    SIGN_OFF   = 0.205
    ORB_OFF    = 0.275

    GLYPH_SIZE = 0.088
    TEXT_SIZE  = 0.062

    @classmethod
    def configure(cls, cusps: list[float], celestials: list, aspects: list = [],
                  title: str = "Radix Chart", save_path: Optional[str] = None):
        cls._cusps        = cusps
        cls._celestials   = celestials
        cls._aspects      = aspects
        cls.title         = title
        cls._chart_title  = title
        cls._save_path    = save_path
        cls._save_done    = False

    @classmethod
    def show(cls):
        import sys
        _argv, sys.argv = sys.argv, sys.argv[:1]
        try:
            moderngl_window.run_window_config(cls, args=['--window', 'glfw'])
        finally:
            sys.argv = _argv

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._base_rad = math.radians(self._cusps[0]) - math.pi
        self._mc_rad   = math.radians(self._cusps[9]) - self._base_rad
        self._build()
        self._upload_geometry()

    def _build(self):
        self._build_base()
        self._build_zodiac()
        self._build_houses()
        self._build_aspects()
        self._build_celestials()

    def _build_base(self):
        # Four concentric rings
        for r in [self.R_INNER, self.R_MID, self.R_OUTER, self.R_RIM]:
            self._add_circle(r, WHITE)

        # User-set title — stable, never overwritten by dynamic playback updates
        self._add_text(self.__class__._chart_title, 0.0, 1.1, self.TEXT_SIZE * 0.8, WHITE)

        # Degree tick marks on the outer ring
        one_deg = np.linspace(0, 2 * math.pi, 360, endpoint=False) + math.radians(15) - self._base_rad
        for angle in one_deg:
            self._add_line(angle, self.R_OUTER, self.R_OUTER + 0.020, DIM_LINE)

        ten_deg = np.linspace(0, 2 * math.pi, 36, endpoint=False) + math.radians(15) - self._base_rad
        for angle in ten_deg:
            self._add_line(angle, self.R_OUTER, self.R_OUTER + 0.030, DIM_WHITE)

    def _build_zodiac(self):
        for i in range(12):
            boundary = math.radians(i * 30) - self._base_rad
            mid      = boundary + math.radians(15)
            r_mid    = (self.R_OUTER + self.R_RIM) / 2

            self._add_line(boundary, self.R_OUTER, self.R_RIM, DIM_WHITE)

            x = r_mid * math.cos(mid)
            y = r_mid * math.sin(mid)
            self._add_glyph(ZODIAC_SYMBOLS[i], x, y, self.GLYPH_SIZE, ZODIAC_COLORS[i])

    def _build_houses(self):
        for i, cusp_lon in enumerate(self._cusps):
            next_lon = self._cusps[(i + 1) % 12]

            # House cusp line (dim, thin)
            self._add_line(math.radians(cusp_lon) - self._base_rad, self.R_INNER, self.R_OUTER, DIM_LINE)

            # House number at the midpoint of the house, just inside the inner ring
            diff = next_lon - cusp_lon
            if diff > 180:   diff -= 360
            elif diff < -180: diff += 360
            mid_angle = math.radians(cusp_lon + diff / 2) - self._base_rad
            r_lbl = (self.R_INNER + self.R_MID) / 2
            self._add_text(str(i + 1), r_lbl * math.cos(mid_angle), r_lbl * math.sin(mid_angle), self.TEXT_SIZE * 0.75, DIM_WHITE)

        # ASC / DSC / MC / IC — brighter lines and labels
        axes = [
            (math.pi,              "ASC"),
            (0.0,                  "DSC"),
            (self._mc_rad,         "MC"),
            (self._mc_rad + math.pi, "IC"),
        ]
        r_lbl = (self.R_INNER + self.R_MID) / 2
        for angle, label in axes:
            self._add_line(angle, self.R_MID, self.R_OUTER, WHITE)
            self._add_text(label, r_lbl * math.cos(angle), r_lbl * math.sin(angle), self.TEXT_SIZE * 0.70, WHITE)

    def _build_aspects(self):
        # Draw pre-computed aspect lines between celestial bodies inside R_INNER
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

    def _build_celestials(self):
        if not self._celestials:
            return

        # Build label nodes for collision resolution
        nodes = []
        for cel in self._celestials:
            if cel.lon is None:
                continue
            nodes.append(_LabelNode(lon=cel.lon, chart_lon=cel.lon, data=cel))

        resolved = _resolve_collisions(nodes)

        for node in resolved:
            cel       = node.data
            tick_ang  = math.radians(cel.lon) - self._base_rad
            label_ang = math.radians(node.chart_lon) - self._base_rad
            lx = math.cos(label_ang)
            ly = math.sin(label_ang)

            cel_color = CELESTIAL_COLORS.get(cel.name.lower(), WHITE)

            # Tick mark at the true longitude
            self._add_line(tick_ang, self.R_OUTER - 0.025, self.R_OUTER, cel_color)

            # Celestial glyph
            r = self.R_OUTER - self.GLYPH_OFF
            self._add_glyph(cel.glyph, lx * r, ly * r, self.GLYPH_SIZE, cel_color)

            # Retrograde marker
            try:
                if cel.retrograde:
                    r = self.R_OUTER - self.RETRO_OFF
                    self._add_glyph('℞', lx * r, ly * r, self.TEXT_SIZE, (*cel_color[:3], 0.8))
            except (ValueError, AttributeError):
                pass

            # Zodiac sign glyph (colored by sign)
            try:
                sign_glyph, _ = cel.sign
                r = self.R_OUTER - self.SIGN_OFF
                self._add_glyph(sign_glyph, lx * r, ly * r, self.GLYPH_SIZE * 0.82, cel_color)
            except (ValueError, TypeError, AttributeError):
                pass

            # Orb in degrees
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

    # Standard Modules
    import time as _time_mod

    # Refresh interval in seconds
    UPDATE_INTERVAL: float = 10.0

    # Class-level references set via configure_live()
    _wizard:     Any        = None
    _location:   Any        = None
    _zodiac:     str        = "tropical"
    _targets:    list[str]  = []
    _prev_cusps: list[float] = []

    @classmethod
    def configure_live(cls, wizard: Any, location: Any, zodiac: str, targets: list[str]):
        cls._wizard   = wizard
        cls._location = location
        cls._zodiac   = zodiac
        cls._targets  = targets

    def __init__(self, **kwargs):
        # Fetch initial data before calling super().__init__ (which triggers _build)
        self._fetch_data()
        self._last_update: float = self._time_mod.monotonic()
        super().__init__(**kwargs)

    # Fetch current planetary positions and houses from the wizard
    def _fetch_data(self):
        from datetime import datetime
        from atlas.utils.chrono import convert_to_utc

        now = convert_to_utc(datetime.now(), self.__class__._location)
        self.__class__.title = datetime.now().strftime("Live  —  %Y-%m-%d  %H:%M:%S")

        celestials = []
        for target in self.__class__._targets:
            try:
                state = self.__class__._wizard.conjure_celestial_state(
                    dt         = now,
                    location   = self.__class__._location,
                    target     = target,
                    zodiac     = self.__class__._zodiac,
                    properties = ["position"],
                    systems    = ["ecliptic"],
                )
                celestials.append(state)
            except Exception:
                pass

        cusps = self.__class__._wizard.conjure_houses(
            dt       = now,
            location = self.__class__._location,
            zodiac   = self.__class__._zodiac,
        )
        self.__class__._prev_cusps = list(self.__class__._cusps)
        self.__class__._cusps      = cusps
        self.__class__._celestials = celestials

    # Returns the step duration used for velocity extrapolation (seconds)
    def _get_step_secs(self) -> float:
        return self.__class__.UPDATE_INTERVAL

    # Rebuild geometry with positions interpolated by t ∈ [0, 1] toward the next fetched state
    def _rebuild_interpolated(self, t: float):
        from copy import copy
        cls       = self.__class__
        step_days = self._get_step_secs() / 86400.0

        # Interpolate planet longitudes using SwissEph velocity (dlon in deg/day)
        interp = []
        for c in cls._celestials:
            if t > 0.0 and c.lon is not None and c.dlon is not None:
                ci     = copy(c)
                ci.lon = (c.lon + c.dlon * step_days * t) % 360
                interp.append(ci)
            else:
                interp.append(c)

        # Interpolate house cusps between the previous and current swisseph-computed values
        prev = cls._prev_cusps if cls._prev_cusps else cls._cusps
        interp_cusps = [
            (prev[i] + ((cls._cusps[i] - prev[i] + 180) % 360 - 180) * t) % 360.0
            for i in range(len(cls._cusps))
        ]

        original_celestials = cls._celestials
        original_cusps      = cls._cusps
        original_aspects    = cls._aspects
        cls._celestials     = interp
        cls._cusps          = interp_cusps
        cls._aspects        = cls._wizard.conjure_aspects(interp)
        self._reset_geometry()
        self._base_rad = math.radians(interp_cusps[0]) - math.pi
        self._mc_rad   = math.radians(interp_cusps[9]) - self._base_rad
        self._build()
        self._upload_geometry()
        cls._celestials = original_celestials
        cls._cusps      = original_cusps
        cls._aspects    = original_aspects

    def on_render(self, time: float, frame_time: float):
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

    # Class-level playback state
    _start_dt:     Any   = None
    _end_dt:       Any   = None
    _play_step:    Any   = None   # timedelta per tick
    _current_dt:   Any   = None
    _current_step: int   = 0
    _total_steps:  int   = 1
    _paused:       bool  = False
    _ff_speed:     int   = 1     # fast-forward multiplier — doubles/halves with shift+arrows
    _ff_speed_prev: int  = 0     # speed before hitting the ceiling, for clean step-back
    _ff_speed_max: int   = 1     # ceiling: step * ff_speed <= ~10h
    UPDATE_INTERVAL: float = 1.0  # seconds per step (overrides LiveRadixChart default)

    # Video export state
    _video_path:   Optional[str] = None
    _frame_buffer: list          = []

    @classmethod
    def configure_playback(cls, wizard: Any, location: Any, zodiac: str, targets: list[str],
                           start_dt: Any, end_dt: Any, step: Any, speed: float = 1.0,
                           save_path: Optional[str] = None):
        cls.configure_live(wizard=wizard, location=location, zodiac=zodiac, targets=targets)
        cls._start_dt      = start_dt
        cls._end_dt        = end_dt
        cls._play_step     = step
        cls._current_dt    = start_dt
        cls._current_step  = 0
        cls._paused        = False
        cls._video_path    = save_path
        cls._frame_buffer  = []
        cls.UPDATE_INTERVAL = 1.0 / max(speed, 0.01)

        # Pre-compute total steps for progress display
        total_secs = (end_dt - start_dt).total_seconds()
        step_secs  = step.total_seconds()
        cls._total_steps  = max(1, int(total_secs / step_secs) + 1)
        cls._ff_speed     = 1
        cls._ff_speed_max = max(1, int(36000 / step_secs))  # ~10h ceiling

    # Build and apply the playback title from current state
    def _update_title(self, dt: Any = None, step: int = 0):
        cls   = self.__class__
        dt    = dt or cls._current_dt
        tot   = cls._total_steps
        pct   = int(step / tot * 100)
        speed = f"  {cls._ff_speed}x" if cls._ff_speed > 1 else ""
        cls.title = dt.strftime(f"Playback  —  %Y-%m-%d  %H:%M  [{step}/{tot}  {pct}%]{speed}")

    # Load chart data for a specific datetime without advancing the playback pointer
    def _load_at(self, dt: Any, step: int):
        self._update_title(dt, step)

        celestials = []
        for target in self.__class__._targets:
            try:
                state = self.__class__._wizard.conjure_celestial_state(
                    dt         = dt,
                    location   = self.__class__._location,
                    target     = target,
                    zodiac     = self.__class__._zodiac,
                    properties = ["position"],
                    systems    = ["ecliptic"],
                )
                celestials.append(state)
            except Exception:
                pass

        cusps = self.__class__._wizard.conjure_houses(
            dt=dt, location=self.__class__._location, zodiac=self.__class__._zodiac,
        )
        self.__class__._prev_cusps = list(self.__class__._cusps)
        self.__class__._cusps      = cusps
        self.__class__._celestials = celestials

    def _fetch_data(self):
        if self.__class__._current_dt is None:
            super()._fetch_data()
            return

        dt  = self.__class__._current_dt
        cur = self.__class__._current_step
        self._load_at(dt, cur)

        # Advance time by ff_speed steps — keeps computation rate constant at any speed
        skip    = self.__class__._ff_speed
        next_dt = dt + self.__class__._play_step * skip
        if next_dt <= self.__class__._end_dt:
            self.__class__._current_dt   = next_dt
            self.__class__._current_step = cur + skip

    # Step one frame in either direction (direction: +1 forward, -1 backward)
    def _step(self, direction: int):
        if self.__class__._current_dt is None:
            return
        step_size = self.__class__._play_step
        new_dt    = self.__class__._current_dt + step_size * direction
        new_dt    = max(self.__class__._start_dt, min(new_dt, self.__class__._end_dt))
        new_step  = round((new_dt - self.__class__._start_dt).total_seconds() / step_size.total_seconds())
        new_step  = max(0, min(new_step, self.__class__._total_steps - 1))
        self.__class__._current_dt   = new_dt
        self.__class__._current_step = new_step
        self._load_at(new_dt, new_step)
        self._rebuild_interpolated(0.0)

    # Spacebar: pause/play — arrows: step — shift+arrows: double/halve speed
    def on_key_event(self, key: Any, action: Any, modifiers: Any):
        if action != self.wnd.keys.ACTION_PRESS:
            return
        cls = self.__class__
        if key == self.wnd.keys.SPACE:
            cls._paused = not cls._paused
            self._rebuild_interpolated(0.0)
        elif key == self.wnd.keys.RIGHT:
            if modifiers.shift:
                if cls._ff_speed < cls._ff_speed_max:
                    new = cls._ff_speed * 2
                    if new >= cls._ff_speed_max:
                        cls._ff_speed_prev = cls._ff_speed   # remember pre-cap speed
                        cls._ff_speed      = cls._ff_speed_max
                    else:
                        cls._ff_speed = new
                self._update_title(step=cls._current_step)
            else:
                self._step(1)
        elif key == self.wnd.keys.LEFT:
            if modifiers.shift:
                if cls._ff_speed >= cls._ff_speed_max and cls._ff_speed_prev:
                    cls._ff_speed      = cls._ff_speed_prev
                    cls._ff_speed_prev = 0
                else:
                    cls._ff_speed = max(1, cls._ff_speed // 2)
                self._update_title(step=cls._current_step)
            else:
                self._step(-1)

    # Returns the effective calendar seconds per tick, accounting for fast-forward speed
    def _get_step_secs(self) -> float:
        return self.__class__._play_step.total_seconds() * self.__class__._ff_speed

    def on_render(self, time: float, frame_time: float):
        cls = self.__class__
        if not cls._paused:
            now     = self._time_mod.monotonic()
            elapsed = now - self._last_update
            if elapsed >= cls.UPDATE_INTERVAL:
                self._last_update = now
                self._fetch_data()
                elapsed = 0.0
            # Rebuild every display frame with velocity-extrapolated positions
            t = min(elapsed / cls.UPDATE_INTERVAL, 1.0) if cls.UPDATE_INTERVAL > 0 else 1.0
            self._rebuild_interpolated(t)

        # Render the current frame (bypasses Chart._save_path logic for static exports)
        super(LiveRadixChart, self).on_render(time, frame_time)

        # Capture frame for video export
        if self.__class__._video_path:
            self.__class__._frame_buffer.append(self.ctx.screen.read())
            if self.__class__._current_dt >= self.__class__._end_dt:
                self._encode_video(self.__class__._video_path)
                self.wnd.close()

    def _build(self):
        super()._build()
        self._build_playback_hud()

    # Draw date, step count, progress bar, and pause indicator at the bottom
    def _build_playback_hud(self):
        dt  = self.__class__._current_dt
        cur = self.__class__._current_step
        tot = self.__class__._total_steps
        if dt is None:
            return

        pct   = cur / tot
        speed = self.__class__._ff_speed
        label = dt.strftime("%Y-%m-%d  %H:%M")
        if speed > 1:   label += f"  {speed}x"
        if self.__class__._paused: label += "  paused"
        self._add_text(label, 0.0, -1.08, self.TEXT_SIZE * 0.9, WHITE)

        # Progress bar: a dim base line + a filled portion on top
        bar_w  = 1.6
        bar_y  = -1.14
        bar_x0 = -bar_w / 2
        bar_x1 =  bar_w / 2
        fill_x1 = bar_x0 + bar_w * pct

        self._add_segment(bar_x0, bar_y, bar_x1, bar_y, DIM_LINE, 'soft')
        if pct > 0:
            self._add_segment(bar_x0, bar_y, fill_x1, bar_y, WHITE, 'soft')

        # Key hint shown when paused
        if self.__class__._paused:
            self._add_text("space  play    arrows  step    shift+arrows  speed", 0.0, -1.19, self.TEXT_SIZE * 0.7, DIM_LINE)

    # Encode accumulated frames as an MP4 video using imageio+ffmpeg
    def _encode_video(self, path: str):
        try:
            import imageio  # type: ignore
            w, h = self.wnd.size
            fps  = max(1, round(1.0 / self.UPDATE_INTERVAL))
            with imageio.get_writer(path, fps=fps, macro_block_size=None) as writer:
                for frame_bytes in self.__class__._frame_buffer:
                    arr = np.frombuffer(frame_bytes, dtype=np.uint8).reshape(h, w, 3)
                    arr = np.flipud(arr)
                    writer.append_data(arr)
            handle_log("info", "video saved: %s", path, source="chart")
        except ImportError:
            handle_log("error", "imageio required for video export: pip install imageio[ffmpeg]", source="chart")


#---------------#
# TRANSIT CHART #
#---------------#

class TransitChart(RadixChart):
    title = "Transit Chart"

    VIEWPORT = 1.4

    # Class-level transit data (set via configure_transit before run_window_config)
    _transit_cusps:      list[float] = []
    _transit_celestials: list        = []
    _transit_aspects:    list        = []

    # Outer ring radii
    R_TRANSIT_RIM = 1.25

    TRANSIT_GLYPH_OFF = 0.08
    TRANSIT_SIGN_OFF  = 0.14
    TRANSIT_ORB_OFF   = 0.20

    # Suppress natal-only aspects
    def _build_aspects(self):
        pass

    @classmethod
    def configure_transit(cls, cusps: list[float], celestials: list,
                          transit_cusps: list[float], transit_celestials: list,
                          transit_aspects: list = [],
                          title: str = "Transit Chart", save_path: Optional[str] = None):
        cls.configure(cusps=cusps, celestials=celestials, title=title, save_path=save_path)
        cls._transit_cusps      = transit_cusps
        cls._transit_celestials = transit_celestials
        cls._transit_aspects    = transit_aspects

    @classmethod
    def show(cls):
        import sys
        _argv, sys.argv = sys.argv, sys.argv[:1]
        try:
            moderngl_window.run_window_config(cls, args=['--window', 'glfw'])
        finally:
            sys.argv = _argv

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


    def _build(self):
        super()._build()
        # Outer zodiac ring between R_RIM and R_TRANSIT_RIM
        self._build_transit_base()
        self._build_transit_houses()
        self._build_transit_celestials()
        self._build_transit_aspects()


    def _build_transit_base(self):
        # Outer zodiac ring between R_RIM and R_TRANSIT_RIM
        self._add_circle(self.R_TRANSIT_RIM, WHITE)

        # Degree tick marks on the outer ring
        one_deg = np.linspace(0, 2 * math.pi, 360, endpoint=False) + math.radians(15) - self._base_rad
        for angle in one_deg:
            self._add_line(angle, self.R_RIM, self.R_RIM - 0.020, DIM_LINE)

        ten_deg = np.linspace(0, 2 * math.pi, 36, endpoint=False) + math.radians(15) - self._base_rad
        for angle in ten_deg:
            self._add_line(angle, self.R_RIM, self.R_RIM - 0.030, DIM_WHITE)


    def _build_transit_houses(self):
        # Transit house cusp lines on outer ring
        for i, cusp_lon in enumerate(self._transit_cusps):
            self._add_line(math.radians(cusp_lon) - self._base_rad, self.R_RIM, self.R_TRANSIT_RIM, DIM_LINE)

    def _build_transit_celestials(self):
        if not self._transit_celestials:
            return

        nodes = [_LabelNode(lon=cel.lon, chart_lon=cel.lon, data=cel)
                 for cel in self._transit_celestials if cel.lon is not None]
        resolved = _resolve_collisions(nodes)

        for node in resolved:
            cel       = node.data
            tick_ang  = math.radians(cel.lon) - self._base_rad
            label_ang = math.radians(node.chart_lon) - self._base_rad
            lx = math.cos(label_ang)
            ly = math.sin(label_ang)

            cel_color = CELESTIAL_COLORS.get(cel.name.lower(), WHITE)

            # Tick at true longitude on the inner transit boundary
            self._add_line(tick_ang, self.R_RIM, self.R_RIM + 0.025, cel_color)

            # Glyph
            r = self.R_RIM + self.TRANSIT_GLYPH_OFF
            self._add_glyph(cel.glyph, lx * r, ly * r, self.GLYPH_SIZE, cel_color)

            # Sign glyph
            try:
                sign_glyph, _ = cel.sign
                r = self.R_RIM + self.TRANSIT_SIGN_OFF
                self._add_glyph(sign_glyph, lx * r, ly * r, self.GLYPH_SIZE * 0.82, cel_color)
            except (ValueError, TypeError, AttributeError):
                pass

            # Orb
            try:
                r = self.R_RIM + self.TRANSIT_ORB_OFF
                self._add_text(f"{round(cel.orb)}°", lx * r, ly * r, self.TEXT_SIZE * 0.65, DIM_WHITE)
            except (ValueError, TypeError, AttributeError):
                pass

    def _build_transit_aspects(self):
        # Draw pre-computed cross-chart aspect lines
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
