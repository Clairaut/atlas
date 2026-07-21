# Standard Modules
from typing import TYPE_CHECKING, Optional, List
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import traceback

# Internal Modules
from atlas.core.atlas import Atlas
from atlas.models.location import Location
from atlas.models.celestial import Celestial
from atlas.models.aspect import ASPECT_GLYPHS, build_aspects, build_transit_aspects
from atlas.models.event import Event
from atlas.utils.config import load_config
from atlas.utils.chrono import convert_to_utc, utc_to_local

if TYPE_CHECKING:
    from atlas.models.location import Location

# External Modules
import typer
from rich.table import Table
from rich.console import Console
from rich import box


# Load configuration
config: dict = load_config()

# Extract default location from config
lat: float = config.get("location", {}).get("lat", 0)
lon: float = config.get("location", {}).get("lon", 0)
alt: float = config.get("location", {}).get("alt", 0)

# Extract default output paths from config (empty string = no default)
default_image_path: Optional[str] = config.get("output", {}).get("image") or None
default_video_path: Optional[str] = config.get("output", {}).get("video") or None

# Pango font sizes for --pango output
glyph_size:  str = config.get("display", {}).get("glyph_size", "16pt")
detail_size: str = config.get("display", {}).get("detail_size", "11pt")

# Journal defaults
journal_dir: Path = Path(config.get("journal", {}).get("dir", "~/documents/journal")).expanduser()
journal_window_hours: int = config.get("journal", {}).get("window_hours", 24)

# Create default location object
default_location_str: str = f"({lat}, {lon}, {alt})"
default_location = Location(lat=lat, lon=lon, alt=alt)

# Default journal targets: every configured celestial that isn't a star
default_targets: list = [k for k, v in config.get("celestials", {}).items() if v.get("type") != "star"]

# Default chart targets: same, but keep the Sun — drop only other stars (e.g. Sirius)
default_chart_targets: list = [k for k, v in config.get("celestials", {}).items() if v.get("type") != "star" or k == "sun"]

cli_atlas = None
console = Console()

app = typer.Typer(
    name="atlas",
    help="a SwissEph interface designed for visualizing astrological/astronomical data.",
    epilog="created by clairaut",
    no_args_is_help=True,
)


# Print installed atlas version and exit
def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version, PackageNotFoundError
        try:
            print(f"atlas {version('atlas')}")
        except PackageNotFoundError:
            print("atlas (version unknown — not installed as a package)")
        raise typer.Exit()


@app.callback()
def _main(
    version: Optional[bool] = typer.Option(None, "--version", "-v", callback=_version_callback, is_eager=True, help="show atlas version and exit"),
) -> None:
    pass


# Resolve a save path: if it's a directory (no extension), append a timestamped filename
def _resolve_save_path(base: Optional[str], ext: str) -> Optional[str]:
    if not base:
        return None
    import os
    if not os.path.splitext(base)[1]:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return os.path.join(base, f"atlas_{stamp}{ext}")
    return base


# Resolve --save: not given -> no save; --save "" -> configured [output] default; --save <path> -> that path.
# Config output paths must never apply unless --save was actually given.
def _resolve_save(save: Optional[str], config_default: Optional[str], ext: str) -> Optional[str]:
    if save is None:
        return None
    if save == "":
        return _resolve_save_path(config_default, ext)
    return _resolve_save_path(save, ext)


# Initialize the CLI components
def _initialize_cli(verbose: bool = False) -> Atlas:
    ephe_path = config.get("ephemeris", {}).get("path", "")
    atlas     = Atlas(ephe_path=ephe_path, dt=convert_to_utc(datetime.now(), default_location), location=default_location, verbose=verbose)

    if verbose:
        logging.info("CLI components initialized")

    return atlas


#================#
 # ARG RESOLVING #
#================#

