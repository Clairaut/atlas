# atlas/src/core/interpreter.py

# Standard libraries
from typing import TYPE_CHECKING, Optional
from datetime import datetime, timedelta


# Internal libraries
from atlas.utils.logger import handle_log
from atlas.utils.config import load_config
from atlas.models.celestial_state import CelestialState, PHASE_DEFS, ELONGATION_EVENTS
from atlas.models.aspect import Aspect, ASPECT_DEFS, ASPECT_GLYPHS
from atlas.models.event import Event

if TYPE_CHECKING:
	from atlas.core.observatory import Observatory
	from atlas.models.location import Location



class Wizard:
	def __init__(self, observatory: "Observatory", verbose: bool = False):
		self._observatory = observatory
		self._config = load_config()
		self._verbose = verbose


	# Consolidates the transfer of data from observatory to state object
	def _sync_state(self, c: CelestialState, properties: list[str], frames: list[str]):
		
		# Apply position
		if "position" in properties:
			for frame in frames:
				if frame in ("ecliptic", "equatorial"): self._observatory.project(frame)
				else: self._observatory.orient(frame)
				pos = self._observatory.observe(c.id)
				c.apply_pos(pos, frame)
				if self._verbose:
					handle_log("info", "celestial position: frame=%s, pos=%s", frame, pos, source="wizard")
		
		# Apply phenomenon
		if "phenomenon" in properties:
			pheno = self._observatory.profile(c.id)
			c.apply_pheno(pheno)
			if self._verbose:
				handle_log("info", "celestial phenomenon: pheno=%s", pheno, source="wizard")


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
			orbit=target_info.get("orbit", "superior"),
			dt=dt,
			location=location  # type: ignore
		)

		# Setup observatory
		self._observatory.set(dt=dt, location=location).align(zodiac=zodiac)

		# If positional properties are requested
		self._sync_state(c, properties=properties, frames=frames)

		return c

	# Return a time-ordered list of states for a single body over a date range
	def conjure_celestial_trace(
		self,
		target:   str,
		start_dt: datetime,
		end_dt:   datetime,
		step:     timedelta,
		location: "Location",
		zodiac:   str = "tropical",
		frames:   list[str] = ["ecliptic"],
	) -> list[CelestialState]:
		
		target_info = self._config["celestials"].get(target.lower())
		if not target_info:
			raise ValueError(f"Target, {target}, could not be found.")

		trace: list[CelestialState] = []

		# Initialize the "session"
		self._observatory.set(dt=start_dt, location=location).align(zodiac)

		while self._observatory.dt <= end_dt:
			state = CelestialState(
				id=target_info["id"],
				glyph=target_info["glyph"],
				name=target_info["name"],
				orbit=target_info.get("orbit", "superior"),
				dt=self._observatory.dt,
				location=location
			)
			
			# Use the shared sync logic without re-aligning location/zodiac
			self._sync_state(state, ["position"], frames)
			trace.append(state)

			# Advance the observatory and the loop
			self._observatory.shift(t_delta=step)
			
		return trace


	# Cast the 12 house cusps for a given dt and location
	def conjure_houses(
		self,
		dt: datetime,
		location: "Location",
		zodiac: str = "tropical",
	) -> list[float]:
		self._observatory.set(dt=dt, location=location)
		self._observatory.align(zodiac=zodiac)
		cusps, _ = self._observatory.cast()
		if len(cusps) == 13:
			return list(cusps[1:13])
		return list(cusps[:12])



	# Detect transit events (aspects, ingresses, stations, phase events) over a date range
	def conjure_events(
		self,
		targets:     list[str],
		start_dt:    datetime,
		end_dt:      datetime,
		location:    "Location",
		zodiac:      str = "tropical",
		event_types: list[str] = ["aspect", "ingress", "station", "phase", "elongation"],
		step:        timedelta = timedelta(hours=1),
	) -> list[Event]:
		events:      list[Event] = []
		current      = start_dt
		prev_states: Optional[list[CelestialState]] = None

		while current <= end_dt:
			states = [
				self.conjure_celestial_state(
					dt=current, location=location, target=t,
					zodiac=zodiac, properties=["position", "phenomenon"], frames=["ecliptic"],
				)
				for t in targets
			]

			if prev_states is not None:
				prev_dt = current - step
				if "aspect"  in event_types: events += self._scan_aspects(states, prev_states, targets, prev_dt, current, location, zodiac)
				if "ingress" in event_types: events += self._scan_ingresses(states, prev_states, targets, prev_dt, current, location, zodiac)
				if "station" in event_types: events += self._scan_stations(states, prev_states, targets, prev_dt, current, location, zodiac)
				if "phase"      in event_types: events += self._scan_phases(states, prev_states, targets, prev_dt, current, location, zodiac)
				if "elongation" in event_types: events += self._scan_elongation(states, prev_states, targets, prev_dt, current, location, zodiac)

			prev_states = states
			current    += step

		events.sort(key=lambda e: e.dt)
		return events

	# Compute all aspects between a list of celestial states (pure geometry, no ephemeris calls)
	def conjure_aspects(self, celestials: list[CelestialState]) -> list[Aspect]:
		aspects: list[Aspect] = []
		for i in range(len(celestials)):
			for j in range(i + 1, len(celestials)):
				a, b = celestials[i], celestials[j]
				if a.lon is None or b.lon is None:
					continue
				diff = self._angular_diff(a.lon, b.lon)
				for angle, name, orb_limit in ASPECT_DEFS:
					if abs(diff - angle) <= orb_limit:
						aspects.append(Aspect(name=name, body_one=a, body_two=b, orb=abs(diff - angle)))
						break
		return aspects



	# -------------------------------------------------------------------------
	# Scan helpers — detect event crossings between two consecutive timesteps
	# -------------------------------------------------------------------------

	# Detect pairwise aspect crossings between prev and current timestep
	def _scan_aspects(
		self,
		states: list[CelestialState], prev_states: list[CelestialState],
		targets: list[str], prev_dt: datetime, current: datetime,
		location: "Location", zodiac: str,
	) -> list[Event]:
		events: list[Event] = []
		for i in range(len(states)):
			for j in range(i + 1, len(states)):
				a, b   = states[i], states[j]
				pa, pb = prev_states[i], prev_states[j]
				if a.lon is None or b.lon is None or pa.lon is None or pb.lon is None:
					continue
				diff_now  = self._angular_diff(a.lon,  b.lon)
				diff_prev = self._angular_diff(pa.lon, pb.lon)
				for angle, name, orb_limit in ASPECT_DEFS:
					res_now  = diff_now  - angle
					res_prev = diff_prev - angle
					if res_prev * res_now <= 0 and abs(res_now) <= orb_limit:
						exact_dt = self._bisect_event(
							lambda t, i=i, j=j, angle=angle: self._aspect_residual(targets[i], targets[j], t, location, zodiac, angle),
							prev_dt, current,
						)
						events.append(Event(
							type=    "aspect",
							dt=      exact_dt,
							body=    a.name,
							body_two=b.name,
							detail=  name,
							glyph=   ASPECT_GLYPHS.get(name, '?'),
							orb=     0.0,
						))
						break
		return events

	# Detect sign ingress crossings for each body
	def _scan_ingresses(
		self,
		states: list[CelestialState], prev_states: list[CelestialState],
		targets: list[str], prev_dt: datetime, current: datetime,
		location: "Location", zodiac: str,
	) -> list[Event]:
		from atlas.models.celestial_state import SIGNS
		events: list[Event] = []
		for k, (state, prev) in enumerate(zip(states, prev_states)):
			if state.lon is None or prev.lon is None:
				continue
			if int(state.lon // 30) != int(prev.lon // 30):
				sign_name = SIGNS[int(state.lon // 30) % 12][1]
				exact_dt  = self._bisect_event(
					lambda t, k=k: self._ingress_residual(targets[k], t, location, zodiac),
					prev_dt, current,
				)
				events.append(Event(
					type=  "ingress",
					dt=    exact_dt,
					body=  state.name,
					detail=sign_name,
					glyph= self._config["celestials"].get(targets[k], {}).get("glyph", "?"),
				))
		return events

	# Detect retrograde / direct station crossings for each body
	def _scan_stations(
		self,
		states: list[CelestialState], prev_states: list[CelestialState],
		targets: list[str], prev_dt: datetime, current: datetime,
		location: "Location", zodiac: str,
	) -> list[Event]:
		events: list[Event] = []
		for k, (state, prev) in enumerate(zip(states, prev_states)):
			if state.dlon is None or prev.dlon is None:
				continue
			if prev.dlon * state.dlon < 0:
				exact_dt = self._bisect_event(
					lambda t, k=k: self._station_residual(targets[k], t, location, zodiac),
					prev_dt, current,
				)
				events.append(Event(
					type=  "station",
					dt=    exact_dt,
					body=  state.name,
					detail="retrograde" if state.dlon < 0 else "direct",
					glyph= self._config["celestials"].get(targets[k], {}).get("glyph", "?"),
				))
		return events

	# Detect phase crossings for all bodies using SwissEph phase data
	def _scan_phases(
		self,
		states: list[CelestialState], prev_states: list[CelestialState],
		targets: list[str], prev_dt: datetime, current: datetime,
		location: "Location", zodiac: str,
	) -> list[Event]:
		events: list[Event] = []
		for k, (state, prev) in enumerate(zip(states, prev_states)):
			# Only inferior planets and satellites have crossing-based phase events
			if state.orbit not in ("inferior", "satellite"):
				continue
			ang_now  = state.phase_cycle
			ang_prev = prev.phase_cycle
			if ang_now is None or ang_prev is None:
				continue
			body_glyph = self._config["celestials"].get(targets[k], {}).get("glyph", "?")
			for target_angle, label, _ in PHASE_DEFS:
				res_now  = self._normalize_residual(ang_now  - target_angle)
				res_prev = self._normalize_residual(ang_prev - target_angle)
				if res_prev * res_now <= 0 and abs(res_now) < 90:
					exact_dt = self._bisect_event(
						lambda t, k=k, ta=target_angle: self._phase_residual(targets[k], t, location, zodiac, ta),
						prev_dt, current,
					)
					events.append(Event(type="phase", dt=exact_dt, body=state.name, detail=label.format(name=state.name), glyph=body_glyph))
		return events

	# Detect synodic crossing events for superior planets (conjunction, quadrature, opposition)
	def _scan_elongation(
		self,
		states: list[CelestialState], prev_states: list[CelestialState],
		targets: list[str], prev_dt: datetime, current: datetime,
		location: "Location", zodiac: str,
	) -> list[Event]:
		events: list[Event] = []
		for k, (state, prev) in enumerate(zip(states, prev_states)):
			if state.orbit != "superior":
				continue
			ang_now  = state.elong_cycle
			ang_prev = prev.elong_cycle
			if ang_now is None or ang_prev is None:
				continue
			body_glyph = self._config["celestials"].get(targets[k], {}).get("glyph", "?")
			for target_angle, label, glyph in ELONGATION_EVENTS:
				res_now  = self._normalize_residual(ang_now  - target_angle)
				res_prev = self._normalize_residual(ang_prev - target_angle)
				if res_prev * res_now <= 0 and abs(res_now) < 90:
					exact_dt = self._bisect_event(
						lambda t, k=k, ta=target_angle: self._elong_residual(targets[k], t, location, zodiac, ta),
						prev_dt, current,
					)
					events.append(Event(type="elongation", dt=exact_dt, body=state.name,
					                    detail=label.format(name=state.name), glyph=body_glyph))
		return events

	# -------------------------------------------------------------------------
	# Geometry helpers
	# -------------------------------------------------------------------------

	# Shortest angular distance between two ecliptic longitudes [0, 180]
	@staticmethod
	def _angular_diff(lon_a: float, lon_b: float) -> float:
		diff = abs(lon_a - lon_b) % 360
		return 360 - diff if diff > 180 else diff

	# Normalize an angle to [-180, 180]
	@staticmethod
	def _normalize_residual(angle: float) -> float:
		angle = angle % 360
		return angle - 360 if angle > 180 else angle

	# -------------------------------------------------------------------------
	# Bisection helpers — scalar crossing functions for exact event timing
	# -------------------------------------------------------------------------

	# Binary search between two datetimes to find exact crossing moment (1-minute tolerance)
	def _bisect_event(self, residual_fn, t_lo: datetime, t_hi: datetime) -> datetime:
		for _ in range(20):
			t_mid = t_lo + (t_hi - t_lo) / 2
			if residual_fn(t_mid) >= 0:
				t_hi = t_mid
			else:
				t_lo = t_mid
			if (t_hi - t_lo).total_seconds() < 60:
				break
		return t_lo + (t_hi - t_lo) / 2

	# Residual for aspect bisection: angular diff between two bodies minus target angle
	def _aspect_residual(self, target_a: str, target_b: str, dt: datetime, location: "Location", zodiac: str, angle: float) -> float:
		a = self.conjure_celestial_state(dt=dt, location=location, target=target_a, zodiac=zodiac, properties=["position"], frames=["ecliptic"])
		b = self.conjure_celestial_state(dt=dt, location=location, target=target_b, zodiac=zodiac, properties=["position"], frames=["ecliptic"])
		if a.lon is None or b.lon is None:
			return 0.0
		return self._angular_diff(a.lon, b.lon) - angle

	# Residual for ingress bisection: fractional sign position (crosses 0 at sign boundary)
	def _ingress_residual(self, target: str, dt: datetime, location: "Location", zodiac: str) -> float:
		state = self.conjure_celestial_state(dt=dt, location=location, target=target, zodiac=zodiac, properties=["position"], frames=["ecliptic"])
		if state.lon is None:
			return 0.0
		return (state.lon % 30) - 15

	# Residual for station bisection: dlon crosses 0 at station moment
	def _station_residual(self, target: str, dt: datetime, location: "Location", zodiac: str) -> float:
		state = self.conjure_celestial_state(dt=dt, location=location, target=target, zodiac=zodiac, properties=["position"], frames=["ecliptic"])
		return state.dlon or 0.0

	# Residual for phase bisection: body's phase_cycle angle minus target phase angle
	def _phase_residual(self, target: str, dt: datetime, location: "Location", zodiac: str, target_angle: float) -> float:
		state = self.conjure_celestial_state(dt=dt, location=location, target=target, zodiac=zodiac, properties=["phenomenon"], frames=["ecliptic"])
		if state.phase_cycle is None:
			return 0.0
		return self._normalize_residual(state.phase_cycle - target_angle)

	# Residual for elongation bisection: elong_cycle minus target synodic angle
	def _elong_residual(self, target: str, dt: datetime, location: "Location", zodiac: str, target_angle: float) -> float:
		state = self.conjure_celestial_state(dt=dt, location=location, target=target, zodiac=zodiac, properties=["phenomenon"], frames=["ecliptic"])
		if state.elong_cycle is None:
			return 0.0
		return self._normalize_residual(state.elong_cycle - target_angle)
