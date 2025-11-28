# Standard libraries
from datetime import datetime
import os

# Internal libraries
from src.core.wizard import Wizard
from src.core.observatory import Observatory
from src.clients.ephe_client import EphemerisClient
from src.models.topo import Location

# External libraries
from pathlib import Path



ephe_path = Path.home() / ".ephe"
ephe_client = EphemerisClient(os.fspath(ephe_path))
observatory = Observatory(ephe_client=ephe_client, dt=datetime.now(), location=Location(lon=0, lat=0, alt=0), verbose=True)
wizard = Wizard(observatory=observatory, verbose=True)


dt = datetime.now()
location = Location(lon=0, lat=0, alt=0)
c = wizard.conjure_celestial_state(dt=dt, location=location, target="sun")
print(c)