# Parse a datetime string — tries full datetime then date-only (midnight)
def _parse_datetime(s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognized datetime format: '{s}' — use YYYY-MM-DD or YYYY-MM-DD HH:MM[:SS]")


# Parse a step string into a timedelta — units match strftime: M=minutes
_STEP_UNITS: dict[str, timedelta] = {
    "w": timedelta(weeks=1),
    "d": timedelta(days=1),
    "h": timedelta(hours=1),
    "M": timedelta(minutes=1),
}

def _parse_step(s: str) -> timedelta:
    unit = s[-1]
    if unit not in _STEP_UNITS or not s[:-1].isdigit():
        raise ValueError(f"unrecognized step format: '{s}' — use e.g. 1d, 6h, 30M, 1w")
    return _STEP_UNITS[unit] * int(s[:-1])


# Parse a 'lat,lon,alt' location string, falling back to the configured default
def _parse_location(s: str) -> "Location":
    try:
        stripped = s.replace("(", "").replace(")", "")
        parts = [float(x) for x in stripped.split(",")]
        lat, lon, alt = (parts + [0.0])[:3] if len(parts) == 2 else parts[:3]
        return Location(lat, lon, alt)
    except ValueError:
        logging.error("invalid --location argument")
        return default_location


# Parse a single moment (--at), defaulting to now
def _resolve_moment(at: Optional[str]) -> datetime:
    if at:
        try:
            return _parse_datetime(at)
        except ValueError:
            logging.error("invalid --at argument")
    return datetime.now()


# Parse an optional range bound (--from/--to)
def _resolve_bound(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return _parse_datetime(s)
    except ValueError:
        logging.error("invalid datetime argument: '%s'", s)
        return None


# Parse --step, falling back to 1 day
def _resolve_step(step: str) -> timedelta:
    try:
        return _parse_step(step)
    except ValueError:
        logging.error("invalid --step argument")
        return timedelta(days=1)


#==================#
 # DISPLAY HELPERS #
#==================#

# Format RA degrees as hh:mm string
def _fmt_ra(ra_deg: float) -> str:
    h = ra_deg / 15.0
    hh = int(h)
    mm = int((h - hh) * 60)
    return f"{hh:02d}h {mm:02d}m"


# Display a single-moment list of celestial states
def _display_celestial_states(states: list["Celestial"], concise: bool = False, attributes: Optional[list[str]] = None, pango: bool = False, glyph_size_override: Optional[str] = None, detail_size_override: Optional[str] = None):
    attrs          = attributes or []
    # Detect which coordinate systems are populated
    # Zodiac (ecliptic) is on by default (no -a given) but, once -a is used to
    # narrow the view, only shows if explicitly requested via -a zodiac
    has_ecliptic   = any(s.lon is not None for s in states) and (not attrs or "zodiac" in attrs)
    has_equatorial = any(s.ra  is not None for s in states)
    has_horizontal = any(s.alt is not None for s in states)
    # Mag: always show for stars; show for planets only if -a mag requested
    has_mag        = any(s.app_mag is not None and (s.type == "star" or "mag" in attrs) for s in states)
    has_elongation = "elongation" in attrs and any(s.elong is not None for s in states)
    has_phase      = False

    rows = []
    for state in states:
        glyph_str = getattr(state, "glyph", "?")
        name_str  = getattr(state, "name",  "?")
        retrograde = "℞" if getattr(state, "retrograde", False) else ""

        # Ecliptic
        try:   sign_glyph, sign_name = state.sign
        except: sign_glyph, sign_name = "?", "?"
        try:   orb_str = f"{state.orb:.2f}°"
        except: orb_str = "?"

        # Equatorial
        ra_str  = _fmt_ra(state.ra)    if state.ra  is not None else "?"
        dec_str = f"{state.dec:+.2f}°" if state.dec is not None else "?"
        try:    constellation = state.constellation or ""
        except: constellation = ""

        # Horizontal
        alt_str = f"{state.alt:.2f}°" if state.alt is not None else "?"
        az_str  = f"{state.az:.2f}°"  if state.az  is not None else "?"

        # Magnitude
        mag_str = f"{state.app_mag:.2f}" if state.app_mag is not None else ""

        # Elongation
        elong_str = f"{state.elong:.2f}°" if state.elong is not None else ""
        try:
            elong_label_tuple = state.elong_label
            elong_label_str   = f"{elong_label_tuple[1]} {elong_label_tuple[0]}" if elong_label_tuple else None
        except Exception:
            elong_label_str = None
        elong_waxing = "wax." if getattr(state, "elong_waxing", None) is True else "wan."

        # Phase
        try:
            phase_tuple = state.phase
            phase_str   = f"{phase_tuple[1]} {phase_tuple[0]}" if phase_tuple else None
        except Exception:
            phase_tuple = None
            phase_str   = None
        phase_angle = getattr(state, "phase_angle", None)
        waxing      = "wax." if getattr(state, "phase_waxing", None) is True else "wan."
        if "phase" in attrs and phase_str is not None and phase_angle is not None:
            has_phase = True

        rows.append((glyph_str, name_str, retrograde,
                     sign_glyph, sign_name, orb_str,
                     ra_str, dec_str, constellation,
                     alt_str, az_str,
                     mag_str, elong_str, elong_label_str, elong_waxing,
                     phase_str, phase_angle, waxing,
                     getattr(state, "color", None)))

    if concise:
        for (g, name, retro, sg, sn, orb, ra, dec, con, alt, az, mag, elong, elong_label_str, elong_waxing, phase_str, phase_angle, waxing, color) in rows:
            parts = [f"{g}"]
            if has_ecliptic:   parts.append(f"{sg} {orb}")
            if has_equatorial: parts.append(f"{ra} {dec}")
            if has_horizontal: parts.append(f"alt {alt}  az {az}")
            if has_mag and mag: parts.append(f"m{mag}")
            if has_elongation and elong:
                eg = elong_label_str.split(" ", 1)[0] if elong_label_str else ""
                parts.append(f"{eg} {elong} {elong_waxing}".strip())
            if "phase" in attrs and phase_str and phase_angle is not None:
                pg = phase_str.split(" ", 1)[0]
                parts.append(f"{pg} {phase_angle:.2f}° {waxing}")
            if pango:
                color_attr = f' color="{color}"' if color else ""
                gsize = glyph_size_override or glyph_size
                dsize = detail_size_override or detail_size
                glyph_span  = f'<span font_size="{gsize}"{color_attr}>{parts[0]}</span>'
                detail_span = f'<span font_size="{dsize}"{color_attr}>{" ".join(parts[1:])}</span>' if len(parts) > 1 else ""
                print(f"{glyph_span} {detail_span}".rstrip())
            else:
                print("  ".join(parts))
    else:
        table = Table(show_header=True, title=None, box=box.SIMPLE, show_edge=False, pad_edge=False)
        table.add_column(" ",    no_wrap=True, min_width=2)
        table.add_column("Name", no_wrap=True)
        if has_ecliptic:
            table.add_column(" ",    no_wrap=True, min_width=2)
            table.add_column("Sign", no_wrap=True)
            table.add_column("Orb",  no_wrap=True, justify="right")
            table.add_column("℞",   no_wrap=True, min_width=1)
        if has_equatorial:
            table.add_column("RA",            no_wrap=True, justify="right")
            table.add_column("Dec",           no_wrap=True, justify="right")
            table.add_column("Constellation", no_wrap=True)
        if has_horizontal:
            table.add_column("Alt", no_wrap=True, justify="right")
            table.add_column("Az",  no_wrap=True, justify="right")
        if has_mag:
            table.add_column("Mag", no_wrap=True, justify="right")
        if has_elongation:
            table.add_column(" ",              no_wrap=True, min_width=2)
            table.add_column("Elongation",      no_wrap=True, justify="right")
            table.add_column("Elong. Phase",    no_wrap=True)
            table.add_column("Elong. Waxing",   no_wrap=True)
        if has_phase:
            table.add_column(" ",           no_wrap=True, min_width=2)
            table.add_column("Phase",       no_wrap=True)
            table.add_column("Phase Angle", no_wrap=True, justify="right")
            table.add_column("Waxing",      no_wrap=True)

        for (g, name, retro, sg, sn, orb, ra, dec, con, alt, az, mag, elong, elong_label_str, elong_waxing, phase_str, phase_angle, waxing, color) in rows:
            cells: list[str] = [g, name]
            if has_ecliptic:
                cells += [sg, sn, orb, retro]
            if has_equatorial:
                cells += [ra, dec, con]
            if has_horizontal:
                cells += [alt, az]
            if has_mag:
                cells.append(mag)
            if has_elongation:
                eg = elong_label_str.split(" ", 1)[0] if elong_label_str else ""
                en = elong_label_str.split(" ", 1)[1] if elong_label_str and " " in elong_label_str else ""
                cells += [eg, elong, en, elong_waxing]
            if has_phase:
                pg = phase_str.split(" ", 1)[0] if phase_str else ""
                pn = phase_str.split(" ", 1)[1] if phase_str and " " in phase_str else ""
                cells += [pg, pn, f"{phase_angle:.2f}°" if phase_angle else "", waxing]
            table.add_row(*cells)

        Console().print(table)


# Display aspects between a list of states at a single moment
def _display_aspects(states: list["Celestial"]):
    global cli_atlas
    if cli_atlas is None:
        cli_atlas = _initialize_cli()
    aspects = build_aspects(states)
    if not aspects:
        print("No aspects found.")
        return
    table = Table(show_header=True, title=None, box=box.SIMPLE, show_edge=False, pad_edge=False)
    table.add_column(" ",      no_wrap=True, min_width=2)
    table.add_column("Aspect", no_wrap=True)
    table.add_column("Body 1", no_wrap=True)
    table.add_column("Body 2", no_wrap=True)
    table.add_column("Orb",    no_wrap=True, justify="right")
    for asp in aspects:
        glyph = ASPECT_GLYPHS.get(asp.name, "?")
        table.add_row(glyph, asp.name.capitalize(),
                      f"{asp.body_one.glyph} {asp.body_one.name}",
                      f"{asp.body_two.glyph} {asp.body_two.name}",
                      f"{asp.orb:.2f}°")
    Console().print(table)


# Display a time-series trace for multiple targets
def _display_trace(traces: list[list["Celestial"]], targets: list[str], concise: bool = False):
    # traces[i] = list of states (one per target) at timestep i
    if not traces:
        return
    if concise:
        for step_states in traces:
            dt_str = step_states[0].dt.strftime("%Y-%m-%d %H:%M") if step_states else ""
            parts  = []
            for state in step_states:
                try:
                    sg, _ = state.sign
                    parts.append(f"{state.glyph} {sg} {state.orb:.1f}°")
                except Exception:
                    parts.append(state.name)
            print(f"{dt_str}  " + "  ".join(parts))
    else:
        table = Table(show_header=True, title=None, box=box.SIMPLE, show_edge=False, pad_edge=False)
        table.add_column("Date/Time", no_wrap=True)
        for target in targets:
            table.add_column(target.capitalize(), no_wrap=True)
        for step_states in traces:
            dt_str = step_states[0].dt.strftime("%Y-%m-%d %H:%M") if step_states else ""
            cells  = [dt_str]
            for state in step_states:
                try:
                    sg, sn = state.sign
                    cells.append(f"{sg} {sn}  {state.orb:.1f}°")
                except Exception:
                    cells.append("?")
            table.add_row(*cells)
        Console().print(table)


# Display detected transit events
def _display_events(events: list[Event], concise: bool = False):
    if not events:
        print("No events found in range.")
        return
    if concise:
        for ev in events:
            bodies = f"{ev.body} / {ev.body_two}" if ev.body_two else ev.body
            print(f"{ev.glyph} {ev.detail}  {bodies}  {ev.at.strftime('%Y-%m-%d %H:%M')}")
    else:
        table = Table(show_header=True, title=None, box=box.SIMPLE, show_edge=False, pad_edge=False)
        table.add_column(" ",       no_wrap=True, min_width=2)
        table.add_column("Event",   no_wrap=True)
        table.add_column("Type",    no_wrap=True)
        table.add_column("Body",    no_wrap=True)
        table.add_column("Date",    no_wrap=True)
        table.add_column("Time",    no_wrap=True)
        for ev in events:
            bodies = f"{ev.body} / {ev.body_two}" if ev.body_two else ev.body
            table.add_row(ev.glyph, ev.detail.title(), ev.type.capitalize(),
                          bodies,
                          ev.at.strftime("%Y-%m-%d"),
                          ev.at.strftime("%H:%M"))
        Console().print(table)


# Format a body string with glyphs: "☽ Moon / ♀ Venus"
def _body_str(body: str, body_two: Optional[str], glyphs: dict) -> str:
    g1   = glyphs.get(body.lower(), "")
    part = f"{g1} {body}".strip()
    if body_two:
        g2   = glyphs.get(body_two.lower(), "")
        part += f" / {g2} {body_two}".rstrip()
    return part


# Format a timedelta as a relative time string; shows hours when within a day
def _until_str(delta: timedelta) -> str:
    s = delta.total_seconds()
    if s >= 0:
        if s < 3600:    return f"in {int(s // 60)}m"
        if s < 86400:   return f"in {int(s // 3600)}h"
        days = delta.days
        return f"in {days} day" if days == 1 else f"in {days} days"
    s = abs(s)
    if s < 3600:    return f"{int(s // 60)}m ago"
    if s < 86400:   return f"{int(s // 3600)}h ago"
    days = abs(delta.days)
    return f"{days} day ago" if days == 1 else f"{days} days ago"


# Display seek results: {glyph} {body glyphs+names} {detail} {date} {time} {until}
def _display_seek_results(events: list[Event], location: "Location", concise: bool = False):
    if not events:
        print("No events found.")
        return
    now    = datetime.now(timezone.utc).replace(tzinfo=None)
    glyphs = {k: v.get("glyph", "") for k, v in config.get("celestials", {}).items()}

    if concise:
        for ev in events:
            body    = _body_str(ev.body, ev.body_two, glyphs)
            delta   = ev.at - now
            local   = utc_to_local(ev.at, location)
            event   = f"{ev.glyph} {ev.detail}"
            print(f"{body}  {event}  {local.strftime('%Y-%m-%d %H:%M')}  ({_until_str(delta)})")
    else:
        table = Table(show_header=True, title=None, box=box.SIMPLE, show_edge=False, pad_edge=False)
        table.add_column("Body",  no_wrap=True)
        table.add_column("Event", no_wrap=True)
        table.add_column("Date",  no_wrap=True)
        table.add_column("Time",  no_wrap=True)
        table.add_column("Until", no_wrap=True, justify="right")
        for ev in events:
            body  = _body_str(ev.body, ev.body_two, glyphs)
            delta = ev.at - now
            local = utc_to_local(ev.at, location)
            event = f"{ev.glyph} {ev.detail.title()}"
            table.add_row(body, event,
                          local.strftime("%Y-%m-%d"), local.strftime("%H:%M"), _until_str(delta))
        Console().print(table)


#============#
 # COMMANDS  #
#============#

@app.command()
def observe(
    targets: List[str] = typer.Argument(..., help="celestial bodies to observe"),
    at: Optional[str] = typer.Option(None, "--at", help="observation datetime 'YYYY-MM-DD [HH:MM[:SS]]'"),
    from_dt: Optional[str] = typer.Option(None, "--from", help="range start datetime 'YYYY-MM-DD [HH:MM[:SS]]'"),
    to_dt: Optional[str] = typer.Option(None, "--to", help="range end datetime 'YYYY-MM-DD [HH:MM[:SS]]' (default: now)"),
    step: str = typer.Option("1d", "--step", help="time step for range queries e.g. 1d, 6h, 30m"),
    location: str = typer.Option(default_location_str, "-l", "--location", help="location '(lat,lon,alt)'"),
    zodiac: str = typer.Option("tropical", "-z", "--zodiac", help="zodiac type", case_sensitive=False),
    attributes: Optional[List[str]] = typer.Option(None, "-a", "--attributes", help="extra attributes: phase, aspects, transits, elongation, mag, zodiac"),
    system: List[str] = typer.Option(["ecliptic"], "-s", "--system", help="coordinate systems: ecliptic, equatorial, horizontal"),
    concise: bool = typer.Option(False, "-c", "--concise", help="compact output"),
    pango: bool = typer.Option(False, "-p", "--pango", help="wrap concise output in Pango markup, colored per [celestials].color"),
    glyph_size_opt: Optional[str] = typer.Option(None, "--glyph-size", help="override [display].glyph_size for this call e.g. 20pt"),
    detail_size_opt: Optional[str] = typer.Option(None, "--detail-size", help="override [display].detail_size for this call e.g. 14pt"),
):
    """observe celestial bodies at a moment or over a time range"""
    global cli_atlas
    if cli_atlas is None:
        cli_atlas = _initialize_cli(verbose=False)

    loc         = _parse_location(location)
    moment      = convert_to_utc(_resolve_moment(at), loc)
    range_from  = _resolve_bound(from_dt)
    range_to    = _resolve_bound(to_dt) or datetime.now()
    if range_from:
        range_from = convert_to_utc(range_from, loc)
    range_to = convert_to_utc(range_to, loc)
    step_td     = _resolve_step(step)
    attrs       = attributes or []

    try:
        if range_from:
            # Time-series trace mode — one trace per target, zipped by timestep
            traces_by_target = [
                cli_atlas.track(
                    target   = target,
                    start_dt = range_from,
                    end_dt   = range_to,
                    step     = step_td,
                    location = loc,
                    zodiac   = zodiac,
                    systems  = system,
                )
                for target in targets
            ]
            # Zip into list-of-lists: traces[step_i] = [state_target_0, state_target_1, ...]
            traces = [list(step) for step in zip(*traces_by_target)]
            _display_trace(traces, targets, concise=concise)

        else:
            # Single-moment observation
            properties: list[str] = ["position"]
            if "phase" in attrs or "mag" in attrs or "elongation" in attrs:
                properties.append("phenomenon")
            if "mag" in attrs:
                properties.append("magnitude")

            states: list[Celestial] = []
            for target in targets:
                state = cli_atlas.locate(
                    dt         = moment,
                    location   = loc,
                    target     = target,
                    zodiac     = zodiac,
                    properties = properties,
                    systems    = system,
                )
                states.append(state)

            _display_celestial_states(states, concise=concise, attributes=attrs, pango=pango, glyph_size_override=glyph_size_opt, detail_size_override=detail_size_opt)

            if "aspects" in attrs:
                print()
                _display_aspects(states)

    except ValueError as e:
        print(f"Error: {e}")
    except Exception:
        logging.error("failed to handle observation command")
        traceback.print_exc()


@app.command()
def chart(
    targets: List[str] = typer.Argument(default_chart_targets, help="celestial bodies to include"),
    at: Optional[str] = typer.Option(None, "--at", help="chart datetime 'YYYY-MM-DD [HH:MM[:SS]]'"),
    transit: Optional[str] = typer.Option(None, "--transit", help="transit datetime — triggers dual-ring transit chart"),
    from_dt: Optional[str] = typer.Option(None, "--from", help="playback start datetime"),
    to_dt: Optional[str] = typer.Option(None, "--to", help="playback end datetime (default: now)"),
    step: str = typer.Option("1d", "--step", help="playback time step e.g. 1d, 1h"),
    speed: float = typer.Option(1.0, "--speed", help="playback steps per second (default 1.0)"),
    save: Optional[str] = typer.Option(None, "--save", help="save path — .png for static charts, .mp4 for playback; pass an empty string ('') to use the configured output-path default"),
    location: str = typer.Option(default_location_str, "-l", "--location", help="location '(lat,lon,alt)'"),
    zodiac: str = typer.Option("tropical", "-z", "--zodiac", help="zodiac type"),
    title: Optional[str] = typer.Option(None, "-T", "--title", help="chart title"),
):
    """render a radix, transit, or playback chart"""
    loc        = _parse_location(location)
    moment     = convert_to_utc(_resolve_moment(at), loc)
    transit_dt = _resolve_bound(transit)
    range_from = _resolve_bound(from_dt)
    range_to   = _resolve_bound(to_dt)

    if targets == ["live"]:
        _handle_live(loc, zodiac)
    elif transit_dt:
        _handle_transit_chart(targets, moment, convert_to_utc(transit_dt, loc), loc, zodiac, save, title)
    elif range_from and range_to:
        _handle_playback(targets, convert_to_utc(range_from, loc), convert_to_utc(range_to, loc), _resolve_step(step), speed, loc, zodiac, save)
    else:
        _handle_chart(targets, moment, loc, zodiac, save, title)


def _handle_chart(targets, moment, loc, zodiac, save, title):
    from atlas.view.chart import RadixChart

    global cli_atlas
    if cli_atlas is None:
        cli_atlas = _initialize_cli(verbose=False)

    try:
        celestials = []
        for target in targets:
            state = cli_atlas.locate(
                dt         = moment,
                location   = loc,
                target     = target,
                zodiac     = zodiac,
                properties = ["position"],
                systems    = ["ecliptic"],
            )
            celestials.append(state)

        cusps    = cli_atlas.erect(dt=moment, location=loc, zodiac=zodiac)
        aspects  = build_aspects(celestials)
        chart_title = title or moment.strftime("%Y-%m-%d  %H:%M")
        RadixChart.configure(cusps=cusps, celestials=celestials, aspects=aspects, title=chart_title, save_path=_resolve_save(save, default_image_path, ".png"))
        RadixChart.show()

    except ValueError as e:
        print(f"Error: {e}")
    except Exception:
        logging.error("failed to handle chart command")
        traceback.print_exc()


def _handle_transit_chart(targets, natal_dt, transit_dt, loc, zodiac, save, title):
    from atlas.view.chart import TransitChart

    global cli_atlas
    if cli_atlas is None:
        cli_atlas = _initialize_cli(verbose=False)

    try:
        natal_celestials   = []
        transit_celestials = []
        for target in targets:
            natal_celestials.append(cli_atlas.locate(
                dt=natal_dt, location=loc, target=target,
                zodiac=zodiac, properties=["position"], systems=["ecliptic"],
            ))
            transit_celestials.append(cli_atlas.locate(
                dt=transit_dt, location=loc, target=target,
                zodiac=zodiac, properties=["position"], systems=["ecliptic"],
            ))

        natal_cusps      = cli_atlas.erect(dt=natal_dt,   location=loc, zodiac=zodiac)
        transit_cusps    = cli_atlas.erect(dt=transit_dt, location=loc, zodiac=zodiac)
        transit_aspects  = build_transit_aspects(natal_celestials, transit_celestials)
        chart_title = title or f"{natal_dt.strftime('%Y-%m-%d')} → {transit_dt.strftime('%Y-%m-%d')}"

        TransitChart.configure_transit(
            cusps=natal_cusps, celestials=natal_celestials,
            transit_cusps=transit_cusps, transit_celestials=transit_celestials,
            transit_aspects=transit_aspects,
            title=chart_title, save_path=_resolve_save(save, default_image_path, ".png"),
        )
        TransitChart.show()

    except ValueError as e:
        print(f"Error: {e}")
    except Exception:
        logging.error("failed to handle transit chart command")
        traceback.print_exc()


def _handle_playback(targets, start_dt, end_dt, step_td, speed, loc, zodiac, save):
    from atlas.view.chart import PlaybackChart

    global cli_atlas
    if cli_atlas is None:
        cli_atlas = _initialize_cli(verbose=False)

    try:
        PlaybackChart.configure_playback(
            atlas = cli_atlas,
            location   = loc,
            zodiac     = zodiac,
            targets    = targets,
            start_dt   = start_dt,
            end_dt     = end_dt,
            step       = step_td,
            speed      = speed,
            save_path  = _resolve_save(save, default_video_path, ".mp4"),
        )
        PlaybackChart.show()
    except Exception:
        logging.error("failed to handle playback command")
        traceback.print_exc()


def _handle_live(loc, zodiac):
    from atlas.view.chart import LiveRadixChart

    global cli_atlas
    if cli_atlas is None:
        cli_atlas = _initialize_cli(verbose=False)

    targets = list(default_chart_targets)

    try:
        LiveRadixChart.configure_live(
            atlas = cli_atlas,
            location = loc,
            zodiac   = zodiac,
            targets  = targets,
        )
        LiveRadixChart.show()
    except Exception:
        logging.error("failed to handle live command")
        traceback.print_exc()


SEEK_DESCRIPTION = (
    "Finds celestial events by type.\n\n"
    "  no --from/--to  — next N occurrences from --at or now (see --limit)\n"
    "  with --from/--to — all matching event entrances in that range\n\n"
    "  For currently active aspects use: atlas observe -a aspects\n\n"
    "--detail keywords by type:\n"
    "  phase      new, waxing crescent, first quarter, waxing gibbous,\n"
    "             full, waning gibbous, last quarter, waning crescent\n"
    "  ingress    aries, taurus, gemini, cancer, leo, virgo,\n"
    "             libra, scorpio, sagittarius, capricorn, aquarius, pisces\n"
    "  station    retrograde, direct\n"
    "  aspect     conjunction, sextile, square, trine, opposition\n"
    "  elongation conjunction, eastern quadrature, opposition, western quadrature\n"
    "  diurnal    rising, setting, culmination, anti-culmination\n\n"
    "  --detail matches are case-insensitive substrings (e.g. 'full' matches 'Full Moon')"
)

SEEK_EPILOG = (
    "examples:\n\n"
    "  atlas seek aspect                                       next aspect entrance\n\n"
    "  atlas seek aspect --detail trine                        next trine entrance\n\n"
    "  atlas seek aspect --limit 3                             next 3 aspect entrances\n\n"
    "  atlas seek phase moon --detail full                     next full moon\n\n"
    "  atlas seek phase moon --detail full --limit 6           next 6 full moons\n\n"
    "  atlas seek ingress moon --detail scorpio                next moon into Scorpio\n\n"
    "  atlas seek station mercury -c                           next mercury station, compact\n\n"
    "  atlas seek elongation venus --detail eastern            next venus eastern quadrature\n\n"
    "  atlas seek aspect --from 2026-01-01 --to 2026-06-01    all aspects in range\n\n"
    "  atlas seek diurnal moon                                 next moonrise/set/culmination\n\n"
    "  atlas seek diurnal sun --detail setting                 next sunset\n\n"
    "  atlas seek diurnal moon --detail rising                 next moonrise"
)

_SEEK_TYPES = ["phase", "ingress", "station", "aspect", "elongation", "diurnal"]


@app.command(help=SEEK_DESCRIPTION, epilog=SEEK_EPILOG)
def seek(
    type: Optional[str] = typer.Argument(None, help=f"event type: {', '.join(_SEEK_TYPES)}"),
    targets: Optional[List[str]] = typer.Argument(None, help="celestial bodies to scan"),
    detail: Optional[List[str]] = typer.Option(None, "--detail", help="filter by detail (case-insensitive substring match)"),
    at: Optional[str] = typer.Option(None, "--at", help="moment or search start 'YYYY-MM-DD [HH:MM[:SS]]'"),
    from_dt: Optional[str] = typer.Option(None, "--from", help="range start — with --to, returns event entrances in range"),
    to_dt: Optional[str] = typer.Option(None, "--to", help="range end   — with --from, returns event entrances in range"),
    limit: int = typer.Option(1, "--limit", help="max results in next-occurrence mode (default 1)"),
    location: str = typer.Option(default_location_str, "-l", "--location", help="location '(lat,lon,alt)'"),
    zodiac: str = typer.Option("tropical", "-z", "--zodiac", help="zodiac type"),
    concise: bool = typer.Option(False, "-c", "--concise", help="compact output"),
):
    if type is not None and type not in _SEEK_TYPES:
        print(f"Error: invalid type '{type}' — choose from {', '.join(_SEEK_TYPES)}")
        raise typer.Exit(code=1)

    global cli_atlas
    if cli_atlas is None:
        cli_atlas = _initialize_cli(verbose=False)

    loc         = _parse_location(location)
    moment      = convert_to_utc(_resolve_moment(at), loc)
    range_from  = _resolve_bound(from_dt)
    range_to    = _resolve_bound(to_dt)
    has_range   = range_from and range_to

    scan_targets = targets or list(config.get("celestials", {}).keys())
    event_types  = [type] if type else _SEEK_TYPES

    try:
        event_details = detail or None

        if has_range:
            events = cli_atlas.transit(
                targets         = scan_targets,
                start_dt        = convert_to_utc(range_from, loc),
                end_dt          = convert_to_utc(range_to, loc),
                location        = loc,
                zodiac          = zodiac,
                event_types     = event_types,
                event_details   = event_details,
            )
        else:
            events = cli_atlas.transit(
                targets         = scan_targets,
                start_dt        = moment,
                end_dt          = moment + timedelta(days=365),
                location        = loc,
                event_details   = event_details,
                zodiac          = zodiac,
                event_types     = event_types,
                limit           = limit,
            )

        _display_seek_results(events, location=loc, concise=concise)

    except Exception:
        logging.error("failed to handle seek command")
        traceback.print_exc()


@app.command()
def dome(
    targets: Optional[List[str]] = typer.Argument(None, help="planet targets to overlay (default: all configured)"),
    at: Optional[str] = typer.Option(None, "--at", help="observation datetime 'YYYY-MM-DD [HH:MM[:SS]]'"),
    mag: float = typer.Option(6.5, "--mag", help="magnitude cutoff for star display (default 6.5)"),
    brightness: float = typer.Option(1.0, "--brightness", help="star brightness multiplier 0.0–2.0 (default 1.0)"),
    save: Optional[str] = typer.Option(None, "--save", help="save initial frame as PNG; pass an empty string ('') to use the configured output-path default"),
    location: str = typer.Option(default_location_str, "-l", "--location", help="location '(lat,lon,alt)'"),
    zodiac: str = typer.Option("tropical", "-z", "--zodiac", help="zodiac type"),
    title: Optional[str] = typer.Option(None, "-T", "--title", help="window title"),
):
    """render an interactive full-sky dome (azimuthal equidistant projection)"""
    from atlas.view.experimental.dome import DomeView

    global cli_atlas
    if cli_atlas is None:
        cli_atlas = _initialize_cli(verbose=False)

    loc     = _parse_location(location)
    moment  = convert_to_utc(_resolve_moment(at), loc)
    scan_targets = targets or list(config.get("celestials", {}).keys())

    try:
        # Fetch planets with both ecliptic and horizontal systems for the panel
        planets: list[Celestial] = []
        for target in scan_targets:
            try:
                state = cli_atlas.locate(
                    dt         = moment,
                    location   = loc,
                    target     = target,
                    zodiac     = zodiac,
                    properties = ["position", "phenomenon"],
                    systems    = ["horizontal", "ecliptic"],
                )
                planets.append(state)
            except ValueError:
                pass

        # Closure: called by dome on click to fetch a full state for a named body
        atlas = cli_atlas

        def fetch_fn(name: str) -> "Celestial":
            return atlas.locate(
                dt         = moment,
                location   = loc,
                target     = name,
                zodiac     = zodiac,
                properties = ["position", "phenomenon", "magnitude"],
                systems    = ["ecliptic", "equatorial", "horizontal"],
            )

        dome_title = title or moment.strftime("%Y-%m-%d  %H:%M")
        save_path  = _resolve_save(save, default_image_path, ".png")

        DomeView.configure(
            dt         = moment,
            location   = loc,
            planets    = planets,
            fetch_fn   = fetch_fn,
            mag_limit  = mag,
            brightness = brightness,
            save_path  = save_path,
            title      = dome_title,
        )
        DomeView.show()

    except ValueError as e:
        print(f"Error: {e}")
    except Exception:
        logging.error("failed to handle dome command")
        traceback.print_exc()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="bind host (default 127.0.0.1)"),
    port: int = typer.Option(5001, "--port", help="bind port (default 5001)"),
):
    """start the Atlas REST API server"""
    try:
        from atlas.serve import run
        run(host=host, port=port)
    except ImportError:
        print("FastAPI/Uvicorn is not installed. Run: pip install fastapi uvicorn")
    except Exception:
        logging.error("failed to start server")
        traceback.print_exc()


