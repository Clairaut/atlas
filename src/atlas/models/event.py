# Standard Modules
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    type:     str                     # "aspect" | "ingress" | "station" | "phase"
    at:       datetime                # exact moment (refined via bisection)
    body:     str                     # primary body name
    detail:   str                     # e.g. "conjunction", "Aries", "retrograde", "full moon"
    glyph:    str                     # display glyph for the event
    body_two: Optional[str] = None    # second body name (aspects only)
    orb:      Optional[float] = None  # orb at exact moment (aspects only, ~0)
    start:    Optional[datetime] = None  # when condition begins (orb entry, phase boundary, etc.)
    end:      Optional[datetime] = None  # when condition ends
