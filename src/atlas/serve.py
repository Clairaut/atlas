# Standard Modules
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

# Internal Modules
from atlas.core.atlas import Atlas
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
        target_names: list[str] = [t.strip().lower() for t in targets.split(",") if t.strip()] or _available_celestials
        try:
            now = _parse_dt(at) if at else datetime.now(timezone.utc)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        location = (lat, lon, alt)
        bodies   = {}

        try:
            with _lock:
                _ensure_ephe_path()
                for target in target_names:
                    if target not in _available_celestials:
                        continue

                    state = _atlas.locate(
                        dt         = now,
                        location   = location,
                        target     = target,
                        zodiac     = zodiac,
                        properties = ["position", "phenomenon"],
                        systems    = ["ecliptic"],
                    )

                    bodies[target] = state.dict()
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
