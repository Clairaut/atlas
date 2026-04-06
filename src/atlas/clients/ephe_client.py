# src/clients/ephe_client.py

# Standard libraries
from time import perf_counter_ns

# Internal libraries
from atlas.utils.logger import handle_log

# External libraries
import swisseph as swe


class EphemerisClient:
	_DEFAULT_FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED
	_FRAME_MASK   = swe.FLG_TOPOCTR | swe.FLG_HELCTR | swe.FLG_BARYCTR
	_AXIS_MASK    = swe.FLG_EQUATORIAL                 # ecliptic vs equatorial
	_ZODIAC_MASK  = swe.FLG_SIDEREAL                   # tropical vs sidereal


	def __init__(self, ephe_path: str = "", flags: int = _DEFAULT_FLAGS, verbose: bool = False):
		self._ephe_path    = ephe_path
		self._flags        = flags
		self._verbose      = verbose
		self._coord_system = "ecliptic"
		self._topo: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (lat, lon, alt_m)

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

	# Set ephemeris topography; cache for horizontal conversion
	# Re-applies ephe path after set_topo since some SwissEph versions reset it internally
	def set_ephe_topo(self, lat: float, lon: float, alt: float) -> None:
		swe.set_topo(lon, lat, alt)
		swe.set_ephe_path(self._ephe_path)
		self._topo = (lat, lon, alt)

		if self._verbose:
			handle_log("info", "set ephemeris topography to (%f, %f, %f)", lon, lat, alt)


	# Set coordinate system; horizontal uses equatorial flags + post-conversion
	def set_coord_system(self, system: str):
		self._coord_system = system.lower()
		if self._coord_system == "ecliptic":
			self._flags &= ~self._AXIS_MASK
		elif self._coord_system in ("equatorial", "horizontal"):
			self._flags |= swe.FLG_EQUATORIAL

	# Set calculation flags
	def set_reference_frame(self, frame: str):
		if frame.lower() == "geocentric":
			self._flags &= ~self._FRAME_MASK               # clear TOPO, HEL, BARY
		elif frame.lower() == "heliocentric":
			self._flags = (self._flags & ~self._FRAME_MASK) | swe.FLG_HELCTR
		elif frame.lower() == "barycentric":
			self._flags = (self._flags & ~self._FRAME_MASK) | swe.FLG_BARYCTR
		elif frame.lower() == "topocentric":
			self._flags = (self._flags & ~self._FRAME_MASK) | swe.FLG_TOPOCTR

	def set_zodiac(self, zodiac: str):
		if zodiac.lower() == "tropical":
			self._flags &= ~self._ZODIAC_MASK
		elif zodiac.lower() == "sidereal":
			self._flags |= swe.FLG_SIDEREAL

	def set_sidereal_ayanamsa(self, aya_code: str | None):
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
	def query_houses(self, jd: float, lat: float, lon: float, hsys: str = "P") -> tuple:
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

	# Query the position of a SwissEph body; converts to horizontal if coord system is set
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
		if self._coord_system == "horizontal":
			return self._to_horizontal(pos, jd), ret
		return pos, ret

	# Query the phenomenon of SwissEph body
	def query_pheno(self, target_id: int, jd: float) -> tuple[tuple, int]:
		t0 = perf_counter_ns()
		phen = swe.pheno_ut(jd, target_id, self._flags)[:5]
		if self._verbose:
			te = (perf_counter_ns() - t0) / 1_000_000
			handle_log("info", "pheno_ut(target=%i, jd=%.6f); took %.2f ms", target_id, jd, te)
		return phen

	# Convert equatorial pos tuple to (alt, az, ha) using cached topo
	def _to_horizontal(self, pos: tuple, jd: float) -> tuple[float, float, float]:
		ra, dec         = pos[0], pos[1]
		lat, lon, alt_m = self._topo
		geopos          = (lon, lat, alt_m)
		az, _, alt_app  = swe.azalt(jd, swe.EQU2HOR, geopos, 1013.25, 15.0, (ra, dec, 1.0))
		lst             = (swe.sidtime(jd) * 15.0 + lon) % 360
		ha              = (lst - ra) % 360
		ha              = ha - 360 if ha > 180 else ha
		return alt_app, az, ha