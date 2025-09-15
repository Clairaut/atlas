# atlas/src/models/cosmo.py


# Standard libraries
from datetime import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

# Internal libraries
if TYPE_CHECKING:
	from atlas.src.models.topo import Location


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
	phase: Optional[float] = field(init=False, default=None)
	elong: Optional[float] = field(init=False, default=None)
	app_diam: Optional[float] = field(init=False, default=None)
	app_mag: Optional[float] = field(init=False, default=None)

	@property
	def retrograde(self) -> bool:
		if lon_speed < 0:
			return True

	@property
	def sign(self) -> str:
		idx = int(self.lon // 30) % 12
		return SIGNS[idx]

	# Apply celestial position to state
	def apply_pos(self, pos: tuple[float], frame: str) -> None:
		match frame:
			case "ecliptic":
				self.lon, self.lat, self.dist, self.dlon, self.dlat, self.ddist = pos
			case "equatorial":
				self.ra, self.dec, self.dist, self.dra, self.ddec, self.ddist = pos

	# Apply celestial phenomenon to state
	def apply_pheno(self, pheno: tuple[float]) -> None:
		self.phase_angle, self.phase, self.elong, self.app_diam, self.app_mag = pheno

