# Standard libraries
from datetime import datetime

# External libraries
from timezonefinder import TimezoneFinder
import pytz

Location = tuple[float, float, float]


# Converts a naive local datetime to naive UTC using coordinates to determine timezone
def convert_to_utc(t: datetime, location: Location) -> datetime:
    lat, lon, _ = location
    tz_str   = TimezoneFinder().timezone_at(lat=lat, lng=lon)
    local_tz = pytz.timezone(tz_str)
    t_local  = local_tz.localize(t, is_dst=None)
    t_utc    = t_local.astimezone(pytz.utc)
    return t_utc.replace(tzinfo=None)


# Converts a naive UTC datetime to naive local time using coordinates to determine timezone
def utc_to_local(t: datetime, location: Location) -> datetime:
    lat, lon, _ = location
    tz_str   = TimezoneFinder().timezone_at(lat=lat, lng=lon)
    local_tz = pytz.timezone(tz_str)
    t_utc    = pytz.utc.localize(t)
    return t_utc.astimezone(local_tz).replace(tzinfo=None)
