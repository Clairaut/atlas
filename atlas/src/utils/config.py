# src/utils/config.py

# Standard libraries
import os
from pathlib import Path

# Internal libraries
from src.utils.logger import handle_log

# External libraries
import tomllib


DEFAULT_CONFIG = """# Atlas configuration
[ephemeris]
path = ""

[location]
lat = 0.00
lon = 0.00
alt = 4.00

[celestials]
sun     = { glyph = "☉", name = "Sun",     id = 0 }
moon    = { glyph = "☽", name = "Moon",    id = 1 }
mercury = { glyph = "☿", name = "Mercury", id = 2 }
venus   = { glyph = "♀", name = "Venus",   id = 3 }
mars    = { glyph = "♂", name = "Mars",    id = 4 }
jupiter = { glyph = "♃", name = "Jupiter", id = 5 }
saturn  = { glyph = "♄", name = "Saturn",  id = 6 }
uranus  = { glyph = "♅", name = "Uranus",  id = 7 }
neptune = { glyph = "♆", name = "Neptune", id = 8 }
pluto   = { glyph = "⯓", name = "Pluto",   id = 9 }
lilith  = { glyph = "⚸", name = "Lilith",  id = 12 }
chiron  = { glyph = "⚷", name = "Chiron",  id = 15 }
pholus  = { glyph = "⯛", name = "Pholus",  id = 16 }
ceres   = { glyph = "⚳", name = "Ceres",   id = 17 }
pallas  = { glyph = "⚴", name = "Pallas",  id = 18 }
juno    = { glyph = "⚵", name = "Juno",    id = 19 }
vesta   = { glyph = "⚶", name = "Vesta",   id = 20 }
"""

# Load Atlas config, create defaults if missing
def load_config() -> dict:
	config_dir = Path.home() / ".config" / "atlas"
	config_file = config_dir / "atlas.toml"

	# If the configuration file does not exist, make one
	if not config_file.exists():
		config_dir.mkdir(parents=True, exist_ok=True)
		config_file.write_text(DEFAULT_CONFIG)
		handle_log("warning", "config missing - created default at %s", config_file)

	# Open config file with read binary
	with config_file.open("rb") as f:
		config = tomllib.load(f)

	handle_log("info", "config loaded from %s", config_file)
	return config