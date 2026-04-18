# atlas/src/utils/constellation.py
# IAU constellation lookup using Roman (1987) boundary data (B1875.0 epoch)

# Standard Modules
import math
from pathlib import Path
from functools import lru_cache
from typing import Optional


# Full constellation name map keyed by IAU abbreviation
_NAMES: dict[str, str] = {
    "And": "Andromeda",     "Ant": "Antlia",        "Aps": "Apus",
    "Aql": "Aquila",        "Aqr": "Aquarius",      "Ara": "Ara",
    "Ari": "Aries",         "Aur": "Auriga",        "Boo": "Boötes",
    "Cae": "Caelum",        "Cam": "Camelopardalis","Cap": "Capricornus",
    "Car": "Carina",        "Cas": "Cassiopeia",    "Cen": "Centaurus",
    "Cep": "Cepheus",       "Cet": "Cetus",         "Cha": "Chamaeleon",
    "Cir": "Circinus",      "CMa": "Canis Major",   "CMi": "Canis Minor",
    "Cnc": "Cancer",        "Col": "Columba",       "Com": "Coma Berenices",
    "CrA": "Corona Australis","CrB": "Corona Borealis","Crt": "Crater",
    "Cru": "Crux",          "Crv": "Corvus",        "CVn": "Canes Venatici",
    "Cyg": "Cygnus",        "Del": "Delphinus",     "Dor": "Dorado",
    "Dra": "Draco",         "Equ": "Equuleus",      "Eri": "Eridanus",
    "For": "Fornax",        "Gem": "Gemini",        "Gru": "Grus",
    "Her": "Hercules",      "Hor": "Horologium",    "Hya": "Hydra",
    "Hyi": "Hydrus",        "Ind": "Indus",         "Lac": "Lacerta",
    "Leo": "Leo",           "Lep": "Lepus",         "Lib": "Libra",
    "LMi": "Leo Minor",     "Lup": "Lupus",         "Lyn": "Lynx",
    "Lyr": "Lyra",          "Men": "Mensa",         "Mic": "Microscopium",
    "Mon": "Monoceros",     "Mus": "Musca",         "Nor": "Norma",
    "Oct": "Octans",        "Oph": "Ophiuchus",     "Ori": "Orion",
    "Pav": "Pavo",          "Peg": "Pegasus",       "Per": "Perseus",
    "Phe": "Phoenix",       "Pic": "Pictor",        "PsA": "Piscis Austrinus",
    "Psc": "Pisces",        "Pup": "Puppis",        "Pyx": "Pyxis",
    "Ret": "Reticulum",     "Scl": "Sculptor",      "Sco": "Scorpius",
    "Sct": "Scutum",        "Ser": "Serpens",       "Sex": "Sextans",
    "Sge": "Sagitta",       "Sgr": "Sagittarius",   "Tau": "Taurus",
    "Tel": "Telescopium",   "TrA": "Triangulum Australe","Tri": "Triangulum",
    "Tuc": "Tucana",        "UMa": "Ursa Major",    "UMi": "Ursa Minor",
    "Vel": "Vela",          "Vir": "Virgo",         "Vol": "Volans",
    "Vul": "Vulpecula",     "Pyx": "Pyxis",         "Ser": "Serpens",
}

# Load and parse the boundary data file once at import
@lru_cache(maxsize=1)
def _load_boundaries() -> list[tuple[float, float, float, str]]:
    data_path = Path(__file__).parent.parent / "data" / "constellations.dat"
    boundaries = []
    with open(data_path) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 4:
                ra_low, ra_high, dec_low, abbr = float(parts[0]), float(parts[1]), float(parts[2]), parts[3]
                boundaries.append((ra_low, ra_high, dec_low, abbr))
    return boundaries


# Precess RA/Dec from J2000.0 to B1875.0 using IAU precession (Lieske 1979)
def _precess_to_b1875(ra_deg: float, dec_deg: float) -> tuple[float, float]:
    # Julian centuries from J2000.0 to B1875.0
    T = -1.2475

    ra  = math.radians(ra_deg)
    dec = math.radians(dec_deg)

    # IAU precession angles (arcseconds → radians)
    zeta  = math.radians((2306.2181 + 1.39656 * T) * T / 3600)
    z     = math.radians((2306.2181 + 1.39656 * T) * T / 3600)
    theta = math.radians((2004.3109 - 0.85330 * T) * T / 3600)

    # Rotation
    a = math.cos(dec) * math.sin(ra + zeta)
    b = math.cos(theta) * math.cos(dec) * math.cos(ra + zeta) - math.sin(theta) * math.sin(dec)
    c = math.sin(theta) * math.cos(dec) * math.cos(ra + zeta) + math.cos(theta) * math.sin(dec)

    ra_1875  = math.degrees(math.atan2(a, b)) + math.degrees(z)
    dec_1875 = math.degrees(math.asin(c))

    # Normalize RA to [0, 360)
    ra_1875 = ra_1875 % 360
    return ra_1875, dec_1875


# Return the full constellation name for a J2000 RA/Dec (degrees)
def identify_constellation(ra_deg: float, dec_deg: float) -> Optional[str]:
    ra_1875, dec_1875 = _precess_to_b1875(ra_deg, dec_deg)
    ra_hours = ra_1875 / 15.0

    boundaries  = _load_boundaries()
    best_abbr   = None
    best_dec    = -90.0

    for ra_low, ra_high, dec_low, abbr in boundaries:
        if dec_1875 < dec_low:
            continue
        # Handle RA wraparound (e.g. ra_low=23h, ra_high=24h wraps to 0h)
        in_range = (ra_low <= ra_hours < ra_high) if ra_low < ra_high else (ra_hours >= ra_low or ra_hours < ra_high)
        if in_range and dec_low > best_dec:
            best_dec  = dec_low
            best_abbr = abbr

    if best_abbr is None:
        return None
    return _NAMES.get(best_abbr, best_abbr)
