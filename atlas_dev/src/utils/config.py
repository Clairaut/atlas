# src/utils/config.py

# Standard libraries
from pathlib import Path

# Internal libraries
from atlas_dev.src.utils.logger import handle_log

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
sun     = { glyph = "☉", name = "Sun",     id = 0,  orbit = "star"      }
moon    = { glyph = "☽", name = "Moon",    id = 1,  orbit = "satellite" }
mercury = { glyph = "☿", name = "Mercury", id = 2,  orbit = "inferior"  }
venus   = { glyph = "♀", name = "Venus",   id = 3,  orbit = "inferior"  }
mars    = { glyph = "♂", name = "Mars",    id = 4,  orbit = "superior"  }
jupiter = { glyph = "♃", name = "Jupiter", id = 5,  orbit = "superior"  }
saturn  = { glyph = "♄", name = "Saturn",  id = 6,  orbit = "superior"  }
uranus  = { glyph = "♅", name = "Uranus",  id = 7,  orbit = "superior"  }
neptune = { glyph = "♆", name = "Neptune", id = 8,  orbit = "superior"  }
pluto   = { glyph = "⯓", name = "Pluto",   id = 9,  orbit = "superior"  }
lilith  = { glyph = "⚸", name = "Lilith",  id = 12, orbit = "superior"  }
chiron  = { glyph = "⚷", name = "Chiron",  id = 15, orbit = "superior"  }
pholus  = { glyph = "⯛", name = "Pholus",  id = 16, orbit = "superior"  }
ceres   = { glyph = "⚳", name = "Ceres",   id = 17, orbit = "superior"  }
pallas  = { glyph = "⚴", name = "Pallas",  id = 18, orbit = "superior"  }
juno    = { glyph = "⚵", name = "Juno",    id = 19, orbit = "superior"  }
vesta   = { glyph = "⚶", name = "Vesta",   id = 20, orbit = "superior"  }
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