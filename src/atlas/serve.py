# Standard Modules
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

# Internal Modules
from atlas.core.atlas import Atlas
from atlas.core.observatory import Observatory
from atlas.models.celestial_state import CelestialState
from atlas.models.location import Location
from atlas.utils.config import load_config

if TYPE_CHECKING:
    from fastapi import FastAPI


# Serialize a CelestialState to a JSON-safe dict
def _serialize(state: CelestialState) -> dict:
    sign_glyph, sign_name = state.sign
    phase = state.phase
    return {
        "glyph":           state.glyph,
        "name":            state.name,
        "type":            state.type,
        "lon":             state.lon,
        "lat":             state.lat,
        "dist":            state.dist,
        "dlon":            state.dlon,
        "elong":           state.elong,
        "elong_waxing":    state.elong_waxing,
        "app_mag":         state.app_mag,
        "app_diam":        state.app_diam,
        "retrograde":      state.retrograde,
        "sign":            sign_name,
        "sign_glyph":      sign_glyph,
        "orb":             round(state.orb, 4),
        "phase":             phase[0] if phase else None,
        "phase_glyph":       phase[1] if phase else None,
        "phase_illuminated": round((state.phase_illuminated or 0), 1),
        "phase_angle":       round(state.phase_angle, 2) if state.phase_angle is not None else None,
        "phase_waxing":            state.phase_waxing
    }


# Build and return a configured FastAPI app
def create_app() -> "FastAPI":
    from fastapi import FastAPI, HTTPException

    cfg       = load_config()
    ephe_path = cfg.get("ephemeris", {}).get("path") or os.fspath(Path.home() / ".ephe")
    _lat: float = cfg.get("location", {}).get("lat", 0)
    _lon: float = cfg.get("location", {}).get("lon", 0)
    _alt: float = cfg.get("location", {}).get("alt", 0)

    _loc    = Location(lat=_lat, lon=_lon, alt=_alt)
    _obs    = Observatory(ephe_path=ephe_path, dt=datetime.now(timezone.utc), location=_loc)
    _atlas = Atlas(observatory=_obs)
    _lock = threading.Lock()

    app = FastAPI(title="Atlas", version="0.3.0")

    # Ensure SwissEph path is set per request.
    def _ensure_ephe_path():
        try:
            _obs.set_ephe_path(ephe_path)
        except Exception:
            _obs.set_ephe_path(os.fspath(Path.home() / ".ephe"))

    _available_celestials = list(cfg.get("celestials", {}).keys())

    # Parse a datetime string — ISO format with optional time component
    def _parse_dt(s: str) -> datetime:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        raise ValueError(f"unrecognized datetime format: '{s}'")


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
            now = _parse_dt(at) if at else datetime.now(timezone.utc)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        location = Location(lat=lat, lon=lon, alt=alt)

        try:
            with _lock:
                _ensure_ephe_path()
                cusps = _atlas.build_houses(dt=now, location=location, zodiac=zodiac, hsys=hsys)
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
        target_names: list[str] = [t.strip() for t in targets.split(",") if t.strip()] or _available_celestials
        try:
            now = _parse_dt(at) if at else datetime.now(timezone.utc)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        location = Location(lat=lat, lon=lon, alt=alt)
        bodies   = {}

        try:
            with _lock:
                _ensure_ephe_path()
                for target in target_names:
                    if target not in _available_celestials:
                        continue

                    state = _atlas.build_celestial_state(
                        dt         = now,
                        location   = location,
                        target     = target,
                        zodiac     = zodiac,
                        properties = ["position", "phenomenon"],
                        systems    = ["ecliptic"],
                    )

                    bodies[target] = _serialize(state)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        return {
            "dt":       now.isoformat(),
            "location": {"lat": lat, "lon": lon, "alt": alt},
            "bodies":   bodies,
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
