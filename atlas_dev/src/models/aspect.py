# Standard Modules
from dataclasses import dataclass
from typing import TYPE_CHECKING

# Internal Modules
if TYPE_CHECKING:
    from atlas_dev.src.models.celestial_state import CelestialState


# Aspect angle definitions: (angle_deg, name, orb_limit)
ASPECT_DEFS: list[tuple[int, str, float]] = [
    (0,   'conjunction', 7.5),
    (60,  'sextile',     7.5),
    (90,  'square',      7.5),
    (120, 'trine',       7.5),
    (180, 'opposition',  7.5),
]

# Aspect glyph mapping
ASPECT_GLYPHS: dict[str, str] = {
    'conjunction': '☌',
    'sextile':     '⚹',
    'square':      '□',
    'trine':       '△',
    'opposition':  '☍',
}


@dataclass
class Aspect:
    name:     str
    body_one: "CelestialState"
    body_two: "CelestialState"
    orb:      float
