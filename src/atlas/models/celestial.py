# atlas/src/models/cosmo.py


# Standard libraries
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Union

Location = tuple[float, float, float]


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
# ︎ is the text-presentation selector: forces monochrome glyph instead of color emoji, same as the zodiac glyphs above
PHASE_DEFS: list[tuple[float, str, str]] = [
    (0,   "New {name}",      "🌑︎"),
    (45,  "Waxing Crescent", "🌒︎"),
    (90,  "First Quarter",   "🌓︎"),
    (135, "Waxing Gibbous",  "🌔︎"),
    (180, "Full {name}",     "🌕︎"),
    (225, "Waning Gibbous",  "🌖︎"),
    (270, "Last Quarter",    "🌗︎"),
    (315, "Waning Crescent", "🌘︎"),
]

# Phase display for superior planets — illumination-based, two states only
# (illum_threshold, name_tpl, glyph) — first entry where phase_illuminated >= threshold wins
SUPERIOR_PHASE_DEFS: list[tuple[float, str, str]] = [
    (0.95, "Full {name}",    "🌕︎"),
    (0.00, "Gibbous {name}", "🌔︎"),
]

# Synodic crossing events for superior planets (elongation-based)
# (cycle_angle_deg, name_tpl, glyph) — name_tpl supports {name} substitution
ELONGATION_EVENTS: list[tuple[float, str, str]] = [
    (0,   "Conjunction {name}",        "☌"),
    (90,  "Eastern Quadrature {name}", "□"),
    (180, "Opposition {name}",         "☍"),
    (270, "Western Quadrature {name}", "□"),
]


@dataclass
class Celestial:
	id: Union[int, str]
	glyph: str
	name: str
	type: str                  # "inferior" | "superior" | "satellite" | "star"

	dt: datetime
	location: Location

	color: Optional[str] = field(default=None)  # hex, from [celestials].color config

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
	phase_waxing: Optional[bool] = field(init=False, default=None)
	elong_waxing: Optional[bool] = field(init=False, default=None)  # elongation-based, for elong_cycle

	@property
	def retrograde(self) -> bool:
		if self.type in ("star", "node", "derived"):
			return False
		if self.dlon is None:
			return False
		return self.dlon < 0

	@property
	def sign(self) -> tuple[str, str]:
		if self.lon is None:
			raise ValueError(f"lon is not set for celestial state: {self.name}")
		idx = int(self.lon // 30) % 12
		return SIGNS[idx]

	@property
	def orb(self) -> float:
		if self.lon is None:
			raise ValueError(f"lon is not set for celestial state: {self.name}")
		return self.lon % 30
	
	@property
	def phase(self) -> Optional[tuple[str, str]]:
		match self.type:
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
		if self.phase_angle is None or self.phase_waxing is None:
			return None
		# phase_angle decreases new→full (180°→0°), so invert to get an increasing 0→360° cycle
		return (180.0 - self.phase_angle) if self.phase_waxing else (180.0 + self.phase_angle)

	@property
	def elong_cycle(self) -> Optional[float]:
		# 0-360° monotonic synodic cycle from elongation + waxing_elong (superior planets)
		# 0° = conjunction, 90° = eastern quadrature, 180° = opposition, 270° = western quadrature
		if self.elong is None or self.elong_waxing is None:
			return None
		return self.elong if self.elong_waxing else 360.0 - self.elong

	@property
	def elong_label(self) -> Optional[tuple[str, str]]:
		# Nearest quadrature stage (conjunction/quadrature/opposition), via elong_cycle
		cycle = self.elong_cycle
		if cycle is None:
			return None
		_, name_tpl, glyph = min(ELONGATION_EVENTS, key=lambda p: abs(((cycle - p[0] + 180) % 360) - 180))
		return (name_tpl.format(name=self.name.capitalize()), glyph)


	@property
	def constellation(self) -> Optional[str]:
		# Requires equatorial frame to be loaded
		if self.ra is None or self.dec is None:
			return None
		from atlas.utils.constellation import identify_constellation
		return identify_constellation(self.ra, self.dec)

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
		self.phase_angle, self.phase_illuminated, self.elong, self.app_diam, self.app_mag, self.phase_waxing, self.elong_waxing = pheno

	# JSON-safe dict of the celestial's public state
	def dict(self) -> dict:
		sign_glyph, sign_name = self.sign
		phase = self.phase
		return {
			"glyph":             self.glyph,
			"name":              self.name,
			"type":              self.type,
			"lon":               self.lon,
			"lat":               self.lat,
			"dist":              self.dist,
			"dlon":              self.dlon,
			"elong":             self.elong,
			"elong_waxing":      self.elong_waxing,
			"app_mag":           self.app_mag,
			"app_diam":          self.app_diam,
			"retrograde":        self.retrograde,
			"sign":              sign_name,
			"sign_glyph":        sign_glyph,
			"orb":               round(self.orb, 4),
			"phase":             phase[0] if phase else None,
			"phase_glyph":       phase[1] if phase else None,
			"phase_illuminated": round((self.phase_illuminated or 0), 1),
			"phase_angle":       round(self.phase_angle, 2) if self.phase_angle is not None else None,
			"phase_waxing":      self.phase_waxing,
		}

