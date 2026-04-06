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



	# Sampling: reads dt and location from observatory; caller must configure observatory first
	def _scry(self, target: str, properties: list[str], frames: list[str]) -> CelestialState:

		# Get target info from configuartion
		target_info = self._config["celestials"].get(target.lower())
		if not target_info:
			raise ValueError(f"Target, {target}, could not be found.")
		
		# Create a celestial state
		c = CelestialState(
			id = target_info["id"], 
			glyph = target_info["glyph"], 
			name = target_info["name"],
			orbit = target_info.get("orbit", "superior"),
			dt = self._observatory.dt,
			location = self._observatory._location
		)

		# Apply position
		if "position" in properties:
			for frame in frames:
				if frame in ("ecliptic", "equatorial", "horizontal"): self._observatory.project(frame)
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

		return c
	
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

		# Setup observatory
		self._observatory.set(dt=dt, location=location).align(zodiac=zodiac)
		
		# Sample the target into a celestial state		
		c: CelestialState = self._scry(target=target, properties=properties, frames=frames)

		return c

	# Return a time-ordered list of states for a single body over a date range
	def conjure_celestial_trace(
		self,
		target: str,
		start_dt: datetime,
		end_dt: datetime,
		step: timedelta,
		location: "Location",
		zodiac: str = "tropical",
		frames: list[str] = ["ecliptic"],
	) -> list[CelestialState]:
		
		trace: list[CelestialState] = []

		# Initialize the observatory once; loop reads dt/location from it via _scry
		self._observatory.set(dt=start_dt, location=location).align(zodiac)

		# While the observatory datetime is less than the end time given, append celestial position and increment time
		while self._observatory.dt <= end_dt:
			trace.append(self._scry(target, ["position"], frames))
			self._observatory.shift(t_delta=step)

		return trace


	# Cast the 12 house cusps for a given dt and location
	def conjure_houses(
		self,
		dt: datetime,
		location: "Location",
		zodiac: str = "tropical",
		hsys: str = "placidus",
	) -> list[float]:

		# Set the observatory date
		self._observatory.set(dt=dt, location=location)

		# Set the zodiac type and house system
		self._observatory.align(zodiac=zodiac)
		self._observatory.domify(hsys)

		# Get the cusps
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
		event_types: list[str] = ["aspect", "ingress", "station", "phase", "elongation", "diurnal"],
		step:        timedelta = timedelta(hours=1),
	) -> list[Event]:
		
		# Initialize events list
		events:      list[Event] = []
		prev_states: Optional[list[CelestialState]] = None

		pos_frames = ["ecliptic", "equatorial", "horizontal"] if "diurnal" in event_types else ["ecliptic"]
		properties = ["position", "phenomenon"]

		# Validate all targets upfront
		for t in targets:
			if not self._config["celestials"].get(t.lower()):
				raise ValueError(f"Target, {t}, could not be found.")

		# Initialize the observatory once
		self._observatory.set(dt=start_dt, location=location).align(zodiac=zodiac)

		# While the observatory datetime is less than the end datetime
		while self._observatory.dt <= end_dt:
			states = [self._scry(t, properties, pos_frames) for t in targets]

			if prev_states is not None:
				current = self._observatory.dt
				prev_dt = current - step
				if "aspect"     in event_types: events += self._scan_aspects(states, prev_states, targets, prev_dt, current)
				if "ingress"    in event_types: events += self._scan_ingresses(states, prev_states, targets, prev_dt, current)
				if "station"    in event_types: events += self._scan_stations(states, prev_states, targets, prev_dt, current)
				if "phase"      in event_types: events += self._scan_phases(states, prev_states, targets, prev_dt, current)
				if "elongation" in event_types: events += self._scan_elongation(states, prev_states, targets, prev_dt, current)
				if "diurnal"    in event_types: events += self._scan_diurnal(states, prev_states, targets, prev_dt, current)

			prev_states = states
			self._observatory.shift(t_delta=step)

		events.sort(key=lambda e: e.dt)
		return events

	# Compute all aspects between a list of celestial states (pure geometry, no ephemeris calls)
	def conjure_aspects(self, celestials: list[CelestialState]) -> list[Aspect]:
		aspects: list[Aspect] = []

		# Loop through each celestial
		for i in range(len(celestials)):

			# Loop through every other celestial
			for j in range(i + 1, len(celestials)):
				a, b = celestials[i], celestials[j]
				if a.lon is None or b.lon is None:
					continue

				# Find the angular difference between the two celestials
				diff = self._angular_diff(a.lon, b.lon)

				# If the angular difference falls within the orb of an aspect, append it to aspects
				for angle, name, orb_limit in ASPECT_DEFS:
					if abs(diff - angle) <= orb_limit:
						aspects.append(Aspect(name=name, body_one=a, body_two=b,
						                      orb=abs(diff - angle), glyph=ASPECT_GLYPHS.get(name, "?")))
						break
		return aspects

	# Compute cross-chart aspects between natal and transit bodies only
	def conjure_transit_aspects(self, natal: list[CelestialState], transit: list[CelestialState]) -> list[Aspect]:

		# Initialize aspects
		aspects: list[Aspect] = []

		# Loop through each natal celestial
		for a in natal:

			# Loop through each transit celestial
			for b in transit:
				if a.lon is None or b.lon is None:
					continue

				# Find the angular difference between the celestials
				diff = self._angular_diff(a.lon, b.lon)

				# If the angle difference falls within the orb of an aspect, append the aspect.
				for angle, name, orb_limit in ASPECT_DEFS:
					if abs(diff - angle) <= orb_limit:
						aspects.append(Aspect(name=name, body_one=a, body_two=b,
						                      orb=abs(diff - angle), glyph=ASPECT_GLYPHS.get(name, "?")))
						break

		return aspects



	 # ========== #
	# SCAN HELPERS #
	 # ========== #

	# Detect pairwise aspect crossings between prev and current timestep
	def _scan_aspects(
		self,
		states: list[CelestialState], prev_states: list[CelestialState],
		targets: list[str], prev_dt: datetime, current: datetime,
	) -> list[Event]:
		
		# Initialize aspect events
		events: list[Event] = []

		# Loop through each given celestial body
		for i in range(len(states)):

			# Loop through the proceeding celestial body
			for j in range(i + 1, len(states)):

				# Initialize each celestial state
				a, b   = states[i], states[j]

				# Initialize each previous celestial state
				pa, pb = prev_states[i], prev_states[j]

				# If an ecliptic longitude is not given, skip
				if a.lon is None or b.lon is None or pa.lon is None or pb.lon is None:
					continue

				# Find the difference between the two angles before and after step
				diff_now  = self._angular_diff(a.lon,  b.lon)
				diff_prev = self._angular_diff(pa.lon, pb.lon)

				# If an angle difference matches the specifications of an aspect bisect the event
				for angle, name, orb_limit in ASPECT_DEFS:
					res_now  = diff_now  - angle
					res_prev = diff_prev - angle


					if res_prev * res_now <= 0 and abs(res_now) <= orb_limit:
						exact_dt = self._bisect_event(
							lambda t, i=i, j=j, angle=angle: self._aspect_residual(targets[i], targets[j], t, angle),
							prev_dt, current,
						)

						# Append the event
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
	) -> list[Event]:
		from atlas.models.celestial_state import SIGNS
		events: list[Event] = []
		for k, (state, prev) in enumerate(zip(states, prev_states)):
			if state.lon is None or prev.lon is None:
				continue
			if int(state.lon // 30) != int(prev.lon // 30):
				sign_name = SIGNS[int(state.lon // 30) % 12][1]
				exact_dt  = self._bisect_event(
					lambda t, k=k: self._ingress_residual(targets[k], t),
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
	) -> list[Event]:
		events: list[Event] = []
		for k, (state, prev) in enumerate(zip(states, prev_states)):
			if state.dlon is None or prev.dlon is None:
				continue
			if prev.dlon * state.dlon < 0:
				exact_dt = self._bisect_event(
					lambda t, k=k: self._station_residual(targets[k], t),
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
	) -> list[Event]:
		events: list[Event] = []
		for k, (state, prev) in enumerate(zip(states, prev_states)):
			if state.orbit not in ("inferior", "satellite"):
				continue
			ang_now  = state.phase_cycle
			ang_prev = prev.phase_cycle
			if ang_now is None or ang_prev is None:
				continue
			for target_angle, label, phase_glyph in PHASE_DEFS:
				res_now  = self._normalize_residual(ang_now  - target_angle)
				res_prev = self._normalize_residual(ang_prev - target_angle)
				if res_prev * res_now <= 0 and abs(res_now) < 90:
					exact_dt = self._bisect_event(
						lambda t, k=k, ta=target_angle: self._phase_residual(targets[k], t, ta),
						prev_dt, current,
					)
					events.append(Event(type="phase", dt=exact_dt, body=state.name,
					                    detail=label.format(name=state.name.capitalize()), glyph=phase_glyph))
		return events

	# Detect synodic crossing events for superior planets (conjunction, quadrature, opposition)
	def _scan_elongation(
		self,
		states: list[CelestialState], prev_states: list[CelestialState],
		targets: list[str], prev_dt: datetime, current: datetime,
	) -> list[Event]:
		events: list[Event] = []
		for k, (state, prev) in enumerate(zip(states, prev_states)):
			ang_now  = state.elong_cycle
			ang_prev = prev.elong_cycle
			if ang_now is None or ang_prev is None:
				continue
			for target_angle, label, elong_glyph in ELONGATION_EVENTS:
				res_now  = self._normalize_residual(ang_now  - target_angle)
				res_prev = self._normalize_residual(ang_prev - target_angle)
				if res_prev * res_now <= 0 and abs(res_now) < 90:
					exact_dt = self._bisect_event(
						lambda t, k=k, ta=target_angle: self._elong_residual(targets[k], t, ta),
						prev_dt, current,
					)
					events.append(Event(type="elongation", dt=exact_dt, body=state.name,
					                    detail=label.format(name=state.name.capitalize()), glyph=elong_glyph))
		return events

	# Detect daily angular crossings: rising, setting, culmination, anti-culmination
	def _scan_diurnal(
		self,
		states: list[CelestialState], prev_states: list[CelestialState],
		targets: list[str], prev_dt: datetime, current: datetime,
	) -> list[Event]:
		events: list[Event] = []
		for k, (state, prev) in enumerate(zip(states, prev_states)):
			if state.alt is None or state.ha is None or prev.alt is None or prev.ha is None:
				continue

			# Rising: altitude crosses 0 from below
			if prev.alt <= 0 < state.alt:
				exact_dt = self._bisect_event(
					lambda t, k=k: self._diurnal_residual(targets[k], t, "rising"),
					prev_dt, current,
				)
				events.append(Event(type="diurnal", dt=exact_dt, body=state.name, detail="rising",           glyph="↑"))

			# Setting: altitude crosses 0 from above
			if prev.alt >= 0 > state.alt:
				exact_dt = self._bisect_event(
					lambda t, k=k: self._diurnal_residual(targets[k], t, "setting"),
					prev_dt, current,
				)
				events.append(Event(type="diurnal", dt=exact_dt, body=state.name, detail="setting",          glyph="↓"))

			# Culmination: hour angle crosses 0 from negative (upper transit)
			if prev.ha <= 0 < state.ha:
				exact_dt = self._bisect_event(
					lambda t, k=k: self._diurnal_residual(targets[k], t, "culmination"),
					prev_dt, current,
				)
				events.append(Event(type="diurnal", dt=exact_dt, body=state.name, detail="culmination",      glyph="⊕"))

			# Anti-culmination: hour angle crosses ±180 (lower transit)
			if abs(prev.ha) > 150 and abs(state.ha) > 150 and prev.ha * state.ha < 0:
				exact_dt = self._bisect_event(
					lambda t, k=k: self._diurnal_residual(targets[k], t, "anti-culmination"),
					prev_dt, current,
				)
				events.append(Event(type="diurnal", dt=exact_dt, body=state.name, detail="anti-culmination", glyph="⊗"))

		return events


	 # ============== #
	# GEOMETRY HELPERS #
	 # ============== #

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


	 # =============== #
	# BISECTION HELPERS #
	 # =============== #

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
	def _aspect_residual(self, target_a: str, target_b: str, dt: datetime, angle: float) -> float:
		self._observatory.set(dt=dt)
		a = self._scry(target_a, ["position"], ["ecliptic"])
		b = self._scry(target_b, ["position"], ["ecliptic"])
		if a.lon is None or b.lon is None:
			return 0.0
		return self._angular_diff(a.lon, b.lon) - angle

	# Residual for ingress bisection: fractional sign position (crosses 0 at sign boundary)
	def _ingress_residual(self, target: str, dt: datetime) -> float:
		self._observatory.set(dt=dt)
		state = self._scry(target, ["position"], ["ecliptic"])
		if state.lon is None:
			return 0.0
		return (state.lon % 30) - 15

	# Residual for station bisection: dlon crosses 0 at station moment
	def _station_residual(self, target: str, dt: datetime) -> float:
		self._observatory.set(dt=dt)
		state = self._scry(target, ["position"], ["ecliptic"])
		return state.dlon or 0.0

	# Residual for phase bisection: body's phase_cycle angle minus target phase angle
	def _phase_residual(self, target: str, dt: datetime, target_angle: float) -> float:
		self._observatory.set(dt=dt)
		state = self._scry(target, ["phenomenon"], ["ecliptic"])
		if state.phase_cycle is None:
			return 0.0
		return self._normalize_residual(state.phase_cycle - target_angle)

	# Residual for elongation bisection: elong_cycle minus target synodic angle
	def _elong_residual(self, target: str, dt: datetime, target_angle: float) -> float:
		self._observatory.set(dt=dt)
		state = self._scry(target, ["phenomenon"], ["ecliptic"])
		if state.elong_cycle is None:
			return 0.0
		return self._normalize_residual(state.elong_cycle - target_angle)

	# Residual for diurnal bisection: altitude (horizon) or hour angle (culmination/anti-culmination)
	def _diurnal_residual(self, target: str, dt: datetime, crossing_type: str) -> float:
		self._observatory.set(dt=dt)
		state = self._scry(target, ["position"], ["horizontal"])
		match crossing_type:
			case "rising" | "setting":
				return state.alt or 0.0
			case "culmination":
				return state.ha or 0.0
			case "anti-culmination":
				return self._normalize_residual((state.ha or 0.0) - 180)
		return 0.0
