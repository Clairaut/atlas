# atlas/src/core/observatory.py

# Standard libraries
from typing import TYPE_CHECKING, Optional
from datetime import datetime, timedelta, timezone


# Internal libraries
from atlas.utils.logger import handle_log

if TYPE_CHECKING:
    from atlas.clients.ephe_client import EphemerisClient
    from atlas.models.location import Location


class Observatory:
	_AYA_ALIASES = {
	    "lahiri":       "L",
	    "fagan":        "F",
	    "krishna": 		"K",
	    "raman":        "R",
	    "yukteshwar":   "Y",
	    "deluce":       "D",
	}

	_HSYS_ALIASES = {
        "placidus": "P", "koch": "K", "porphyry": "O", "regiomontanus": "R",
        "campanus": "C", "equal": "A", "whole": "W", "wholesign": "W", "ws": "W",
    }

	def __init__(
		self, 
		ephe_client: "EphemerisClient",
		dt: datetime,
		location: "Location",
		hsys: str = "P",
		verbose: bool = False
	):
		self._ephe_client = ephe_client
		self.dt = dt
		self._hsys = hsys
		self._verbose = verbose
		self._location = location

		# Cache
		self._jd_cache: float | None = None
		self._jd_dt: datetime | None = None

		if verbose:
			handle_log(
				"info", 
				"ok observatory initiation (dt=%s, location:%s)", 
				dt, location,
				source="observatory"
			)

	@property
	def _dt(self) -> datetime:
		return self.__dt

	@_dt.setter
	def _dt(self, dt: datetime) -> None:
		self.__dt = dt
		if dt is not None:
			# Invalidate JD cache
			self._jd_cache = None
			self._jd_dt = None

	@property
	def _location(self) -> "Location":
		return self.__location

	@_location.setter
	def _location(self, location: "Location") -> None:
		self.__location = location
		if location is not None:
			self._ephe_client.set_ephe_topo(location.lat, location.lon, location.alt)
			if self._verbose:
				handle_log(
					"info", 
					"ok topo set (lat=%.6f, lon=%.6f, alt=%.1f)", 
					location.lat, location.lon, location.alt,
					source="observatory"
				)

	@property
	def _jd(self) -> float:
		# Initialize datetime; set to utc now if empty
		dt = self.dt or datetime.now(timezone.utc)
		if self._verbose and self.dt is None:
			handle_log(
				"warning", 
				"warning _jd: observatory time null; defaulting to present UTC: %s", 
				dt,
				source="observatory"
			)
		
		# Check if cache is valid
		if (self._jd_dt == dt) and (self._jd_cache is not None):
			return self._jd_cache

		# Convert datetime-hour to float
		hour = (dt.hour + dt.minute / 60 + dt.second / 3600 + dt.microsecond / 3_600_000_000)

		# JD conversion
		jd = self._ephe_client.convert_to_jd(dt.year, dt.month, dt.day, hour)

		# Update cache
		self._jd_cache = jd
		self._jd_dt = dt

		# Convert dt to jd
		return jd


	 #======#
	# CONFIG #
     #======#

	# Set observatory datetime/location
	def set(self, dt: Optional[datetime] = None, location: Optional["Location"] = None): 
		if dt:
			self.dt = dt
		if location:
			self._location = location
		
		if self._verbose:
			handle_log(
				"info", 
				"ok observatory setting (dt=%s, location:%s)",
				self.dt, self._location,
				source="observatory"
			)

		return self

	# Shift observatory datetime/location
	def shift(self, t_delta: Optional[timedelta] = None, l_delta: Optional[tuple[float, float, float]] = None):
		# Shift observatory time
		if t_delta:
			if self.dt:
				dt_temp = self.dt
				self.dt += t_delta
				if self._verbose: 
					handle_log(
						"info", 
						"ok observatory time shift (%s to %s)", 
						dt_temp, self.dt,
						source="observatory"
					)
			else:
				handle_log("error", "bad observatory time shift: dt not set")
				raise ValueError("Failed to shift observatory time: dt is not yet set")
		
		# Shift observatory location
		if l_delta:
			if self._location:
				dlat, dlon, dalt = l_delta
				old_loc = self._location
				new_loc = type(old_loc)(lat=old_loc.lat + dlat, lon=old_loc.lon + dlon, alt=old_loc.alt + dalt)
				self._location = new_loc
				if self._verbose: 
					handle_log(
						"info", 
						"ok observatory location shift ((%f, %f, %f) to (%f, %f, %f))",
						old_loc.lat, old_loc.lon, old_loc.alt,
						self._location.lon, self._location.lat, self._location.alt,
						source="observatory"
					)
			else:
				handle_log("error", "bad observatory location shift: location not set")
				raise ValueError("Failed to shift observatory location: location is not yet set")
			
		return self

	# Align the zodiac mode
	def align(self, zodiac: str, aya: str | None = None):
		# Set zodiac mode
		self._ephe_client.set_zodiac(zodiac)

		# Set ayanamsa if sidereal
		if aya:
			aya_code = self._AYA_ALIASES.get(aya.lower())
			if not aya_code:
				handle_log("error", "bad observatory alignment: ayanamsa not found (aya=%s)", aya)
				raise ValueError(f"Unknown ayanamsa {aya}")
			self._ephe_client.set_sidereal_ayanamsa(aya_code)

		if self._verbose:
			handle_log("info", "ok observatory alignment (zodiac=%s, aya=%s, flags=%s)", zodiac, aya, self._ephe_client.flags)
		return self
	
	# Set coordinate system; delegates entirely to ephe_client
	def project(self, system: str):
		self._ephe_client.set_coord_system(system)
		if self._verbose:
			handle_log("info", "ok observatory projection (system=%s, flags=%s)", system, self._ephe_client.flags)
		return self

	# Orient the observatory frame
	def orient(self, frame: str):
		self._ephe_client.set_reference_frame(frame)
		if self._verbose:
			handle_log("info", "ok observatory projection (system=%s, flags=%s)", frame, self._ephe_client.flags)
		return self


	# Select the observatory house division
	def domify(self, system: str):
		hsys = self._HSYS_ALIASES.get(system.lower())
		if not hsys:
			handle_log("error", "bad observatory domification: system not found (system=%s)", system)
			raise ValueError(f"Unknown house system {system}")
		self._hsys = hsys
		if self._verbose:
			handle_log("info", "ok observatory domification (system=%s, hsys=%c)", system, hsys)
		return self

	 #======#
	# ACTION #
     #======#

	# Cast house cusps
	def cast(self) -> tuple[tuple, tuple]:
		if not self._location:
			handle_log("error", "bad observatory cast: location is not yet set")
			raise ValueError("Failed to cast observatory cusps/ascmc: location is not yet set")
		cusps, ascmc = self._ephe_client.query_houses(self._jd, self._location.lat, self._location.lon, self._hsys.encode()) # type: ignore
		
		if self._verbose:
			handle_log("info", "ok observatory cast (dt=%s, location=%s)", self.dt, self._location)
		
		return cusps, ascmc

	# Observe a target — routes to planet or star query based on ID type
	def observe(self, target_id: int | str) -> tuple:
		if isinstance(target_id, int):
			pos, ret = self._ephe_client.query_celestial_pos(target_id, self._jd)
		else:
			pos, ret = self._ephe_client.query_star_pos(target_id, self._jd)
		if ret < 0:
			handle_log(
				"error",
				"bad observatory observation; (error-code=%i, target_id=%s, dt=%s, location=%s)",
				ret, target_id, self.dt, self._location
			)
			raise RuntimeError(f"SwissEph error-code {ret} for target: {target_id}")
		if self._verbose:
			handle_log(
				"info",
				"ok observatory observation; (target=%s, dt=%s, location=%s)",
				target_id, self.dt, self._location
			)
		return pos

	# Profile a target
	def profile(self, target_id: int) -> tuple:
		pheno_now = self._ephe_client.query_pheno(target_id, self._jd)
		pheno_prev = self._ephe_client.query_pheno(target_id, self._jd - 1e-5)

		# Illumination-based waxing
		waxing = pheno_now[1] >= pheno_prev[1]

		# Elongation-based waxing
		waxing_elong = pheno_now[2] >= pheno_prev[2] # type: ignore

		# Stitch result
		result = (*pheno_now, waxing, waxing_elong)

		if self._verbose:
			handle_log(
				"info",
				"ok observatory profile; (target ID=%i, dt=%s, location=%s)",
				target_id, self.dt, self._location
			)

		return result