@app.command()
def view(
    at: Optional[str] = typer.Option(None, "--at", help="datetime to view 'YYYY-MM-DD [HH:MM[:SS]]'"),
    live: bool = typer.Option(False, "--live", help="real-time mode (default when --at is omitted)"),
    location: str = typer.Option(default_location_str, "-l", "--location", help="location '(lat,lon,alt)'"),
    zodiac: str = typer.Option("tropical", "-z", "--zodiac", help="zodiac type"),
):
    """open the Atlas sky viewer (requires atlas-viewer)"""
    print("atlas view is not yet implemented.")


@app.command()
def journal(
    mode: str = typer.Option("snapshot", "--mode", help="snapshot|digest|both"),
    format: str = typer.Option("md", "--format", help="md|json"),
):
    """append a sky snapshot and/or upcoming-events digest to today's journal entry"""
    if mode not in ("snapshot", "digest", "both"):
        print(f"Error: invalid --mode '{mode}' — choose from snapshot, digest, both")
        raise typer.Exit(code=1)
    if format not in ("md", "json"):
        print(f"Error: invalid --format '{format}' — choose from md, json")
        raise typer.Exit(code=1)

    try:
        from journalkit import JournalEntry, export_section
    except ImportError:
        print("Error: journalkit is not installed. Run: pip install atlas[journal]")
        raise typer.Exit(code=1)

    global cli_atlas
    if cli_atlas is None:
        cli_atlas = _initialize_cli(verbose=False)

    now = datetime.now()
    moment = convert_to_utc(now, default_location)
    glyphs = {k: v.get("glyph", "") for k, v in config.get("celestials", {}).items()}

    if mode in ("snapshot", "both"):
        entries = []
        for target in default_targets:
            try:
                state = cli_atlas.locate(
                    dt         = moment,
                    location   = default_location,
                    target     = target,
                    zodiac     = "tropical",
                    properties = ["position"],
                    systems    = ["ecliptic"],
                )
                sign_glyph, sign_name = state.sign
                retrograde = bool(getattr(state, "retrograde", False))
                retro = " ℞" if retrograde else ""
                entries.append(JournalEntry(
                    text = f"{state.glyph} {state.name} — {sign_glyph} {sign_name} {state.orb:.2f}°{retro}",
                    data = {
                        "body": state.name, "glyph": state.glyph,
                        "sign": sign_name, "orb": round(state.orb, 2),
                        "retrograde": retrograde,
                    },
                ))
            except Exception:
                continue
        path = export_section(journal_dir, "Sky", entries, fmt=format)
        console.print(f"Appended to [bold]{path}[/bold]")

    if mode in ("digest", "both"):
        events = cli_atlas.transit(
            targets     = default_targets,
            start_dt    = moment,
            end_dt      = moment + timedelta(hours=journal_window_hours),
            location    = default_location,
            zodiac      = "tropical",
        )
        if events:
            entries = [
                JournalEntry(
                    text = f"{ev.glyph} {ev.detail}  {_body_str(ev.body, ev.body_two, glyphs)}  {utc_to_local(ev.at, default_location).strftime('%Y-%m-%d %H:%M')}",
                    data = {
                        "type": ev.type, "detail": ev.detail, "body": ev.body,
                        "body_two": ev.body_two, "at": utc_to_local(ev.at, default_location).isoformat(),
                    },
                )
                for ev in events
            ]
        else:
            message = f"no events in the next {journal_window_hours}h"
            entries = [JournalEntry(text=message, data={"empty": True, "message": message})]
        path = export_section(journal_dir, "Sky Events", entries, fmt=format)
        console.print(f"Appended to [bold]{path}[/bold]")


def main():
    app()


if __name__ == "__main__":
    main()
