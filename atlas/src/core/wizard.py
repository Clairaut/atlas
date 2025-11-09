# atlas/src/core/interpreter.py

# Standard libraries
from typing import TYPE_CHECKING
from datetime import datetime

# Internal libraries
from atlas.src.utils.logger import handle_log
from atlas.src.utils.config import load_config
from atlas.src.models.cosmo import CelestialState

if TYPE_CHECKING:
	from atlas.src.core.observatory import Observatory
	from atlas.src.models.topo import Location



class Wizard:
	def __init__(self, observatory: "Observatory", verbose: bool = False):
		self._observatory = observatory
		self._config = load_config()

	# Cast a celestial state
	def conjure_celestial_state(
		self,
		dt: datetime, 
		location: "Location",
		target: str,
		zodiac: str = "tropical",
		ayanamsa: str = None,
		properties: list[str] = ["position", "phenomenon"],
		frames: list[str] = ["ecliptic", "equatorial"],
	) -> CelestialState:
		try:
			# Get the SwissEph ID of the body
			target = self._config["celestials"][target.lower()]

			# Conjure celestial state
			c = CelestialState(
				id=target["id"], 
				glyph=target["glyph"], 
				name=target["name"],
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
					pos = self._observatory.observe(target["id"])					# Observe target
					c.apply_pos(pos, frame)
					print(f"[wizard][debug] Celestial position: {pos}")
			# If phenomenon properties are requested
			if "phenomenon" in properties:
				pheno = self._observatory.profile(target["id"])
				c.apply_pheno(pheno)
				print(f"[wizard][debug] Celestial phenomenon: {pheno}")


		except Exception as e:
			handle_log(
				"error", 
				"bad celestial glyph conjuring"
				"(dt=%s, location: %s, , target: %s, zodiac: %s, ayanmsa: %s, properties: %s, frames: %s)",
				dt, location, target, zodiac, ayanamsa, properties, frames,
				exc_info=True
			)





