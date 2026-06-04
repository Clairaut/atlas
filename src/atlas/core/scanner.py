# atlas/src/core/scanner.py

# Standard Modules
from typing import TYPE_CHECKING, Optional
from datetime import datetime, timedelta

# Internal Modules
from atlas.models.celestial_state import CelestialState, PHASE_DEFS, ELONGATION_EVENTS
from atlas.models.aspect import ASPECT_DEFS, ASPECT_GLYPHS, angular_diff
from atlas.models.event import Event

if TYPE_CHECKING:
    from atlas.core.atlas import Atlas


class Scanner:
    def __init__(self, atlas: "Atlas"):
        self._atlas  = atlas
        self._obs    = atlas._observatory
        self._config = atlas._config

    # Detect transit events over a date range
    def scan_events(
        self,
        targets:       list[str],
        start_dt:      datetime,
        end_dt:        datetime,
        location,
        zodiac:        str = "tropical",
        event_types:   list[str] = ["aspect", "ingress", "station", "phase", "elongation", "diurnal"],
        event_details: Optional[list[str]] = None,
        step:          timedelta = timedelta(hours=1),
        limit:         Optional[int] = None,
    ) -> list[Event]:

        def _keep(evts: list[Event]) -> list[Event]:
            return [e for e in evts if event_details is None or any(d.lower() in e.detail.lower() for d in event_details)]

        events:          list[Event] = []
        prev_states:     Optional[list[CelestialState]] = None
        pending_aspects: dict = {}

        pos_systems = ["ecliptic", "equatorial", "horizontal"] if "diurnal" in event_types else ["ecliptic"]
        properties  = ["position", "phenomenon"]

        self._obs.set(dt=start_dt, location=location).align(zodiac=zodiac)

        while self._obs.dt is not None and self._obs.dt <= end_dt:
            states = [self._atlas._sample(t, properties, pos_systems) for t in targets]

            if prev_states is not None:
                current: datetime = self._obs.dt  # type: ignore[assignment]
                prev_dt = current - step
                if "aspect"     in event_types:
                    new_events, pending_aspects = self._scan_aspects(states, prev_states, targets, prev_dt, current, pending_aspects)
                    events += _keep(new_events)
                if "ingress"    in event_types: events += _keep(self._scan_ingresses(states, prev_states, targets, prev_dt, current))
                if "station"    in event_types: events += _keep(self._scan_stations(states, prev_states, targets, prev_dt, current))
                if "phase"      in event_types: events += _keep(self._scan_phases(states, prev_states, targets, prev_dt, current))
                if "elongation" in event_types: events += _keep(self._scan_elongation(states, prev_states, targets, prev_dt, current))
                if "diurnal"    in event_types: events += _keep(self._scan_diurnal(states, prev_states, targets, prev_dt, current))

            prev_states = states
            if limit and len(events) >= limit:
                break
            self._obs.shift(t_delta=step)

        # Emit any aspects still active at end of scan range
        for p in pending_aspects.values():
            if p["at"] is not None:
                events.append(Event(
                    type="aspect", at=p["at"], body=p["body"], body_two=p["body_two"],
                    detail=p["detail"], glyph=p["glyph"], orb=0.0, start=p["start"], end=None,
                ))

        # Fill start/end from consecutive events per body for phase, ingress, elongation
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


     # ========== #
    # SCAN HELPERS #
     # ========== #

    # Detect pairwise aspect crossings, orb entries, and orb exits between prev and current timestep
    def _scan_aspects(
        self,
        states: list[CelestialState], prev_states: list[CelestialState],
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

                diff_now  = angular_diff(a.lon,  b.lon)
                diff_prev = angular_diff(pa.lon, pb.lon)

                for angle, name, orb_limit in ASPECT_DEFS:
                    res_now     = diff_now  - angle
                    res_prev    = diff_prev - angle
                    in_orb_now  = abs(res_now)  <= orb_limit
                    in_orb_prev = abs(res_prev) <= orb_limit
                    key         = (targets[i], targets[j], name)

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
                            pending.pop(key)

        return events, pending

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
                    at=    exact_dt,
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
                    at=    exact_dt,
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

        # Loop through each celestial state
        for k, (state, prev) in enumerate(zip(states, prev_states)):
            ang_now  = state.phase_cycle
            ang_prev = prev.phase_cycle
            
            # If an angle is null, skip
            if ang_now is None or ang_prev is None:
                continue

            # Loop through each phase angle, label and glyph
            for target_angle, label, phase_glyph in PHASE_DEFS:

                # Get the current and previous residual phase angle
                res_now  = _normalize(ang_now  - target_angle)
                res_prev = _normalize(ang_prev - target_angle)

                # If the product of the prev and current residual is zero, then the target has been reached
                if res_prev * res_now <= 0 and abs(res_now) < 90:
                    exact_dt = self._bisect_event(
                        lambda t, k=k, ta=target_angle: self._phase_residual(targets[k], t, ta),
                        prev_dt, current,
                    )
                    events.append(Event(type="phase", at=exact_dt, body=state.name,
                                        detail=label.format(name=state.name.capitalize()), glyph=phase_glyph))
        return events

    # Detect synodic crossing events for superior planets
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
                res_now  = _normalize(ang_now  - target_angle)
                res_prev = _normalize(ang_prev - target_angle)
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
        states: list[CelestialState], prev_states: list[CelestialState],
        targets: list[str], prev_dt: datetime, current: datetime,
    ) -> list[Event]:
        events: list[Event] = []
        for k, (state, prev) in enumerate(zip(states, prev_states)):
            if state.alt is None or state.ha is None or prev.alt is None or prev.ha is None:
                continue

            # Rising: altitude crosses 0 from below
            if prev.alt <= 0 < state.alt:
                exact_dt = self._bisect_event(lambda t, k=k: self._diurnal_residual(targets[k], t, "rising"), prev_dt, current)
                events.append(Event(type="diurnal", at=exact_dt, body=state.name, detail="rising",           glyph="↑"))

            # Setting: altitude crosses 0 from above
            if prev.alt >= 0 > state.alt:
                exact_dt = self._bisect_event(lambda t, k=k: self._diurnal_residual(targets[k], t, "setting"), prev_dt, current)
                events.append(Event(type="diurnal", at=exact_dt, body=state.name, detail="setting",          glyph="↓"))

            # Culmination: hour angle crosses 0 from negative (upper transit)
            if prev.ha <= 0 < state.ha:
                exact_dt = self._bisect_event(lambda t, k=k: self._diurnal_residual(targets[k], t, "culmination"), prev_dt, current)
                events.append(Event(type="diurnal", at=exact_dt, body=state.name, detail="culmination",      glyph="⊕"))

            # Anti-culmination: hour angle crosses ±180 (lower transit)
            if abs(prev.ha) > 150 and abs(state.ha) > 150 and prev.ha * state.ha < 0:
                exact_dt = self._bisect_event(lambda t, k=k: self._diurnal_residual(targets[k], t, "anti-culmination"), prev_dt, current)
                events.append(Event(type="diurnal", at=exact_dt, body=state.name, detail="anti-culmination", glyph="⊗"))

        return events


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

    def _aspect_residual(self, target_a: str, target_b: str, dt: datetime, angle: float) -> float:
        self._obs.set(dt=dt)
        a = self._atlas._sample(target_a, ["position"], ["ecliptic"])
        b = self._atlas._sample(target_b, ["position"], ["ecliptic"])
        if a.lon is None or b.lon is None:
            return 0.0
        return angular_diff(a.lon, b.lon) - angle

    def _ingress_residual(self, target: str, dt: datetime) -> float:
        self._obs.set(dt=dt)
        state = self._atlas._sample(target, ["position"], ["ecliptic"])
        if state.lon is None:
            return 0.0
        return (state.lon % 30) - 15

    def _station_residual(self, target: str, dt: datetime) -> float:
        self._obs.set(dt=dt)
        state = self._atlas._sample(target, ["position"], ["ecliptic"])
        return state.dlon or 0.0

    def _phase_residual(self, target: str, dt: datetime, target_angle: float) -> float:
        self._obs.set(dt=dt)
        state = self._atlas._sample(target, ["phenomenon"], ["ecliptic"])
        if state.phase_cycle is None:
            return 0.0
        return _normalize(state.phase_cycle - target_angle)

    def _elong_residual(self, target: str, dt: datetime, target_angle: float) -> float:
        self._obs.set(dt=dt)
        state = self._atlas._sample(target, ["phenomenon"], ["ecliptic"])
        if state.elong_cycle is None:
            return 0.0
        return _normalize(state.elong_cycle - target_angle)

    def _diurnal_residual(self, target: str, dt: datetime, crossing_type: str) -> float:
        self._obs.set(dt=dt)
        state = self._atlas._sample(target, ["position"], ["horizontal"])
        match crossing_type:
            case "rising" | "setting":
                return state.alt or 0.0
            case "culmination":
                return state.ha or 0.0
            case "anti-culmination":
                return _normalize((state.ha or 0.0) - 180)
        return 0.0


# Normalize an angle to [-180, 180]
def _normalize(angle: float) -> float:
    angle = angle % 360
    return angle - 360 if angle > 180 else angle
