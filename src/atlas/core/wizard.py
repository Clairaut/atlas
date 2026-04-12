# atlas/src/core/interpreter.py

# Standard libraries
from typing import TYPE_CHECKING, Optional
from datetime import datetime, timedelta


# Internal libraries
from atlas.utils.logger import handle_log
from atlas.utils.config import load_config
from atlas.models.body_state import BodyState, PHASE_DEFS, ELONGATION_EVENTS
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
	def _scry(self, target: str, properties: list[str], frames: list[str]) -> BodyState:

		# Get target info from configuartion
		target_info = self._config["celestials"].get(target.lower())
		if not target_info:
			raise ValueError(f"Target, {target}, could not be found.")
		
		# Create a celestial state
		c = BodyState(
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
	
	# Cast states for multiple targets; sets observatory once
	def conjure_body_states(
		self,
		targets:    list[str],
		dt:         datetime,
		location:   "Location",
		zodiac:     str = "tropical",
		ayanamsa:   Optional[str] = None,
		properties: list[str] = ["position", "phenomenon"],
		frames:     list[str] = ["ecliptic", "equatorial"],
	) -> list[BodyState]:
		self._observatory.set(dt=dt, location=location).align(zodiac=zodiac, aya=ayanamsa)
		return [self._scry(target=t, properties=properties, frames=frames) for t in targets]

	# Cast a single body state; delegates to conjure_body_states
	def conjure_body_state(
		self,
		dt:         datetime,
		location:   "Location",
		target:     str,
		zodiac:     str = "tropical",
		ayanamsa:   Optional[str] = None,
		properties: list[str] = ["position", "phenomenon"],
		frames:     list[str] = ["ecliptic", "equatorial"],
	) -> BodyState:
		return self.conjure_body_states([target], dt=dt, location=location, zodiac=zodiac, ayanamsa=ayanamsa, properties=properties, frames=frames)[0]

	# Return a time-ordered list of states for a single body over a date range
	def conjure_body_trace(
		self,
		target: str,
		start_dt: datetime,
		end_dt: datetime,
		step: timedelta,
		location: "Location",
		zodiac: str = "tropical",
		frames: list[str] = ["ecliptic"],
	) -> list[BodyState]:
		
		trace: list[BodyState] = []

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
		targets:       list[str],
		start_dt:      datetime,
		end_dt:        datetime,
		location:      "Location",
		zodiac:        str = "tropical",
		event_types:   list[str] = ["aspect", "ingress", "station", "phase", "elongation", "diurnal"],
		event_details: Optional[list[str]] = None,
		step:          timedelta = timedelta(hours=1),
		limit:         Optional[int] = None,
	) -> list[Event]:
		
		def _scry_events(new_events: list[Event]) -> list[Event]:
			# Initialize events list
			matched_events: list[Event] = []

			# Loop through each event and append if detail matches filter
			for new_event in new_events:
				if event_details is None or new_event.detail in event_details:
					matched_events.append(new_event)

			return matched_events

		# Initialize events list and aspect orb-tracking state
		events:          list[Event] = []
		prev_states:     Optional[list[BodyState]] = None
		pending_aspects: dict = {}

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
				if "aspect"     in event_types:
					new_events, pending_aspects = self._scan_aspects(states, prev_states, targets, prev_dt, current, pending_aspects)
					events += _scry_events(new_events)
				if "ingress"    in event_types: events += _scry_events(self._scan_ingresses(states, prev_states, targets, prev_dt, current))
				if "station"    in event_types: events += _scry_events(self._scan_stations(states, prev_states, targets, prev_dt, current))
				if "phase"      in event_types: events += _scry_events(self._scan_phases(states, prev_states, targets, prev_dt, current))
				if "elongation" in event_types: events += _scry_events(self._scan_elongation(states, prev_states, targets, prev_dt, current))
				if "diurnal"    in event_types: events += _scry_events(self._scan_diurnal(states, prev_states, targets, prev_dt, current))

			prev_states = states
			if limit and len(events) >= limit:
				break
			self._observatory.shift(t_delta=step)

		# Emit any aspects still active at end of scan range
		for p in pending_aspects.values():
			if p["at"] is not None:
				events.append(Event(
					type="aspect", at=p["at"], body=p["body"], body_two=p["body_two"],
					detail=p["detail"], glyph=p["glyph"], orb=0.0, start=p["start"], end=None,
				))

		# Post-process phases, ingresses, and elongation: fill start/end from consecutive events per body
		for type_key in ("phase", "ingress", "elongation"):
			by_body: dict[str, list[Event]] = {}
			for e in events:
				if e.type == type_key:
					by_body.setdefault(e.body, []).append(e)
			for body_events in by_body.values():
				body_events.sort(key=lambda e: e.at)
				for i, e in enumerate(body_events):
					e.start = body_events[i - 1].at if i > 0 else None
					e.end   = body_events[i + 1].at if i < len(body_events) - 1 else None

		events.sort(key=lambda e: e.at)
		return events[:limit] if limit else events

	# Compute all aspects between a list of celestial states (pure geometry, no ephemeris calls)
	def conjure_aspects(self, celestials: list[BodyState]) -> list[Aspect]:
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
	def conjure_transit_aspects(self, natal: list[BodyState], transit: list[BodyState]) -> list[Aspect]:

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

	# Detect pairwise aspect crossings, orb entries, and orb exits between prev and current timestep
	def _scan_aspects(
		self,
		states: list[BodyState], prev_states: list[BodyState],
		targets: list[str], prev_dt: datetime, current: datetime,
		pending: dict,
	) -> tuple[list[Event], dict]:

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
					res_now      = diff_now  - angle
					res_prev     = diff_prev - angle
					in_orb_now   = abs(res_now)  <= orb_limit
					in_orb_prev  = abs(res_prev) <= orb_limit
					key          = (targets[i], targets[j], name)

					# Orb entry: outside last step, inside this step
					if not in_orb_prev and in_orb_now:
						entry_dt = self._bisect_event(
							lambda t, i=i, j=j, angle=angle, ol=orb_limit:
								ol - abs(self._aspect_residual(targets[i], targets[j], t, angle)),
							prev_dt, current,
						)
						pending[key] = {"start": entry_dt, "at": None, "body": a.name, "body_two": b.name, "detail": name, "glyph": ASPECT_GLYPHS.get(name, "?")}

					# Exact crossing
					if res_prev * res_now <= 0 and in_orb_now:
						exact_dt = self._bisect_event(
							lambda t, i=i, j=j, angle=angle: self._aspect_residual(targets[i], targets[j], t, angle),
							prev_dt, current,
						)
						if key in pending:
							pending[key]["at"] = exact_dt
						else:
							# Aspect was already in orb at scan start — no entry captured
							pending[key] = {"start": None, "at": exact_dt, "body": a.name, "body_two": b.name, "detail": name, "glyph": ASPECT_GLYPHS.get(name, "?")}

					# Orb exit: inside last step, outside this step
					if in_orb_prev and not in_orb_now:
						exit_dt = self._bisect_event(
							lambda t, i=i, j=j, angle=angle, ol=orb_limit:
								abs(self._aspect_residual(targets[i], targets[j], t, angle)) - ol,
							prev_dt, current,
						)
						if key in pending and pending[key]["at"] is not None:
							p = pending.pop(key)
							events.append(Event(
								type="aspect", at=p["at"], body=p["body"], body_two=p["body_two"],
								detail=p["detail"], glyph=p["glyph"], orb=0.0,
								start=p["start"], end=exit_dt,
							))
						elif key in pending:
							pending.pop(key)  # entered and exited orb without exact (shouldn't normally occur)

		return events, pending

	# Detect sign ingress crossings for each body
	def _scan_ingresses(
		self,
		states: list[BodyState], prev_states: list[BodyState],
		targets: list[str], prev_dt: datetime, current: datetime,
	) -> list[Event]:
		from atlas.models.body_state import SIGNS
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
					at=    exact_dt,
					body=  state.name,
					detail=sign_name,
					glyph= self._config["celestials"].get(targets[k], {}).get("glyph", "?"),
				))
		return events

	# Detect retrograde / direct station crossings for each body
	def _scan_stations(
		self,
		states: list[BodyState], prev_states: list[BodyState],
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
					at=    exact_dt,
					body=  state.name,
					detail="retrograde" if state.dlon < 0 else "direct",
					glyph= self._config["celestials"].get(targets[k], {}).get("glyph", "?"),
				))
		return events

	# Detect phase crossings for all bodies using SwissEph phase data
	def _scan_phases(
		self,
		states: list[BodyState], prev_states: list[BodyState],
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
					events.append(Event(type="phase", at=exact_dt, body=state.name,
					                    detail=label.format(name=state.name.capitalize()), glyph=phase_glyph))
		return events

	# Detect synodic crossing events for superior planets (conjunction, quadrature, opposition)
	def _scan_elongation(
		self,
		states: list[BodyState], prev_states: list[BodyState],
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
					events.append(Event(type="elongation", at=exact_dt, body=state.name,
					                    detail=label.format(name=state.name.capitalize()), glyph=elong_glyph))
		return events

	# Detect daily angular crossings: rising, setting, culmination, anti-culmination
	def _scan_diurnal(
		self,
		states: list[BodyState], prev_states: list[BodyState],
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
				events.append(Event(type="diurnal", at=exact_dt, body=state.name, detail="rising",           glyph="↑"))

			# Setting: altitude crosses 0 from above
			if prev.alt >= 0 > state.alt:
				exact_dt = self._bisect_event(
					lambda t, k=k: self._diurnal_residual(targets[k], t, "setting"),
					prev_dt, current,
				)
				events.append(Event(type="diurnal", at=exact_dt, body=state.name, detail="setting",          glyph="↓"))

			# Culmination: hour angle crosses 0 from negative (upper transit)
			if prev.ha <= 0 < state.ha:
				exact_dt = self._bisect_event(
					lambda t, k=k: self._diurnal_residual(targets[k], t, "culmination"),
					prev_dt, current,
				)
				events.append(Event(type="diurnal", at=exact_dt, body=state.name, detail="culmination",      glyph="⊕"))

			# Anti-culmination: hour angle crosses ±180 (lower transit)
			if abs(prev.ha) > 150 and abs(state.ha) > 150 and prev.ha * state.ha < 0:
				exact_dt = self._bisect_event(
					lambda t, k=k: self._diurnal_residual(targets[k], t, "anti-culmination"),
					prev_dt, current,
				)
				events.append(Event(type="diurnal", at=exact_dt, body=state.name, detail="anti-culmination", glyph="⊗"))

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
