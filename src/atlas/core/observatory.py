# atlas/src/core/observatory.py

# Standard Modules
from time import perf_counter_ns
from typing import TYPE_CHECKING, Optional
from datetime import datetime, timedelta, timezone
from functools import lru_cache

# Internal Modules
from atlas.utils.logger import handle_log

# External Modules
import swisseph as swe

if TYPE_CHECKING:
    from atlas.models.location import Location


class Observatory:
	_DEFAULT_FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED
	_FRAME_MASK    = swe.FLG_TOPOCTR | swe.FLG_HELCTR | swe.FLG_BARYCTR
	_AXIS_MASK     = swe.FLG_EQUATORIAL
	_ZODIAC_MASK   = swe.FLG_SIDEREAL

	_AYA_ALIASES = {
	    "lahiri":     "L",
	    "fagan":      "F",
	    "krishna":    "K",
	    "raman":      "R",
	    "yukteshwar": "Y",
	    "deluce":     "D",
	}

	_HSYS_ALIASES = {
        "placidus": "P", "koch": "K", "porphyry": "O", "regiomontanus": "R",
        "campanus": "C", "equal": "A", "whole": "W", "wholesign": "W", "ws": "W",
    }

	def __init__(
		self,
		ephe_path: str = "",
		dt: Optional[datetime] = None,
		location: Optional["Location"] = None,
		hsys: str = "P",
		verbose: bool = False
	):
		self._ephe_path    = ephe_path
		self._flags        = self._DEFAULT_FLAGS
		self._coord_system = "ecliptic"
		self._topo: tuple[float, float, float] = (0.0, 0.0, 0.0)
		self._hsys         = hsys
		self._verbose      = verbose
		self.dt            = dt

		# Cache
		self._jd_cache: float | None = None
		self._jd_dt: datetime | None = None

		self.set_ephe_path(ephe_path)

		if location is not None:
			self._location = location
		else:
			self.__location = None

		if verbose:
			handle_log(
				"info",
				"initialized Observatory (dt=%s, location=%s)",
				dt, location,
				source="observatory"
			)


	 #=======#
	# SWE API #
	 #=======#

	# Set ephemeris file path
	def set_ephe_path(self, ephe_path: str) -> None:
		self._ephe_path = ephe_path
		swe.set_ephe_path(ephe_path)
		if self._verbose:
			handle_log("info", "set ephemeris path to %s", ephe_path)

	# Set topography; re-applies ephe path since some SwissEph versions reset it internally
	def _set_ephe_topo(self, lat: float, lon: float, alt: float) -> None:
		swe.set_topo(lon, lat, alt)
		swe.set_ephe_path(self._ephe_path)
		self._topo = (lat, lon, alt)

	@staticmethod
	@lru_cache(maxsize=512)
	def _cached_calc(target_id: int, jd: float, flags: int) -> tuple:
		return swe.calc_ut(jd, target_id, flags)

	@staticmethod
	@lru_cache(maxsize=256)
	def _cached_fixstar(name: str, jd: float, flags: int) -> tuple:
		return swe.fixstar2(name, jd, flags)

	@staticmethod
	@lru_cache(maxsize=128)
	def _cached_star_mag(name: str) -> Optional[float]:
		try:
			result = swe.fixstar_mag(name)
			return float(result[0]) if result else None
		except Exception:
			return None

	# Convert equatorial pos to (alt, az, ha) using cached topo
	@staticmethod
	def _to_horizontal(pos: tuple, jd: float, topo: tuple[float, float, float]) -> tuple[float, float, float]:
		ra, dec         = pos[0], pos[1]
		lat, lon, alt_m = topo
		geopos          = (lon, lat, alt_m)
		# swe.azalt returns azimuth measured from south through west;
		# convert to north-based (compass bearing) by adding 180°
		az_s, _, alt_app = swe.azalt(jd, swe.EQU2HOR, geopos, 1013.25, 15.0, (ra, dec, 1.0))
		az               = (az_s + 180.0) % 360.0
		lst              = (swe.sidtime(jd) * 15.0 + lon) % 360
		ha               = (lst - ra) % 360
		ha               = ha - 360 if ha > 180 else ha
		return alt_app, az, ha


	 #=========#
	# INTERNALS #
	 #=========#

	@property
	def _location(self) -> Optional["Location"]:
		return self.__location

	@_location.setter
	def _location(self, location: "Location") -> None:
		self.__location = location
		if location is not None:
			self._set_ephe_topo(location.lat, location.lon, location.alt)
			if self._verbose:
				handle_log(
					"info",
					"ok topo set (lat=%.6f, lon=%.6f, alt=%.1f)",
					location.lat, location.lon, location.alt,
					source="observatory"
				)

	@property
	def _jd(self) -> float:
		dt = self.dt or datetime.now(timezone.utc)
		if self._verbose and self.dt is None:
			handle_log(
				"warning",
				"warning _jd: observatory time null; defaulting to present UTC: %s",
				dt,
				source="observatory"
			)

		if (self._jd_dt == dt) and (self._jd_cache is not None):
			return self._jd_cache

		hour = (dt.hour + dt.minute / 60 + dt.second / 3600 + dt.microsecond / 3_600_000_000)
		jd   = swe.julday(dt.year, dt.month, dt.day, hour, swe.GREG_CAL)

		self._jd_cache = jd
		self._jd_dt    = dt
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
		if t_delta:
			if self.dt:
				dt_temp  = self.dt
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

		if l_delta:
			if self._location:
				dlat, dlon, dalt = l_delta
				old_loc          = self._location
				new_loc          = type(old_loc)(lat=old_loc.lat + dlat, lon=old_loc.lon + dlon, alt=old_loc.alt + dalt)
				self._location   = new_loc
				if self._verbose:
					handle_log(
						"info",
						"ok observatory location shift ((%f, %f, %f) to (%f, %f, %f))",
						old_loc.lat, old_loc.lon, old_loc.alt,
						self._location.lon, self._location.lat, self._location.alt, # type: ignore
						source="observatory"
					)
			else:
				handle_log("error", "bad observatory location shift: location not set")
				raise ValueError("Failed to shift observatory location: location is not yet set")

		return self

	# Align the zodiac mode
	def align(self, zodiac: str, aya: str | None = None):
		if zodiac.lower() == "tropical":
			self._flags &= ~self._ZODIAC_MASK
		elif zodiac.lower() == "sidereal":
			self._flags |= swe.FLG_SIDEREAL

		if aya:
			aya_code = self._AYA_ALIASES.get(aya.lower())
			if not aya_code:
				handle_log("error", "bad observatory alignment: ayanamsa not found (aya=%s)", aya)
				raise ValueError(f"Unknown ayanamsa {aya}")
			match aya_code:
				case "L": swe.set_sid_mode(swe.SIDM_LAHIRI,        0.0, 0.0)
				case "F": swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY, 0.0, 0.0)
				case "K": swe.set_sid_mode(swe.SIDM_KRISHNAMURTI,  0.0, 0.0)
				case "R": swe.set_sid_mode(swe.SIDM_RAMAN,         0.0, 0.0)
				case "Y": swe.set_sid_mode(swe.SIDM_YUKTESHWAR,    0.0, 0.0)
				case "D": swe.set_sid_mode(swe.SIDM_DELUCE,        0.0, 0.0)

		if self._verbose:
			handle_log("info", "ok observatory alignment (zodiac=%s, aya=%s, flags=%s)", zodiac, aya, self._flags)
		return self

	# Set coordinate system
	def project(self, system: str):
		self._coord_system = system.lower()
		if self._coord_system == "ecliptic":
			self._flags &= ~self._AXIS_MASK
		elif self._coord_system in ("equatorial", "horizontal"):
			self._flags |= swe.FLG_EQUATORIAL

		if self._verbose:
			handle_log("info", "ok observatory projection (system=%s, flags=%s)", system, self._flags)
		return self

	# Orient the reference frame
	def orient(self, frame: str):
		match frame.lower():
			case "geocentric":
				self._flags &= ~self._FRAME_MASK
			case "heliocentric":
				self._flags = (self._flags & ~self._FRAME_MASK) | swe.FLG_HELCTR
			case "barycentric":
				self._flags = (self._flags & ~self._FRAME_MASK) | swe.FLG_BARYCTR
			case "topocentric":
				self._flags = (self._flags & ~self._FRAME_MASK) | swe.FLG_TOPOCTR

		if self._verbose:
			handle_log("info", "ok observatory orientation (frame=%s, flags=%s)", frame, self._flags)
		return self

	# Select the house division system
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
		cusps, ascmc = swe.houses(self._jd, self._location.lat, self._location.lon, self._hsys.encode()) # type: ignore

		if self._verbose:
			handle_log("info", "ok observatory cast (dt=%s, location=%s)", self.dt, self._location)

		return cusps, ascmc

	# Observe a target — routes to planet or star query based on ID type
	def observe(self, target_id: int | str) -> tuple:
		if isinstance(target_id, int):
			t0       = perf_counter_ns()
			pos, ret = self._cached_calc(target_id, self._jd, self._flags)
			if self._verbose:
				te = (perf_counter_ns() - t0) / 1_000_000
				handle_log("info", "calc_ut(target=%i, jd=%.6f) -> ret=%i; took %.2f ms", target_id, self._jd, ret, te)
		else:
			t0 = perf_counter_ns()
			try:
				xx, _, ret = self._cached_fixstar(target_id, self._jd, self._flags)
			except Exception:
				raise ValueError(f"star not found: '{target_id}' — check spelling or sefstars.txt")
			pos = xx
			if self._verbose:
				te = (perf_counter_ns() - t0) / 1_000_000
				handle_log("info", "fixstar2(name=%s, jd=%.6f) -> ret=%i; took %.2f ms", target_id, self._jd, ret, te)

		if ret < 0:
			handle_log(
				"error",
				"bad observatory observation; (error-code=%i, target_id=%s, dt=%s, location=%s)",
				ret, target_id, self.dt, self._location
			)
			raise RuntimeError(f"SwissEph error-code {ret} for target: {target_id}")

		if self._coord_system == "horizontal":
			pos = self._to_horizontal(pos, self._jd, self._topo)

		if self._verbose:
			handle_log(
				"info",
				"ok observatory observation; (target=%s, dt=%s, location=%s)",
				target_id, self.dt, self._location
			)
		return pos

	# Retrieve a static catalog attribute for a target
	def measure(self, target_id: str, attribute: str) -> Optional[float]:
		match attribute:
			case "star_magnitude":
				return self._cached_star_mag(target_id)
			case _:
				raise ValueError(f"unknown measurable attribute: '{attribute}'")

	# Profile a target
	def profile(self, target_id: int) -> tuple:
		t0         = perf_counter_ns()
		pheno_now  = swe.pheno_ut(self._jd,        target_id, self._flags)[:5]
		pheno_prev = swe.pheno_ut(self._jd - 1e-5, target_id, self._flags)[:5]

		# phase_angle (index 0) decreases waxing→full: more numerically stable at full moon than illumination
		waxing       = pheno_now[0] <= pheno_prev[0]
		waxing_elong = pheno_now[2] >= pheno_prev[2]
		result       = (*pheno_now, waxing, waxing_elong)

		if self._verbose:
			te = (perf_counter_ns() - t0) / 1_000_000
			handle_log(
				"info",
				"ok observatory profile; (target ID=%i, dt=%s, location=%s, took %.2f ms)",
				target_id, self.dt, self._location, te
			)

		return result
