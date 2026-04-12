# Standard Modules
from dataclasses import dataclass
from typing import TYPE_CHECKING

# Internal Modules
if TYPE_CHECKING:
    from atlas.models.planet_state import PlanetState


# Aspect angle definitions: (angle_deg, name, orb_limit)
ASPECT_DEFS: list[tuple[int, str, float]] = [
    (0,   'conjunction', 5),
    (60,  'sextile',     5),
    (90,  'square',      5),
    (120, 'trine',       5),
    (180, 'opposition',  5),
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
    body_one: "PlanetState"
    body_two: "PlanetState"
    orb:      float
    glyph:    str = ""
