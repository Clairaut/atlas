# Standard Modules
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

# Internal Modules
from atlas.core.atlas import Atlas
from atlas.models.aspect import build_aspects, build_transit_aspects
from atlas.utils.chrono import convert_to_utc
from atlas.utils.config import load_config

if TYPE_CHECKING:
    from fastapi import FastAPI


# Build and return a configured FastAPI app
def create_app() -> "FastAPI":
    from fastapi import FastAPI, HTTPException

    cfg       = load_config()
    ephe_path = cfg.get("ephemeris", {}).get("path") or os.fspath(Path.home() / ".ephe")
    _lat: float = cfg.get("location", {}).get("lat", 0)
    _lon: float = cfg.get("location", {}).get("lon", 0)
    _alt: float = cfg.get("location", {}).get("alt", 0)

    _loc   = (_lat, _lon, _alt)
    _atlas = Atlas(ephe_path=ephe_path, dt=datetime.now(timezone.utc), location=_loc)
    _lock  = threading.Lock()

    app = FastAPI(title="Atlas", version="0.3.0")

    # Ensure SwissEph path is set per request.
    def _ensure_ephe_path():
        try:
            _atlas._observatory.set_ephe_path(ephe_path)
        except Exception:
            _atlas._observatory.set_ephe_path(os.fspath(Path.home() / ".ephe"))

    _available_celestials = list(cfg.get("celestials", {}).keys())

    # Parse a datetime string. A value carrying an offset, or a trailing Z, is
    # taken at its word. A bare one is read as local time where the observer is,
    # because that is how people write down the moment they mean: reading it as
    # UTC silently moves a chart by the whole offset and changes the ascendant.
    def _parse_dt(s: str, location: tuple) -> datetime:
        try:
            aware = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
            if aware.tzinfo is not None:
                return aware.astimezone(timezone.utc)
        except ValueError:
            pass

        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                naive = datetime.strptime(s.strip(), fmt)
            except ValueError:
                continue
            try:
                return convert_to_utc(naive, location).replace(tzinfo=timezone.utc)
            except Exception as exc:
                # A time that never happened, or happened twice, at a daylight
                # saving boundary. Say which rather than silently picking one.
                raise ValueError(f"'{s}' is ambiguous or does not exist in the timezone at that location") from exc

        raise ValueError(f"unrecognized datetime format: '{s}'")

    # Locate the requested bodies at one moment, keyed by target name
    def _locate(dt: datetime, location: tuple, zodiac: str, targets: "list[str]") -> "dict":
        celestials = {}
        for target in targets:
            if target not in _available_celestials:
                continue

            celestials[target] = _atlas.locate(
                dt         = dt,
                location   = location,
                target     = target,
                zodiac     = zodiac,
                properties = ["position", "phenomenon"],
                systems    = ["ecliptic"],
            )

        return celestials

    # Split a comma-separated target list, falling back to everything configured
    def _resolve_targets(targets: str) -> "list[str]":
        return [target.strip().lower() for target in targets.split(",") if target.strip()] or _available_celestials


    # Return house cusps for a given time, location, and house system
    @app.get("/cast")
    def cast(
        at: str = "",
        zodiac: str = "tropical",
        hsys: str = "placidus",
        lat: float = _lat,
        lon: float = _lon,
        alt: float = _alt,
    ):
        try:
            now = _parse_dt(at, (lat, lon, alt)) if at else datetime.now(timezone.utc)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        location = (lat, lon, alt)

        try:
            with _lock:
                _ensure_ephe_path()
                cusps = _atlas.erect(dt=now, location=location, zodiac=zodiac, hsys=hsys)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        return {
            "dt": now.isoformat(),
            "location": {"lat": lat, "lon": lon, "alt": alt},
            "hsys": hsys,
            "cusps": {str(i + 1): round(c, 6) for i, c in enumerate(cusps)},
        }

    # Return current positions for requested celestial bodies
    @app.get("/observe")
    def observe(
        targets: str = "",
        at: str = "",
        zodiac: str = "tropical",
        lat: float = _lat,
        lon: float = _lon,
        alt: float = _alt,
    ):
        targets = _resolve_targets(targets)
        try:
            now = _parse_dt(at, (lat, lon, alt)) if at else datetime.now(timezone.utc)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        location = (lat, lon, alt)

        try:
            with _lock:
                _ensure_ephe_path()
                bodies = _locate(now, location, zodiac, targets)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        return {
            "dt":       now.isoformat(),
            "location": {"lat": lat, "lon": lon, "alt": alt},
            "bodies":   {name: state.dict() for name, state in bodies.items()},
        }

    # Return aspects within one chart, or — given transit_at — the aspects a second
    # moment makes to it. Both dates are arbitrary; neither moment is privileged.
    @app.get("/compare")
    def compare(
        targets:     str   = "",
        at:          str   = "",
        transit_at:  str   = "",
        zodiac:      str   = "tropical",
        lat:         float = _lat,
        lon:         float = _lon,
        alt:         float = _alt,
        transit_lat: float = _lat,
        transit_lon: float = _lon,
        transit_alt: float = _alt,
    ):
        targets = _resolve_targets(targets)

        try:
            chart_dt   = _parse_dt(at, (lat, lon, alt)) if at else datetime.now(timezone.utc)
            transit_dt = _parse_dt(transit_at, (transit_lat, transit_lon, transit_alt)) if transit_at else None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        location = (lat, lon, alt)

        try:
            with _lock:
                _ensure_ephe_path()
                chart = list(_locate(chart_dt, location, zodiac, targets).values())

                if transit_dt is None:
                    found = build_aspects(chart)
                else:
                    transit = list(_locate(transit_dt, (transit_lat, transit_lon, transit_alt), zodiac, targets).values())
                    found   = build_transit_aspects(chart, transit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        # In transit mode `one` is always the `at` chart and `two` the transiting body
        return {
            "dt":         chart_dt.isoformat(),
            "transit_dt": transit_dt.isoformat() if transit_dt else None,
            "mode":       "transit" if transit_dt else "chart",
            "location":   {"lat": lat, "lon": lon, "alt": alt},
            "aspects": [
                {
                    "name":  a.name,
                    "glyph": a.glyph,
                    "orb":   round(a.orb, 4),
                    "one":   {"name": a.body_one.name, "glyph": a.body_one.glyph, "lon": a.body_one.lon},
                    "two":   {"name": a.body_two.name, "glyph": a.body_two.glyph, "lon": a.body_two.lon},
                }
                for a in found
            ],
        }

    return app


# Start the ASGI server
def run(host: str = "127.0.0.1", port: int = 5001) -> None:
    try:
        import uvicorn

        print(f"Atlas server running at http://{host}:{port}")
        uvicorn.run("atlas.serve:create_app", factory=True, host=host, port=port)
    except ImportError:
        print("FastAPI/Uvicorn is not installed. Run: pip install fastapi uvicorn")
