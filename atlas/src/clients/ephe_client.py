# src/clients/ephe_client.py

# Standard libraries
from time import perf_counter_ns

# Internal libraries
from atlas.src.utils.logger import handle_log

# External libraries
import swisseph as swe


class EphemerisClient:
	_DEFAULT_FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED
	_FRAME_MASK   = swe.FLG_TOPOCTR | swe.FLG_HELCTR | swe.FLG_BARYCTR
	_AXIS_MASK    = swe.FLG_EQUATORIAL                 # ecliptic vs equatorial
	_ZODIAC_MASK  = swe.FLG_SIDEREAL                   # tropical vs sidereal


	def __init__(self, ephe_path: str = "", flags: int = _DEFAULT_FLAGS, verbose: bool = False):
		self._ephe_path = ephe_path
		self._flags = flags
		self._verbose = verbose

		self.set_ephe_path(ephe_path)
		
		if verbose:
			handle_log("info", "initialized EphemerisClient (ephe_path=%s, flags=%s)", ephe_path, flags) 

	@property
	def flags(self) -> int:
		return self._flags


	 #=============#
	# CONFIGURATION #
	 #=============#

	# Set ephemeris path
	def set_ephe_path(self, ephe_path: str) -> None:
		swe.set_ephe_path(ephe_path)

		if self._verbose:
			handle_log("info", "set ephemeris to %s", ephe_path)

	# Set ephemeris topography
	def set_ephe_topo(self, lat: float, lon: float, alt: float) -> None:
		swe.set_topo(lon, lat, alt)

		if self._verbose:
			handle_log("info", "set ephemeris topography to (%f, %f, %f)", lon, lat, alt)

	# Set zodiac type
	def use_tropical(self):
	    self._flags &= ~self._ZODIAC_MASK
	    return self

	def use_sidereal(self, aya_code: str | None):
		match (aya_code or "").upper():
			case "L": sid_mode = swe.SIDM_LAHIRI
			case "F": sid_mode = swe.SIDM_FAGAN_BRADLEY
			case "K": sid_mode = swe.SIDM_KRISHNAMURTI
			case "R": sid_mode = swe.SIDM_RAMAN
			case "Y": sid_mode = swe.SIDM_YUKTESHWAR
			case "D": sid_mode = swe.SIDM_DELUCE
			case _:   sid_mode = None
		if sid_mode:
			swe.set_sid_mode(sid_mode, 0.0, 0.0)
		self._flags |= swe.FLG_SIDEREAL
		return self

	def use_geocentric(self):
	    self._flags &= ~self._FRAME_MASK               # clear TOPO, HEL, BARY
	    return self

	def use_topocentric(self):
	    self._flags = (self._flags & ~self._FRAME_MASK) | swe.FLG_TOPOCTR
	    return self

	def use_heliocentric(self):
	    self._flags = (self._flags & ~self._FRAME_MASK) | swe.FLG_HELCTR
	    return self

	def use_barycentric(self):
	    self._flags = (self._flags & ~self._FRAME_MASK) | swe.FLG_BARYCTR
	    return self

	def use_ecliptic(self):
	    self._flags &= ~self._AXIS_MASK
	    return self

	def use_equatorial(self):
	    self._flags |= swe.FLG_EQUATORIAL
	    return self


	 #==========#
	# CONVERSION #
	 #==========#

	# Convert datetime (UTC) to Julian date
	@staticmethod
	def convert_to_jd(year: int, month: int, day: int, hour: float) -> float:
		return swe.julday(year, month, day, hour, swe.GREG_CAL)


	 #=======#
	# QUERIES #
	 #=======#

	# Query ayanamsa
	@staticmethod
	def query_ayanamsa(jd: float) -> float:
		return swe.get_ayanamsa_ut(jd)

	# Query ecliptic alignment of the houses
	def query_houses(self, jd: float, lat: float, lon: float, hsys: str = "P") -> tuple[float]:
		t0 = perf_counter_ns()
		cusps, ascmc = swe.houses(jd, lat, lon, hsys)
		if self._verbose:
			te = (perf_counter_ns() - t0) / 1_000_000
			handle_log(
				"info", 
				"houses(hsys=%s, jd=%.6f, lat=%.6f, lon=%.6f) took %.2f ms",
				hsys, jd, lat, lon, te
			)
		return cusps, ascmc

	# Query the position of a SwissEph body
	def query_pos(self, target_id: int, jd: float) -> tuple[tuple, int]:
		t0 = perf_counter_ns()
		pos, ret = swe.calc_ut(jd, target_id, self._flags)
		if self._verbose:
			te = (perf_counter_ns() - t0) / 1_000_000
			handle_log(
				"info", 
				"calc_ut(target=%i, jd=%.6f) -> ret=%i; took %.2f ms", 
				target_id, jd, ret, te
			)
		return pos, ret

	# Query the phenomenon of SwissEph body
	def query_pheno(self, target_id: int, jd: float) -> tuple[tuple, int]:
		t0 = perf_counter_ns()
		phen = swe.pheno_ut(jd, target_id, self._flags)[:5]
		if self._verbose:
			te = (perf_counter_ns() - t0) / 1_000_000
			handle_log("info", "pheno_ut(target=%i, jd=%.6f) -> ret=%i; took %.2f ms", target_id, jd, ret, te)
		return phen