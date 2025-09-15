# atlas/src/models/topo.py

# Standard libraries
from dataclasses import dataclass

@dataclass
class Location:
    lat: float
    lon: float
    alt: float
