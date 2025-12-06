# atlas/src/core/observatory.py

# Standard libraries
from typing import TYPE_CHECKING, Optional
from datetime import datetime, timedelta, timezone

# Internal libraries
from src.utils.logger import handle_log

if TYPE_CHECKING:
	from src.clients.ephe_client import EphemerisClient
	from src.models.topo import Location


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
		self._dt = dt
		self._hsys = "P"
		self._zodiac = "tropical"
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
		dt = self._dt or datetime.now(timezone.utc)
		if self._verbose and self._dt is None:
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
			self._dt = dt
		if location:
			self._location = location
		
		if self._verbose:
			handle_log(
				"info", 
				"ok observatory setting (dt=%s, location:%s)",
				self._dt, self._location,
				source="observatory"
			)

	# Shift observatory datetime/location
	def shift(self, t_delta: Optional[timedelta] = None, l_delta: Optional[tuple[float, float, float]] = None):
		# Shift observatory time
		if t_delta:
			if self._dt:
				dt_temp = self._dt
				self._dt += t_delta
				if self._verbose: 
					handle_log(
						"info", 
						"ok observatory time shift (%s to %s)", 
						dt_temp, self._dt,
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

	# Align the zodiac mode
	def align(self, zodiac: str, aya: str | None = None):
		match zodiac:
			case "tropical":
				self._ephe_client.use_tropical()
			case "sidereal":
				if aya:
					aya_code = self._AYA_ALIASES.get(aya)
					if not aya_code:
						handle_log(
							"error", 
							"bad observatory alignment: ayanamsa alias not found"
							" (ayanamsa=%s)", aya,
							source="observatory"	
						)
						raise ValueError(f"Failed to align observatory zodiac system: ayanamsa alias not found: {aya}")
					self._ephe_client.use_sidereal(aya_code)
				else:
					handle_log(
						"error", 
						"bad observatory alignment: ayanamsa not provided for sidereal zodiac",
						source="observatory"
					)
					raise ValueError("Failed to align observatory zodiac system: ayanamsa must be provided for sidereal zodiac")
		return self

	# Orient the observatory frame
	def orient(self, frame: str):
		match frame:
			case "ecliptic":
				self._ephe_client.use_ecliptic()
			case "equatorial":
				self._ephe_client.use_equatorial()
			case "topocentric":
				self._ephe_client.use_topocentric()
			case "geocentric":
				self._ephe_client.use_geocentric()
		if self._verbose:
			handle_log("info", "ok observatory frame orientation (frame=%s, flags=%s)", frame, self._ephe_client.flags)
		return self

	# Select the observatory house division
	def domify(self, system: str):
		hsys = self._HSYS_ALIASES.get("system") 
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
		cusps, ascmc = self._ephe_client.query_houses(self._jd, self._location.lat, self._location.lon, self._hsys)
		
		if self._verbose:
			handle_log("info", "ok observatory cast (dt=%s, location=%s)", self._dt, self._location)
		
		return cusps, ascmc

	# Observe a target
	def observe(self, target_id: int) -> tuple:
		pos, ret = self._ephe_client.query_pos(target_id, self._jd)
		if ret < 0:
			handle_log(
				"error", 
				"bad observatory observation; (error-code=%i, target_id=%i, dt=%s, location=%s)", 
				ret, target_id, self._dt, self._location
			)
			raise RuntimeError(f"SwissEph error-code {ret} for target ID: {target_id}")
		if self._verbose:
			handle_log(
				"info", 
				"ok observatory observation; (target ID=%i, dt=%s, location=%s)",
				target_id, self._dt, self._location
			)
		return pos

	# Profile a target
	def profile(self, target_id: int) -> tuple:
		pheno_now = self._ephe_client.query_pheno(target_id, self._jd)
		pheno_prev = self._ephe_client.query_pheno(target_id, self._jd - 1e-5)

		# Determine waxing/waning
		waxing = pheno_now[1] >= pheno_prev[1]

		# Stitch result
		result = (*pheno_now, waxing)

		if self._verbose:
			handle_log(
				"info",
				"ok observatory profile; (target ID=%i, dt=%s, location=%s)",
				target_id, self._dt, self._location
			)

		return result