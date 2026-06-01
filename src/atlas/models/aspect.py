# Standard Modules
from dataclasses import dataclass
from typing import TYPE_CHECKING

# Internal Modules
if TYPE_CHECKING:
    from atlas.models.celestial_state import CelestialState


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
    body_one: "CelestialState"
    body_two: "CelestialState"
    orb:      float
    glyph:    str = ""


# Shortest angular distance between two ecliptic longitudes, result in [0, 180]
def angular_diff(lon_a: float, lon_b: float) -> float:
    diff = abs(lon_a - lon_b) % 360
    return 360 - diff if diff > 180 else diff


# Compute all aspects between a list of celestial states (pure geometry)
def build_aspects(celestials: "list[CelestialState]") -> list[Aspect]:
    aspects: list[Aspect] = []
    for i in range(len(celestials)):
        for j in range(i + 1, len(celestials)):
            a, b = celestials[i], celestials[j]
            if a.lon is None or b.lon is None:
                continue
            diff = angular_diff(a.lon, b.lon)
            for angle, name, orb_limit in ASPECT_DEFS:
                if abs(diff - angle) <= orb_limit:
                    aspects.append(Aspect(name=name, body_one=a, body_two=b,
                                          orb=abs(diff - angle), glyph=ASPECT_GLYPHS.get(name, "?")))
                    break
    return aspects


# Compute cross-chart aspects between natal and transit bodies
def build_transit_aspects(natal: "list[CelestialState]", transit: "list[CelestialState]") -> list[Aspect]:
    aspects: list[Aspect] = []
    for a in natal:
        for b in transit:
            if a.lon is None or b.lon is None:
                continue
            diff = angular_diff(a.lon, b.lon)
            for angle, name, orb_limit in ASPECT_DEFS:
                if abs(diff - angle) <= orb_limit:
                    aspects.append(Aspect(name=name, body_one=a, body_two=b,
                                          orb=abs(diff - angle), glyph=ASPECT_GLYPHS.get(name, "?")))
                    break
    return aspects
