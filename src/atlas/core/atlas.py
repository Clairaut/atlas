# atlas/src/core/atlas.py

# Standard Modules
from typing import TYPE_CHECKING, Optional
from datetime import datetime, timedelta

# Internal Modules
from atlas.utils.logger import handle_log
from atlas.utils.config import load_config
from atlas.models.celestial_state import CelestialState
from atlas.models.event import Event

if TYPE_CHECKING:
    from atlas.core.observatory import Observatory
    from atlas.models.location import Location


class Atlas:
    def __init__(self, observatory: "Observatory", verbose: bool = False):
        self._observatory = observatory
        self._config      = load_config()
        self._verbose     = verbose


    # Reads dt and location from observatory; caller must configure observatory first
    def _sample(self, target: str, properties: list[str], systems: list[str]) -> CelestialState:
        target_info = self._config["celestials"].get(target.lower()) or {
            "id":    target,
            "glyph": "✦",
            "name":  target.capitalize(),
            "type": "star",
        }

        c = CelestialState(
            id    = target_info["id"],
            glyph = target_info["glyph"],
            name  = target_info["name"],
            type  = target_info.get("type", "superior"),
            dt       = self._observatory.dt,          # type: ignore[arg-type]
            location = self._observatory._location,   # type: ignore[arg-type]
        )

        if "position" in properties:
            for system in systems:
                if system in ("ecliptic", "equatorial", "horizontal"):
                    self._observatory.project(system)
                else:
                    self._observatory.orient(system)

                # Derived planets (e.g. south node): compute from source + offset
                if c.type == "derived":
                    source_info = self._config["celestials"][target_info["source"]]
                    source_pos  = self._observatory.observe(source_info["id"])
                    offset      = target_info.get("lon_offset", 0)
                    pos         = ((source_pos[0] + offset) % 360, *source_pos[1:])
                else:
                    pos = self._observatory.observe(c.id)

                c.apply_pos(pos, system)
                if self._verbose:
                    handle_log("info", "celestial position: system=%s, pos=%s", system, pos, source="atlas")

        if "phenomenon" in properties and c.type not in ("star", "node", "derived"):
            pheno = self._observatory.profile(int(c.id))
            c.apply_pheno(pheno)
            if self._verbose:
                handle_log("info", "celestial phenomenon: pheno=%s", pheno, source="atlas")

        if "magnitude" in properties and c.type == "star":
            c.app_mag = self._observatory.measure(str(c.id), "star_magnitude")

        return c


    # Build states for multiple targets
    def build_celestial_states(
        self,
        targets:    list[str],
        dt:         datetime,
        location:   "Location",
        zodiac:     str = "tropical",
        ayanamsa:   Optional[str] = None,
        properties: list[str] = ["position", "phenomenon"],
        systems:    list[str] = ["ecliptic"],
    ) -> list[CelestialState]:
        self._observatory.set(dt=dt, location=location).align(zodiac=zodiac, aya=ayanamsa)
        return [self._sample(target=t, properties=properties, systems=systems) for t in targets]

    # Build a single body state
    def build_celestial_state(
        self,
        dt:         datetime,
        location:   "Location",
        target:     str,
        zodiac:     str = "tropical",
        ayanamsa:   Optional[str] = None,
        properties: list[str] = ["position", "phenomenon"],
        systems:    list[str] = ["ecliptic"],
    ) -> CelestialState:
        self._observatory.set(dt=dt, location=location).align(zodiac=zodiac, aya=ayanamsa)
        return self._sample(target=target, properties=properties, systems=systems)

    # Return a time-ordered list of states for a single body over a date range
    def build_celestial_trace(
        self,
        target:   str,
        start_dt: datetime,
        end_dt:   datetime,
        step:     timedelta,
        location: "Location",
        zodiac:   str = "tropical",
        systems:  list[str] = ["ecliptic"],
    ) -> list[CelestialState]:
        trace: list[CelestialState] = []
        self._observatory.set(dt=start_dt, location=location).align(zodiac)
        while self._observatory.dt is not None and self._observatory.dt <= end_dt:
            trace.append(self._sample(target, ["position"], systems))
            self._observatory.shift(t_delta=step)
        return trace

    # Cast the 12 house cusps for a given dt and location
    def build_houses(
        self,
        dt:       datetime,
        location: "Location",
        zodiac:   str = "tropical",
        hsys:     str = "placidus",
    ) -> list[float]:
        self._observatory.set(dt=dt, location=location).align(zodiac=zodiac).domify(hsys)
        cusps, _ = self._observatory.cast()
        return list(cusps[1:13] if len(cusps) == 13 else cusps[:12])

    # Detect transit events over a date range
    def build_events(
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
        from atlas.core.scanner import Scanner
        return Scanner(self).scan_events(
            targets=targets, start_dt=start_dt, end_dt=end_dt, location=location,
            zodiac=zodiac, event_types=event_types, event_details=event_details,
            step=step, limit=limit,
        )
