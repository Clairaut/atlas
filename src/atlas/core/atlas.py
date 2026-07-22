# atlas/src/core/atlas.py

# Standard Modules
from typing import Optional
from datetime import datetime, timedelta
import logging

# Internal Modules
from atlas.utils.config import load_config
from atlas.core.observatory import Observatory
from atlas.models.celestial import Celestial
from atlas.models.event import Event

Location = tuple[float, float, float]


class Atlas:
    def __init__(
        self,
        ephe_path: str = "",
        dt:        Optional[datetime] = None,
        location:  Optional[Location] = None,
        hsys:      str = "P",
        verbose:   bool = False,
    ):
        self._observatory = Observatory(ephe_path=ephe_path, dt=dt, location=location, hsys=hsys, verbose=verbose)
        self._config      = load_config()
        self._verbose     = verbose

    # Resolve an explicit location, falling back to the configured default
    def _resolve_location(self, location: Optional[Location]) -> Location:
        if location is not None:
            return location
        cfg = self._config.get("location", {})
        return (cfg.get("lat", 0.0), cfg.get("lon", 0.0), cfg.get("alt", 0.0))


    # Reads dt and location from observatory; caller must configure observatory first
    def _sample(self, target: str, properties: list[str], systems: list[str]) -> Celestial:
        target_info = self._config["celestials"].get(target.lower()) or {
            "id":    target,
            "glyph": "✦",
            "name":  target.capitalize(),
            "type": "star",
        }

        c = Celestial(
            id    = target_info["id"],
            glyph = target_info["glyph"],
            name  = target_info["name"],
            type  = target_info.get("type", "superior"),
            color = target_info.get("color"),
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
                    logging.info("celestial position: system=%s, pos=%s", system, pos)

        if "phenomenon" in properties and c.type not in ("star", "node", "derived"):
            pheno = self._observatory.profile(int(c.id))
            c.apply_pheno(pheno)
            if self._verbose:
                logging.info("celestial phenomenon: pheno=%s", pheno)

        if "magnitude" in properties and c.type == "star":
            c.app_mag = self._observatory.measure(str(c.id), "star_magnitude")

        return c


    # Build states for multiple targets
    def survey(
        self,
        targets:    list[str],
        dt:         datetime,
        location:   Optional[Location] = None,
        zodiac:     str = "tropical",
        ayanamsa:   Optional[str] = None,
        properties: list[str] = ["position", "phenomenon"],
        systems:    list[str] = ["ecliptic"],
    ) -> list[Celestial]:
        self._observatory.set(dt=dt, location=self._resolve_location(location)).align(zodiac=zodiac, aya=ayanamsa)
        return [self._sample(target=t, properties=properties, systems=systems) for t in targets]

    # Build a single body state
    def locate(
        self,
        dt:         datetime,
        target:     str,
        location:   Optional[Location] = None,
        zodiac:     str = "tropical",
        ayanamsa:   Optional[str] = None,
        properties: list[str] = ["position", "phenomenon"],
        systems:    list[str] = ["ecliptic"],
    ) -> Celestial:
        self._observatory.set(dt=dt, location=self._resolve_location(location)).align(zodiac=zodiac, aya=ayanamsa)
        return self._sample(target=target, properties=properties, systems=systems)

    # Return a time-ordered list of states for a single body over a date range
    def track(
        self,
        target:   str,
        start_dt: datetime,
        end_dt:   datetime,
        step:     timedelta = timedelta(days=1),
        location: Optional[Location] = None,
        zodiac:   str = "tropical",
        systems:  list[str] = ["ecliptic"],
    ) -> list[Celestial]:
        trace: list[Celestial] = []
        self._observatory.set(dt=start_dt, location=self._resolve_location(location)).align(zodiac)
        while self._observatory.dt is not None and self._observatory.dt <= end_dt:
            trace.append(self._sample(target, ["position"], systems))
            self._observatory.shift(t_delta=step)
        return trace

    # Cast the 12 house cusps for a given dt and location
    def erect(
        self,
        dt:       datetime,
        location: Optional[Location] = None,
        zodiac:   str = "tropical",
        hsys:     str = "placidus",
    ) -> list[float]:
        self._observatory.set(dt=dt, location=self._resolve_location(location)).align(zodiac=zodiac).domify(hsys)
        cusps, _ = self._observatory.cast()
        return list(cusps[1:13] if len(cusps) == 13 else cusps[:12])

    # Detect transit events over a date range
    def transit(
        self,
        targets:       list[str],
        start_dt:      datetime,
        end_dt:        datetime,
        location:      Optional[Location] = None,
        zodiac:        str = "tropical",
        event_types:   list[str] = ["aspect", "ingress", "station", "phase", "elongation", "diurnal"],
        event_details: Optional[list[str]] = None,
        step:          timedelta = timedelta(hours=1),
        limit:         Optional[int] = None,
    ) -> list[Event]:
        from atlas.core.scanner import Scanner
        return Scanner(self).scan_events(
            targets=targets, start_dt=start_dt, end_dt=end_dt, location=self._resolve_location(location),
            zodiac=zodiac, event_types=event_types, event_details=event_details,
            step=step, limit=limit,
        )
