# Standard libraries
from datetime import datetime

# Internal libraries
from atlas_dev.src.models.location import Location

# External libraries
from timezonefinder import TimezoneFinder
import pytz


# Converts a naive local datetime to naive UTC using coordinates to determine timezone
def convert_to_utc(t: datetime, location: Location) -> datetime:
    tz_str = TimezoneFinder().timezone_at(lat=location.lat, lng=location.lon)
    local_tz = pytz.timezone(tz_str)
    t_local = local_tz.localize(t, is_dst=None)
    t_utc = t_local.astimezone(pytz.utc)
    return t_utc.replace(tzinfo=None)
