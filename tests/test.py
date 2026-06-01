# Standard libraries
from datetime import datetime
import os

# Internal libraries
from atlas.core.atlas import Atlas
from atlas.core.observatory import Observatory
from atlas.models.location import Location

# External libraries
from pathlib import Path


# Setup Observatory and Atlas
ephe_path  = os.fspath(Path.home() / ".ephe")
observatory = Observatory(ephe_path=ephe_path, dt=datetime.now(), location=Location(lon=0, lat=0, alt=0), verbose=False)
atlas = Atlas(observatory=observatory, verbose=False)


dt = datetime.now()
location = Location(lon=0, lat=0, alt=0)


# Conjure celestial state for the Sun
c = atlas.build_celestial_state(dt=dt, location=location, target="sun")

# Conjure celestial state for the Moon
m = atlas.build_celestial_state(dt=dt, location=location, target="moon")


print(f"Sun Position at {dt} for location ({location.lat}, {location.lon}, {location.alt}m):")
print(f"Zodiac: {c.sign[0]} {c.sign[1]} {round(c.orb, 2)}°")
print(f"Distance: {c.dist} AU")
print("\n")
print(f"Moon Position at {dt} for location ({location.lat}, {location.lon}, {location.alt}m):")
print(f"Zodiac: {m.sign[0]} {m.sign[1]} {round(m.orb, 2)}°")
print(f"Distance: {m.dist} AU")

if m.phase_illuminated is not None:
    if m.phase is not None and m.phase[0] and m.phase[1]:
        print(f"Phase: {m.phase[0]} {m.phase[1]}")
    print(f"Phase Illuminated: {round(m.phase_illuminated * 100, 2)}%")
    print(f"Waxing: {'Yes' if m.waxing else 'No'}")