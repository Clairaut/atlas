# atlas/src/models/cosmo.py


# Standard libraries
from datetime import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

# Internal libraries
if TYPE_CHECKING:
	from src.models.location import Location


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

PHASES: list[tuple[float, float, str, str, str]] = [
    # (illum_min, illum_max, name_tpl, waxing_emoji, waning_emoji)
    (0.00, 0.20, "New {name}",             "🌑", "🌑"),
    (0.20, 0.40, "{dir} Crescent",  "🌒", "🌘"),
    (0.40, 0.60, "{dir2} Quarter",   "🌓", "🌗"),
    (0.60, 0.80, "{dir} Gibbous",   "🌔", "🌖"),
    (0.80, 1.01, "Full {name}",            "🌕", "🌕"),
]


@dataclass
class CelestialState:
	id: int
	glyph: str
	name: str

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

	phase_angle: Optional[float] = field(init=False, default=None)
	phase_illuminated: Optional[float] = field(init=False, default=None)
	elong: Optional[float] = field(init=False, default=None)
	app_diam: Optional[float] = field(init=False, default=None)
	app_mag: Optional[float] = field(init=False, default=None)
	waxing: Optional[bool] = field(init=False, default=None)

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
	def phase(self) -> Optional[tuple]:
		# Validate required properties
		if self.phase_illuminated is None or self.waxing is None:
			raise ValueError(f"phase_illuminated or waxing is not set for celestial state: {self.name}")

		# Determine phase name and emoji
		for illum_min, illum_max, name_tpl, waxing_emoji, waning_emoji in PHASES:
			if illum_min <= self.phase_illuminated < illum_max:
				name = name_tpl.format(name=self.name, dir="Waxing" if self.waxing else "Waning", dir2="First" if self.waxing else "Last")
				emoji = waxing_emoji if self.waxing else waning_emoji
				return (name, emoji)
		return None


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

	# Apply celestial phenomenon to state
	def apply_pheno(self, pheno: tuple[float, float, float, float, float, bool]) -> None:
		if len(pheno) != 6:
			raise ValueError(f"Expected 6 values for phenomenon, got {len(pheno)}: {pheno}")
		self.phase_angle, self.phase_illuminated, self.elong, self.app_diam, self.app_mag, self.waxing = pheno

