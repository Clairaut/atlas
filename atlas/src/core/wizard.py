# atlas/src/core/interpreter.py

# Standard libraries
from typing import TYPE_CHECKING, Optional
from datetime import datetime

# Internal libraries
from src.utils.logger import handle_log
from src.utils.config import load_config
from src.models.cosmo import CelestialState

if TYPE_CHECKING:
	from src.core.observatory import Observatory
	from src.models.topo import Location



class Wizard:
	def __init__(self, observatory: "Observatory", verbose: bool = False):
		self._observatory = observatory
		self._config = load_config()
		self._verbose = verbose

	# Cast a celestial state
	def conjure_celestial_state(
		self,
		dt: datetime, 
		location: "Location",
		target: str,
		zodiac: str = "tropical",
		ayanamsa: Optional[str] = None,
		properties: list[str] = ["position", "phenomenon"],
		frames: list[str] = ["ecliptic", "equatorial"],
	) -> CelestialState:

		# Get the SwissEph ID of the body
		target_info = self._config["celestials"].get(target.lower())

		# Raise error if the target is not found
		if not target_info:
			raise ValueError(f"Target, {target}, could not be found. Please check configuration.")

		# Conjure celestial state  
		c = CelestialState(
			id=target_info["id"], 
			glyph=target_info["glyph"], 
			name=target_info["name"],
			dt=dt,
			location=location
		)

		# Setup observatory
		self._observatory.set(dt=dt, location=location)
		self._observatory.align(zodiac=zodiac)

		# If positional properties are requested
		if "position" in properties:
			for frame in frames:
				self._observatory.orient(frame)									# Orient observatory
				pos = self._observatory.observe(target_info["id"])					# Observe target
				c.apply_pos(pos, frame)

				if self._verbose:
					handle_log(
						"info", 
						"Celestial position: frame=%s, pos=%s", 
						frame, pos,
						source="wizard"
					)

		# If phenomenon properties are requested
		if "phenomenon" in properties:
			pheno = self._observatory.profile(target_info["id"])
			c.apply_pheno(pheno)

			# Log phenomenon info
			if self._verbose:
				handle_log(
					"info",
					"Celestial phenomenon: pheno=%s",
					pheno,
					source="wizard"
				)

		return c






