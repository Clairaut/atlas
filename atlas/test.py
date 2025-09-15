# Standard libraries
from datetime import datetime
import os

# Internal libraries
from atlas.src.core.magus import Magus
from atlas.src.core.observatory import Observatory
from atlas.src.clients.ephe_client import EphemerisClient
from atlas.src.models.topo import Location

# External libraries
from pathlib import Path



ephe_path = Path.home() / ".ephe"
ephe_client = EphemerisClient(os.fspath(ephe_path))
observatory = Observatory(ephe_client=ephe_client)
magus = Magus(observatory=observatory)


dt = datetime.now()
location = Location(lon=0, lat=0, alt=0)
magus.conjure_celestial_state(dt=dt, location=location, target="sun")