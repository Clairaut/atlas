# src/utils/config.py

# Standard libraries
from pathlib import Path

# Internal libraries
from atlas.utils.logger import handle_log

# External libraries
import tomllib


DEFAULT_CONFIG = """# Atlas configuration
[ephemeris]
path = ""

[output]
image = ""   # default save path for static charts (.png)
video = ""   # default save path for playback exports (.mp4)

[location]
lat = 0.00
lon = 0.00
alt = 4.00

[celestials]
sun     = { glyph = "☉", name = "Sun",     id = 0,  type = "star"      }
moon    = { glyph = "☽", name = "Moon",    id = 1,  type = "satellite" }
mercury = { glyph = "☿", name = "Mercury", id = 2,  type = "inferior"  }
venus   = { glyph = "♀", name = "Venus",   id = 3,  type = "inferior"  }
mars    = { glyph = "♂", name = "Mars",    id = 4,  type = "superior"  }
jupiter = { glyph = "♃", name = "Jupiter", id = 5,  type = "superior"  }
saturn  = { glyph = "♄", name = "Saturn",  id = 6,  type = "superior"  }
uranus  = { glyph = "♅", name = "Uranus",  id = 7,  type = "superior"  }
neptune = { glyph = "♆", name = "Neptune", id = 8,  type = "superior"  }
pluto   = { glyph = "⯓", name = "Pluto",   id = 9,  type = "superior"  }
lilith  = { glyph = "⚸", name = "Lilith",  id = 12, type = "superior"  }
chiron  = { glyph = "⚷", name = "Chiron",  id = 15, type = "superior"  }
pholus  = { glyph = "⯛", name = "Pholus",  id = 16, type = "superior"  }
ceres   = { glyph = "⚳", name = "Ceres",   id = 17, type = "superior"  }
pallas  = { glyph = "⚴", name = "Pallas",  id = 18, type = "superior"  }
juno    = { glyph = "⚵", name = "Juno",    id = 19, type = "superior"  }
vesta      = { glyph = "⚶", name = "Vesta",      id = 20,           type = "superior" }
true_node  = { glyph = "☊", name = "True Node",  id = 11,           type = "node"     }
south_node = { glyph = "☋", name = "South Node", id = "south_node", type = "derived",  source = "true_node", lon_offset = 180 }
sirius     = { glyph = "✦", name = "Sirius",      id = "Sirius",     type = "star"     }
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