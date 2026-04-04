# atlas/src/models/cosmo.py


# Standard libraries
from datetime import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

# Internal libraries
if TYPE_CHECKING:
    from atlas.models.location import Location


# Initialize signs
SIGNS: list[tuple[str, str]] = [
    ("♈︎", "Aries"),
    ("♉︎", "Taurus"),
    ("♊︎", "Gemini"),
    ("♋︎", "Cancer"),
    ("♌︎", "Leo"),
    ("♍︎", "Virgo"),
    ("♎︎", "Libra"),
    ("♏︎", "Scorpio"),
    ("♐︎", "Sagittarius"),
    ("♑︎", "Capricorn"),
    ("♒︎", "Aquarius"),
    ("♓︎", "Pisces"),
]

# Phase definitions for inferior planets and the Moon (full phase cycle via phase_cycle)
# (cycle_angle_deg, name_tpl, glyph) — name_tpl supports {name} substitution
PHASE_DEFS: list[tuple[float, str, str]] = [
    (0,   "New {name}",      "🌑"),
    (45,  "Waxing Crescent", "🌒"),
    (90,  "First Quarter",   "🌓"),
    (135, "Waxing Gibbous",  "🌔"),
    (180, "Full {name}",     "🌕"),
    (225, "Waning Gibbous",  "🌖"),
    (270, "Last Quarter",    "🌗"),
    (315, "Waning Crescent", "🌘"),
]

# Phase display for superior planets — illumination-based, two states only
# (illum_threshold, name_tpl, glyph) — first entry where phase_illuminated >= threshold wins
SUPERIOR_PHASE_DEFS: list[tuple[float, str, str]] = [
    (0.00, "Full {name}",    "🌕"),
    (0.95, "Gibbous {name}", "🌔"),
]

# Synodic crossing events for superior planets (elongation-based, used by wizard)
# (cycle_angle_deg, name_tpl, glyph) — name_tpl supports {name} substitution
ELONGATION_EVENTS: list[tuple[float, str, str]] = [
    (0,   "Conjunction {name}",        "☌"),
    (90,  "Eastern Quadrature {name}", "□"),
    (180, "Opposition {name}",         "☍"),
    (270, "Western Quadrature {name}", "□"),
]


@dataclass
class CelestialState:
	id: int
	glyph: str
	name: str
	orbit: str                  # "inferior" | "superior" | "satellite" | "star"

	dt: datetime
	location: "Location"

	# Positional properties
	dist: Optional[float] = field(init=False, default=None)			# Base (AU)
	ddist: Optional[float] = field(init=False, default=None)

	lon: Optional[float] = field(init=False, default=None)			# Ecliptic (deg)
	lat: Optional[float] = field(init=False, default=None)
	dlon: Optional[float] = field(init=False, default=None)			# Ecliptic (deg/s)
	dlat: Optional[float] = field(init=False, default=None)

	ra: Optional[float] = field(init=False, default=None)			# Equatorial (deg)
	dec: Optional[float] = field(init=False, default=None)
	dra: Optional[float] = field(init=False, default=None)			# Equatorial
	ddec: Optional[float] = field(init=False, default=None)

	alt: Optional[float] = field(init=False, default=None)			# Horizontal (deg)
	az: Optional[float] = field(init=False, default=None)
	ha: Optional[float] = field(init=False, default=None)			# Hour angle [-180, 180]

	phase_angle: Optional[float] = field(init=False, default=None)
	phase_illuminated: Optional[float] = field(init=False, default=None)
	elong: Optional[float] = field(init=False, default=None)
	app_diam: Optional[float] = field(init=False, default=None)
	app_mag: Optional[float] = field(init=False, default=None)
	waxing: Optional[bool] = field(init=False, default=None)
	waxing_elong: Optional[bool] = field(init=False, default=None)  # elongation-based, for elong_cycle

	@property
	def retrograde(self) -> bool:
		if not self.dlon:
			raise ValueError(f"dlon is not set for celestial state: {self.name}")

		if self.dlon < 0:
			return True
		return False

	@property
	def sign(self) -> tuple[str, str]:
		if not self.lon:
			raise ValueError(f"lon is not set for celestial state: {self.name}")

		idx = int(self.lon // 30) % 12
		return SIGNS[idx]
	
	@property
	def orb(self) -> float:
		if not self.lon:
			raise ValueError(f"lon is not set for celestial state: {self.name}")

		return self.lon % 30
	
	@property
	def phase(self) -> Optional[tuple[str, str]]:
		match self.orbit:
			case "superior":
				# Illumination-based: superior planets are always gibbous-to-full
				if self.phase_illuminated is None:
					raise ValueError(f"phase data not available for {self.name} — load phenomenon data first")
				for threshold, name_tpl, glyph in SUPERIOR_PHASE_DEFS:
					if self.phase_illuminated >= threshold:
						return (name_tpl.format(name=self.name.capitalize()), glyph)
			case "inferior" | "satellite":
				# Full 0-360° cycle via phase_cycle (0°=new, 180°=full, matches PHASE_DEFS directly)
				cycle = self.phase_cycle
				if cycle is None:
					raise ValueError(f"phase data not available for {self.name} — load phenomenon data first")
				_, name_tpl, glyph = min(PHASE_DEFS, key=lambda p: abs(((cycle - p[0] + 180) % 360) - 180))
				return (name_tpl.format(name=self.name.capitalize()), glyph)
		return None  # star or unknown

	@property
	def phase_cycle(self) -> Optional[float]:
		# 0-360° monotonic cycle mapped from SwissEph phase_angle (Sun-body-Earth, 180°=new, 0°=full)
		# 0° = new, 90° = first quarter, 180° = full, 270° = last quarter
		if self.phase_angle is None or self.waxing is None:
			return None
		# phase_angle decreases new→full (180°→0°), so invert to get an increasing 0→360° cycle
		return (180.0 - self.phase_angle) if self.waxing else (180.0 + self.phase_angle)

	@property
	def elong_cycle(self) -> Optional[float]:
		# 0-360° monotonic synodic cycle from elongation + waxing_elong (superior planets)
		# 0° = conjunction, 90° = eastern quadrature, 180° = opposition, 270° = western quadrature
		if self.elong is None or self.waxing_elong is None:
			return None
		return self.elong if self.waxing_elong else 360.0 - self.elong


	# Apply celestial position to state
	def apply_pos(self, pos: tuple[float, ...], frame: str) -> None:
		match frame:
			case "ecliptic":
				if len(pos) == 6:
					self.lon, self.lat, self.dist, self.dlon, self.dlat, self.ddist = pos
				else:
					raise ValueError(f"Expected 6 values for ecliptic position, got {len(pos)}: {pos}")
			case "equatorial":
				if len(pos) == 6:
					self.ra, self.dec, self.dist, self.dra, self.ddec, self.ddist = pos
				else:
					raise ValueError(f"Expected 6 values for equatorial position, got {len(pos)}: {pos}")
			case "horizontal":
				if len(pos) == 3:
					self.alt, self.az, self.ha = pos
				else:
					raise ValueError(f"Expected 3 values for horizontal position, got {len(pos)}: {pos}")

	# Apply celestial phenomenon to state
	def apply_pheno(self, pheno: tuple) -> None:
		if len(pheno) != 7:
			raise ValueError(f"Expected 7 values for phenomenon, got {len(pheno)}: {pheno}")
		self.phase_angle, self.phase_illuminated, self.elong, self.app_diam, self.app_mag, self.waxing, self.waxing_elong = pheno

