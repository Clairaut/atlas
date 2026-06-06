# atlas/src/view/base.py
# Shared OpenGL base: atlas init, glyph rendering, resize, shader loading, screenshot export

# Standard Modules
import os
import math
from typing import Optional

# Standard Modules (continued)
import logging

# External Modules
import moderngl
import moderngl_window
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_RGBA = tuple[float, float, float, float]

_STATIC_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../..', 'static')
_SHADER_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shaders')
_FONT_PATH   = os.path.join(_STATIC_DIR, 'fonts/NotoSans-Regular.ttf')
_SYMBOL_FONT = os.path.join(_STATIC_DIR, 'fonts/NotoSansSymbols-Regular.ttf')

ATLAS_SIZE   = 512
GLYPH_CELL   = 48

SYMBOL_CHARS = "♈♉♊♋♌♍♎♏♐♑♒♓☉☽☿♀♂♃♄♅♆⯓⚸⚷⯛⚳⚴⚵⚶"
TEXT_CHARS   = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz℞°. "


def _glyph_quad(x: float, y: float, size: float, uv: tuple[float, float, float, float], color: _RGBA) -> np.ndarray:
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
    return ch.replace('︎', '').replace('️', '')


def _ortho(l: float, r: float, b: float, t: float) -> np.ndarray:
    return np.array([
        [2/(r-l), 0,       0, -(r+l)/(r-l)],
        [0,       2/(t-b), 0, -(t+b)/(t-b)],
        [0,       0,      -1,  0           ],
        [0,       0,       0,  1           ],
    ], dtype='f4')


def _circle_verts(radius: float, segments: int = 180) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    pts    = np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])
    pairs  = np.empty((segments * 2, 2), dtype='f4')
    pairs[0::2] = pts
    pairs[1::2] = np.roll(pts, -1, axis=0)
    return pairs


class GlyphAtlas:
    def __init__(self, ctx: moderngl.Context, font_path: str, chars: str, cell_size: int = GLYPH_CELL):
        self.uv_map: dict[str, tuple[float, float, float, float]] = {}
        cols    = ATLAS_SIZE // cell_size
        rows    = math.ceil(len(chars) / cols)
        atlas_h = max(rows * cell_size, 1)

        img  = Image.new("RGBA", (ATLAS_SIZE, atlas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype(font_path, size=cell_size - 8)
        except Exception:
            logging.warning("glyph atlas: font not found at %s, using default", font_path)
            font = ImageFont.load_default()

        for i, ch in enumerate(chars):
            col = i % cols
            row = i // cols
            px  = col * cell_size + cell_size // 2
            py  = row * cell_size + cell_size // 2
            draw.text((px, py), ch, font=font, fill=(255, 255, 255, 255), anchor="mm")
            u0 = (col * cell_size)       / ATLAS_SIZE
            v0 = (row * cell_size)       / atlas_h
            u1 = ((col + 1) * cell_size) / ATLAS_SIZE
            v1 = ((row + 1) * cell_size) / atlas_h
            self.uv_map[ch] = (u0, v0, u1, v1)

        img = img.transpose(Image.FLIP_TOP_BOTTOM)  # type: ignore
        for ch in self.uv_map:
            u0, v0, u1, v1 = self.uv_map[ch]
            self.uv_map[ch] = (u0, 1.0 - v1, u1, 1.0 - v0)

        self.texture = ctx.texture((ATLAS_SIZE, atlas_h), 4, img.tobytes())
        self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)


class BaseGLWindow(moderngl_window.WindowConfig):  # type: ignore
    gl_version   = (3, 3)
    window_size  = (900, 900)
    aspect_ratio = 1.0
    resizable    = True

    _TEXT_SPACING: float = 0.50  # override in subclasses

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        self._glyph_prog = self._load_program('glyph')
        self._line_prog  = self._load_program('line')

        self._sym_atlas = GlyphAtlas(self.ctx, _SYMBOL_FONT, SYMBOL_CHARS)
        self._txt_atlas = GlyphAtlas(self.ctx, _FONT_PATH,   TEXT_CHARS)

        self._sym_quads:     list[np.ndarray]             = []
        self._txt_quads:     list[np.ndarray]             = []
        self._sym_glyph_vao: Optional[moderngl.VertexArray] = None
        self._txt_glyph_vao: Optional[moderngl.VertexArray] = None

        self._save_path: Optional[str] = None
        self._save_done: bool          = False

    def on_resize(self, width: int, height: int) -> None:
        side = min(width, height)
        x    = (width  - side) // 2
        y    = (height - side) // 2
        self.ctx.viewport = (x, y, side, side)

    def _load_program(self, name: str) -> moderngl.Program:
        vert = open(os.path.join(_SHADER_DIR, f'{name}.vert')).read()
        frag = open(os.path.join(_SHADER_DIR, f'{name}.frag')).read()
        return self.ctx.program(vertex_shader=vert, fragment_shader=frag)

    def _add_glyph(self, ch: str, x: float, y: float, size: float, color: _RGBA) -> None:
        ch = _strip_var_selector(ch)
        if ch in self._sym_atlas.uv_map:
            self._sym_quads.append(_glyph_quad(x, y, size, self._sym_atlas.uv_map[ch], color))
        elif ch in self._txt_atlas.uv_map:
            self._txt_quads.append(_glyph_quad(x, y, size, self._txt_atlas.uv_map[ch], color))

    def _add_text(self, text: str, x: float, y: float, size: float, color: _RGBA) -> None:
        spacing = size * self._TEXT_SPACING
        total_w = len(text) * spacing
        start_x = x - total_w / 2 + spacing / 2
        for i, ch in enumerate(text):
            self._add_glyph(ch, start_x + i * spacing, y, size, color)

    def _reset_glyphs(self) -> None:
        for vao in (self._sym_glyph_vao, self._txt_glyph_vao):
            if vao:
                vao.release()
        self._sym_glyph_vao = None
        self._txt_glyph_vao = None
        self._sym_quads     = []
        self._txt_quads     = []

    def _upload_glyphs(self) -> None:
        def _build(quads: list) -> Optional[moderngl.VertexArray]:
            if not quads:
                return None
            data = np.vstack(quads).astype('f4')
            vbo  = self.ctx.buffer(data.tobytes())
            return self.ctx.vertex_array(
                self._glyph_prog, [(vbo, '2f 2f 4f', 'in_pos', 'in_uv', 'in_color')]
            )
        self._sym_glyph_vao = _build(self._sym_quads)
        self._txt_glyph_vao = _build(self._txt_quads)

    def _save_screenshot(self, path: str) -> None:
        x, y, w, h = self.ctx.viewport
        data = self.ctx.screen.read(viewport=(x, y, w, h))
        img  = Image.frombytes('RGB', (w, h), data).transpose(Image.FLIP_TOP_BOTTOM)  # type: ignore
        img.save(path)
        logging.info("saved: %s", path)

    @classmethod
    def show(cls) -> None:
        import sys
        _argv, sys.argv = sys.argv, sys.argv[:1]
        try:
            moderngl_window.run_window_config(cls, args=['--window', 'glfw'])
        finally:
            sys.argv = _argv
