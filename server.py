# Standard Modules
import os
from datetime import datetime, timezone
from pathlib import Path

# Internal Modules
from atlas.core.wizard import Wizard
from atlas.core.observatory import Observatory
from atlas.clients.ephe_client import EphemerisClient
from atlas.models.celestial_state import CelestialState
from atlas.models.location import Location
from atlas.utils.config import load_config

# External Modules
from flask import Flask, jsonify, request
import swisseph as swe


app = Flask(__name__)

# Load config and initialize Atlas once at startup
config    = load_config()
ephe_path = config.get("ephemeris", {}).get("path") or os.fspath(Path.home() / ".ephe")
_lat: float = config.get("location", {}).get("lat", 0)
_lon: float = config.get("location", {}).get("lon", 0)
_alt: float = config.get("location", {}).get("alt", 0)

_client = EphemerisClient(ephe_path)
_loc    = Location(lat=_lat, lon=_lon, alt=_alt)
_obs    = Observatory(ephe_client=_client, dt=datetime.now(timezone.utc), location=_loc)
_wizard = Wizard(observatory=_obs)


# Serialize a CelestialState to a JSON-safe dict
def _serialize(state: CelestialState) -> dict:
    sign_glyph, sign_name = state.sign
    phase = state.phase  # None for stars (orbit="star")
    return {
        "glyph":           state.glyph,
        "name":            state.name,
        "orbit":           state.orbit,
        "lon":             state.lon,
        "lat":             state.lat,
        "dist":            state.dist,
        "dlon":            state.dlon,
        "elong":           state.elong,
        "app_mag":         state.app_mag,
        "app_diam":        state.app_diam,
        "illuminated_pct": round((state.phase_illuminated or 0) * 100, 1),
        "retrograde":      state.retrograde,
        "sign":            sign_name,
        "sign_glyph":      sign_glyph,
        "orb":             round(state.orb, 4),
        "phase":           phase[0] if phase else None,
        "phase_glyph":     phase[1] if phase else None,
    }


# Return current positions for all configured celestial bodies
@app.get("/observe")
def observe():
    lat: float = request.args.get("lat", default=_lat, type=float)  # type: ignore
    lon: float = request.args.get("lon", default=_lon, type=float)  # type: ignore
    alt: float = request.args.get("alt", default=_alt, type=float)  # type: ignore

    swe.set_ephe_path(ephe_path)   # SwissEph path is process-global; re-set per request
    now      = datetime.now(timezone.utc)
    location = Location(lat=lat, lon=lon, alt=alt)
    bodies   = {}

    for target in config.get("celestials", {}):
        state = _wizard.conjure_celestial_state(
            dt         = now,
            location   = location,
            target     = target,
            properties = ["position", "phenomenon"],
            frames     = ["ecliptic"],
        )
        bodies[target] = _serialize(state)

    return jsonify({
        "dt":       now.isoformat(),
        "location": {"lat": lat, "lon": lon, "alt": alt},
        "bodies":   bodies,
    })


if __name__ == "__main__":
    app.run(port=5001)
