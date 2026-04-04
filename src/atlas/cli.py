# Standard Modules
from typing import TYPE_CHECKING, Optional
from datetime import datetime, timedelta, timezone
import argparse
import traceback

# Internal Modules
from atlas.core.wizard import Wizard
from atlas.core.observatory import Observatory
from atlas.clients.ephe_client import EphemerisClient
from atlas.models.location import Location
from atlas.models.celestial_state import CelestialState
from atlas.models.aspect import Aspect, ASPECT_GLYPHS
from atlas.models.event import Event
from atlas.utils.logger import handle_log
from atlas.utils.config import load_config
from atlas.utils.chrono import convert_to_utc, utc_to_local

if TYPE_CHECKING:
    from atlas.models.location import Location

# External Modules
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


# Resolve a save path: if it's a directory (no extension), append a timestamped filename
def _resolve_save_path(base: Optional[str], ext: str) -> Optional[str]:
    if not base:
        return None
    import os
    if not os.path.splitext(base)[1]:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return os.path.join(base, f"atlas_{stamp}{ext}")
    return base

# Create default location object
default_location_str: str = f"({lat}, {lon}, {alt})"
default_location = Location(lat=lat, lon=lon, alt=alt)


cli_wizard = None

# Initialize the CLI components
def _initialize_cli(verbose: bool = False) -> Wizard:
    # Setup Ephemeris Client, Observatory, and Wizard
    ephe_path = config.get("ephemeris", {}).get("path", "")
    ephe_client = EphemerisClient(ephe_path=ephe_path, verbose=verbose)
    observatory = Observatory(ephe_client=ephe_client, dt=convert_to_utc(datetime.now(), default_location), location=default_location, verbose=verbose)
    wizard = Wizard(observatory=observatory, verbose=verbose)

    if verbose:
        handle_log("info", "CLI components initialized", source="cli")

    return wizard


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


#==========================#
 # MAIN PARSER CONSTRUCTION #
#==========================#

# Construct parser
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas",
        description="a SwissEph interface designed for visualizing astrological/astronomical data.",
        epilog="created by clairaut"
    )

    subparsers = parser.add_subparsers(required=True, dest="command")

    # observe subparser
    observe_parser = subparsers.add_parser(
        name  = "observe",
        help  = "observe celestial bodies at a moment or over a time range",
        usage = "atlas observe {celestial_bodies}* [options]"
    )
    observe_parser.add_argument("targets",        help="celestial bodies to observe",                              nargs="+")
    observe_parser.add_argument("--at",           help="observation datetime 'YYYY-MM-DD [HH:MM[:SS]]'",          nargs="?", default=None)
    observe_parser.add_argument("--from",         help="range start datetime 'YYYY-MM-DD [HH:MM[:SS]]'",          nargs="?", default=None, dest="from_dt")
    observe_parser.add_argument("--to",           help="range end datetime 'YYYY-MM-DD [HH:MM[:SS]]'",            nargs="?", default=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dest="to_dt")
    observe_parser.add_argument("--step",         help="time step for range queries e.g. 1d, 6h, 30m",            nargs="?", default="1d")
    observe_parser.add_argument("-l", "--location",  help="location '(lat,lon,alt)'",                             nargs="?", default=default_location_str)
    observe_parser.add_argument("-z", "--zodiac",    help="zodiac type",                                           choices=["tropical", "sidereal"], default="tropical")
    observe_parser.add_argument("-a", "--attributes",help="extra attributes: phase, aspects, transits, elongation", choices=["phase", "aspects", "transits", "elongation"], nargs="*", default=None)
    observe_parser.add_argument("-f", "--frames",    help="coordinate frames",                                     nargs="*", default=["ecliptic"])
    observe_parser.add_argument("-c", "--concise",   help="compact output",                                        action="store_true")

    # chart subparser
    chart_parser = subparsers.add_parser(
        name  = "chart",
        help  = "render a radix, transit, or playback chart",
        usage = "atlas chart [targets]* [options]"
    )
    default_targets = list(config.get("celestials", {}).keys())
    chart_parser.add_argument("targets",          help="celestial bodies to include",                              nargs="*", default=default_targets)
    chart_parser.add_argument("--at",             help="chart datetime 'YYYY-MM-DD [HH:MM[:SS]]'",                nargs="?", default=None)
    chart_parser.add_argument("--transit",        help="transit datetime — triggers dual-ring transit chart",      nargs="?", default=None)
    chart_parser.add_argument("--from",           help="playback start datetime",                                  nargs="?", default=None, dest="from_dt")
    chart_parser.add_argument("--to",             help="playback end datetime",                                    nargs="?", default=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dest="to_dt")
    chart_parser.add_argument("--step",           help="playback time step e.g. 1d, 1h",                          nargs="?", default="1d")
    chart_parser.add_argument("--speed",          help="playback steps per second (default 1.0)",                  type=float, default=1.0)
    chart_parser.add_argument("--save",           help="save path — .png for static charts, .mp4 for playback",   nargs="?", const="", default=None)
    chart_parser.add_argument("-l", "--location", help="location '(lat,lon,alt)'",                                nargs="?", default=default_location_str)
    chart_parser.add_argument("-z", "--zodiac",   help="zodiac type",                                              choices=["tropical", "sidereal"], default="tropical")
    chart_parser.add_argument("-T", "--title",    help="chart title",                                              nargs="?", default=None)

    # seek subparser
    seek_parser = subparsers.add_parser(
        name            = "seek",
        help            = "find celestial events by type",
        description     = (
            "Finds celestial events by type.\n\n"
            "  aspect (no --from/--to)  — snapshot of aspects active at --at or now\n"
            "  other  (no --from/--to)  — next N occurrences from --at or now (see --limit)\n"
            "  any    (with --from/--to) — all matching event entrances in that range\n\n"
            "  --limit N with aspect and no range triggers entry mode (next N aspect formations)."
        ),
        usage           = "atlas seek {type} [targets]* [options]",
        epilog          = (
            "examples:\n"
            "  atlas seek aspect                              active aspects right now\n"
            "  atlas seek aspect sun moon --at 1999-09-29    active aspects on a date\n"
            "  atlas seek aspect --detail trine              active trines right now\n"
            "  atlas seek aspect --limit 3                   next 3 aspect entrances\n"
            "  atlas seek phase moon --detail full           next full moon\n"
            "  atlas seek phase moon --detail full --limit 6 next 6 full moons\n"
            "  atlas seek ingress moon --detail scorpio      next moon into Scorpio\n"
            "  atlas seek station mercury -c                 next mercury station, compact\n"
            "  atlas seek aspect --from 2026-01-01 --to 2026-06-01  aspect entrances in range\n"
            "  atlas seek diurnal moon                        next moonrise/set/culmination\n"
            "  atlas seek diurnal sun --detail setting        next sunset\n"
            "  atlas seek diurnal moon --detail rising        next moonrise"
        ),
        formatter_class = argparse.RawDescriptionHelpFormatter,
    )
    seek_parser.add_argument("type",      help="event type: phase, ingress, station, aspect, elongation, diurnal", choices=["phase", "ingress", "station", "aspect", "elongation", "diurnal"])
    seek_parser.add_argument("targets",   help="celestial bodies to scan",                                   nargs="*", default=[])
    seek_parser.add_argument("--detail",  help="filter by detail e.g. full, scorpio, trine, retrograde",    nargs="?", default=None)
    seek_parser.add_argument("--at",      help="moment or search start 'YYYY-MM-DD [HH:MM[:SS]]'",          nargs="?", default=None)
    seek_parser.add_argument("--from",    help="range start — with --to, returns event entrances in range",  nargs="?", default=None, dest="from_dt")
    seek_parser.add_argument("--to",      help="range end   — with --from, returns event entrances in range",nargs="?", default=None, dest="to_dt")
    seek_parser.add_argument("--limit",   help="max results in next-occurrence mode (default 1)",            type=int,  default=1)
    seek_parser.add_argument("-l", "--location", help="location '(lat,lon,alt)'",                           nargs="?", default=default_location_str)
    seek_parser.add_argument("-z", "--zodiac",   help="zodiac type",                                         choices=["tropical", "sidereal"], default="tropical")
    seek_parser.add_argument("-c", "--concise",  help="compact output",                                      action="store_true")

    return parser


#====================#
 # ARGUMENT PARSERS #
#====================#

# Parse all arguments
def _parse_arguments(parser: argparse.ArgumentParser):
    args = parser.parse_args()

    # Parse --at (single moment)
    if hasattr(args, "at") and args.at:
        try:
            args.at = _parse_datetime(args.at)
        except ValueError:
            handle_log("error", "invalid --at argument", source="cli")
            args.at = datetime.now()
    elif hasattr(args, "at"):
        args.at = datetime.now()

    # Parse --from / --to
    for attr in ("from_dt", "to_dt"):
        if hasattr(args, attr) and getattr(args, attr):
            try:
                setattr(args, attr, _parse_datetime(getattr(args, attr)))
            except ValueError:
                handle_log("error", "invalid --%s argument", attr.replace("_", ""), source="cli")
                setattr(args, attr, None)

    # Parse --step
    if hasattr(args, "step") and args.step:
        try:
            args.step = _parse_step(args.step)
        except ValueError:
            handle_log("error", "invalid --step argument", source="cli")
            args.step = timedelta(days=1)

    # Parse --transit datetime (chart command)
    if hasattr(args, "transit") and args.transit:
        try:
            args.transit = _parse_datetime(args.transit)
        except ValueError:
            handle_log("error", "invalid --transit argument", source="cli")
            args.transit = None

    # Parse --location
    if hasattr(args, "location"):
        try:
            stripped = args.location.replace("(", "").replace(")", "")
            parts = [float(x) for x in stripped.split(",")]
            lat, lon, alt = (parts + [0.0])[:3] if len(parts) == 2 else parts[:3]
            args.location = Location(lat, lon, alt)
        except ValueError:
            handle_log("error", "invalid --location argument", source="cli")
            args.location = default_location

    # Convert --at to UTC using resolved location
    if hasattr(args, "at") and isinstance(args.at, datetime):
        try:
            args.datetime = convert_to_utc(args.at, args.location)
        except Exception:
            args.datetime = convert_to_utc(datetime.now(), args.location)

    # Convert --from / --to to UTC
    for attr in ("from_dt", "to_dt"):
        if hasattr(args, attr) and isinstance(getattr(args, attr), datetime):
            try:
                setattr(args, attr, convert_to_utc(getattr(args, attr), args.location))
            except Exception:
                pass

    return args


#==================#
 # DISPLAY HELPERS #
#==================#

# Display a single-moment list of celestial states
def _display_celestial_states(states: list["CelestialState"], concise: bool = False):
    rows = []
    has_phase = False

    for state in states:
        full_name = f"{getattr(state, 'glyph', '?')} {getattr(state, 'name', '?')}"

        try:
            sign_glyph, sign_name = state.sign
            sign = f"{sign_glyph} {sign_name}"
        except Exception:
            sign_glyph, sign = "?", "?"

        try:
            orb = f"{state.orb:.2f}°"
        except Exception:
            orb = "?"

        try:
            phase_tuple = state.phase
            phase_str = f"{phase_tuple[1]} {phase_tuple[0]}" if phase_tuple else None
        except Exception:
            phase_tuple = None
            phase_str = None

        phase_angle = getattr(state, "phase_angle", None)
        waxing      = "wax." if getattr(state, "waxing", None) is True else "wan."
        retrograde  = "℞" if getattr(state, "retrograde", False) else ""

        if phase_str is not None and phase_angle is not None:
            has_phase = True

        rows.append((full_name, sign_glyph, sign, orb, retrograde, phase_str, phase_angle, waxing))

    if concise:
        for full_name, sg, _, orb, _, phase_str, phase_angle, waxing in rows:
            glyph = full_name.split(" ", 1)[0]
            if phase_str and phase_angle is not None:
                phase_glyph = phase_str.split(" ", 1)[0]
                suffix = f" {phase_glyph} {phase_angle:.2f}° {waxing}"
            else:
                suffix = ""
            print(f"{glyph} {sg} {orb}{suffix}")
    else:
        table = Table(show_header=True, title=None, box=box.SIMPLE, show_edge=False, pad_edge=False)
        table.add_column(" ",      no_wrap=True, min_width=2)
        table.add_column("Name",   no_wrap=True)
        table.add_column(" ",      no_wrap=True, min_width=2)
        table.add_column("Sign",   no_wrap=True)
        table.add_column("Orb",    no_wrap=True, justify="right")
        table.add_column("℞",      no_wrap=True, min_width=1)
        if has_phase:
            table.add_column(" ",           no_wrap=True, min_width=2)
            table.add_column("Phase",       no_wrap=True)
            table.add_column("Phase Angle", no_wrap=True, justify="right")
            table.add_column("Waxing",      no_wrap=True)
        for full_name, sign_glyph, sign, orb, retrograde, phase_str, phase_angle, waxing in rows:
            cel_glyph, cel_name = full_name.split(" ", 1)
            sign_name = sign.split(" ", 1)[1] if " " in sign else sign
            if has_phase:
                phase_glyph = phase_str.split(" ", 1)[0] if phase_str else ""
                phase_name  = phase_str.split(" ", 1)[1] if phase_str and " " in phase_str else ""
                table.add_row(cel_glyph, cel_name, sign_glyph, sign_name, orb, retrograde,
                              phase_glyph, phase_name, f"{phase_angle:.2f}°" if phase_angle else "", waxing)
            else:
                table.add_row(cel_glyph, cel_name, sign_glyph, sign_name, orb, retrograde)
        Console().print(table)


# Display aspects between a list of states at a single moment
def _display_aspects(states: list["CelestialState"]):
    global cli_wizard
    if cli_wizard is None:
        cli_wizard = _initialize_cli()
    aspects = cli_wizard.conjure_aspects(states)
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
def _display_trace(traces: list[list["CelestialState"]], targets: list[str], concise: bool = False):
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
            print(f"{ev.glyph} {ev.detail}  {bodies}  {ev.dt.strftime('%Y-%m-%d %H:%M')}")
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
                          ev.dt.strftime("%Y-%m-%d"),
                          ev.dt.strftime("%H:%M"))
        Console().print(table)


#===================#
 # HANDLE COMMANDS #
#===================#

def _handle_command(args):
    if args.command == "observe":
        _handle_observe(args)
    elif args.command == "seek":
        _handle_seek(args)
    elif args.command == "chart":
        if getattr(args, "targets", None) == ["live"]:
            _handle_live(args)
        elif getattr(args, "transit", None):
            _handle_transit_chart(args)
        elif getattr(args, "from_dt", None) and getattr(args, "to_dt", None):
            _handle_playback(args)
        else:
            _handle_chart(args)


def _handle_observe(args):
    global cli_wizard
    if cli_wizard is None:
        cli_wizard = _initialize_cli(verbose=False)

    has_range   = getattr(args, "from_dt", None) and getattr(args, "to_dt", None)
    attributes  = args.attributes or []

    try:
        if has_range and "transits" in attributes:
            # Transit / event detection mode
            events = cli_wizard.conjure_events(
                targets     = args.targets,
                start_dt    = args.from_dt,
                end_dt      = args.to_dt,
                location    = args.location,
                zodiac      = args.zodiac,
                step        = args.step,
            )
            _display_events(events, concise=args.concise)

        elif has_range:
            # Time-series trace mode — one trace per target, zipped by timestep
            traces_by_target = [
                cli_wizard.conjure_celestial_trace(
                    target   = target,
                    start_dt = args.from_dt,
                    end_dt   = args.to_dt,
                    step     = args.step,
                    location = args.location,
                    zodiac   = args.zodiac,
                    frames   = args.frames,
                )
                for target in args.targets
            ]
            # Zip into list-of-lists: traces[step_i] = [state_target_0, state_target_1, ...]
            traces = [list(step) for step in zip(*traces_by_target)]
            _display_trace(traces, args.targets, concise=args.concise)

        else:
            # Single-moment observation
            properties: list[str] = ["position"]
            if "phase" in attributes:
                properties.append("phenomenon")

            states: list[CelestialState] = []
            for target in args.targets:
                state = cli_wizard.conjure_celestial_state(
                    dt         = args.datetime,
                    location   = args.location,
                    target     = target,
                    zodiac     = args.zodiac,
                    properties = properties,
                    frames     = args.frames,
                )
                states.append(state)

            _display_celestial_states(states, concise=args.concise)

            if "aspects" in attributes:
                print()
                _display_aspects(states)

    except ValueError as e:
        print(f"Error: {e}")
    except Exception:
        handle_log("error", "failed to handle observation command", source="cli")
        traceback.print_exc()


def _handle_chart(args):
    from atlas.view.chart import RadixChart

    global cli_wizard
    if cli_wizard is None:
        cli_wizard = _initialize_cli(verbose=False)

    try:
        celestials = []
        for target in args.targets:
            state = cli_wizard.conjure_celestial_state(
                dt         = args.datetime,
                location   = args.location,
                target     = target,
                zodiac     = args.zodiac,
                properties = ["position"],
                frames     = ["ecliptic"],
            )
            celestials.append(state)

        cusps    = cli_wizard.conjure_houses(dt=args.datetime, location=args.location, zodiac=args.zodiac)
        aspects  = cli_wizard.conjure_aspects(celestials)
        title    = args.title or args.datetime.strftime("%Y-%m-%d  %H:%M")
        RadixChart.configure(cusps=cusps, celestials=celestials, aspects=aspects, title=title, save_path=_resolve_save_path(args.save or default_image_path if args.save is not None else None, ".png"))
        RadixChart.show()

    except ValueError as e:
        print(f"Error: {e}")
    except Exception:
        handle_log("error", "failed to handle chart command", source="cli")
        traceback.print_exc()


def _handle_transit_chart(args):
    from atlas.view.chart import TransitChart

    global cli_wizard
    if cli_wizard is None:
        cli_wizard = _initialize_cli(verbose=False)

    try:
        natal_dt   = args.datetime
        transit_dt = convert_to_utc(args.transit, args.location)

        natal_celestials   = []
        transit_celestials = []
        for target in args.targets:
            natal_celestials.append(cli_wizard.conjure_celestial_state(
                dt=natal_dt, location=args.location, target=target,
                zodiac=args.zodiac, properties=["position"], frames=["ecliptic"],
            ))
            transit_celestials.append(cli_wizard.conjure_celestial_state(
                dt=transit_dt, location=args.location, target=target,
                zodiac=args.zodiac, properties=["position"], frames=["ecliptic"],
            ))

        natal_cusps      = cli_wizard.conjure_houses(dt=natal_dt,   location=args.location, zodiac=args.zodiac)
        transit_cusps    = cli_wizard.conjure_houses(dt=transit_dt, location=args.location, zodiac=args.zodiac)
        transit_aspects  = cli_wizard.conjure_transit_aspects(natal_celestials, transit_celestials)
        title = args.title or f"{natal_dt.strftime('%Y-%m-%d')} → {transit_dt.strftime('%Y-%m-%d')}"

        TransitChart.configure_transit(
            cusps=natal_cusps, celestials=natal_celestials,
            transit_cusps=transit_cusps, transit_celestials=transit_celestials,
            transit_aspects=transit_aspects,
            title=title, save_path=_resolve_save_path(args.save or default_image_path if args.save is not None else None, ".png"),
        )
        TransitChart.show()

    except ValueError as e:
        print(f"Error: {e}")
    except Exception:
        handle_log("error", "failed to handle transit chart command", source="cli")
        traceback.print_exc()


def _handle_playback(args):
    from atlas.view.chart import PlaybackChart

    global cli_wizard
    if cli_wizard is None:
        cli_wizard = _initialize_cli(verbose=False)

    try:
        PlaybackChart.configure_playback(
            wizard     = cli_wizard,
            location   = args.location,
            zodiac     = args.zodiac,
            targets    = args.targets,
            start_dt   = args.from_dt,
            end_dt     = args.to_dt,
            step       = args.step,
            speed      = args.speed,
            save_path  = _resolve_save_path(args.save or default_video_path if args.save is not None else None, ".mp4"),
        )
        PlaybackChart.show()
    except Exception:
        handle_log("error", "failed to handle playback command", source="cli")
        traceback.print_exc()


def _handle_live(args):
    from atlas.view.chart import LiveRadixChart

    global cli_wizard
    if cli_wizard is None:
        cli_wizard = _initialize_cli(verbose=False)

    targets = list(config.get("celestials", {}).keys())

    try:
        LiveRadixChart.configure_live(
            wizard   = cli_wizard,
            location = args.location,
            zodiac   = args.zodiac,
            targets  = targets,
        )
        LiveRadixChart.show()
    except Exception:
        handle_log("error", "failed to handle live command", source="cli")
        traceback.print_exc()


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
            delta   = ev.dt - now
            local   = utc_to_local(ev.dt, location)
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
            delta = ev.dt - now
            local = utc_to_local(ev.dt, location)
            event = f"{ev.glyph} {ev.detail.title()}"
            table.add_row(body, event,
                          local.strftime("%Y-%m-%d"), local.strftime("%H:%M"), _until_str(delta))
        Console().print(table)


# Display a snapshot of currently active aspects: body | aspect | orb
def _display_aspect_snapshot(aspects: list[Aspect], concise: bool = False):
    if not aspects:
        print("No active aspects.")
        return
    glyphs = {k: v.get("glyph", "") for k, v in config.get("celestials", {}).items()}

    if concise:
        for asp in aspects:
            body = _body_str(asp.body_one.name, asp.body_two.name, glyphs)
            print(f"{body}  {asp.glyph} {asp.name}  {asp.orb:.2f}°")
    else:
        table = Table(show_header=True, title=None, box=box.SIMPLE, show_edge=False, pad_edge=False)
        table.add_column("Body",   no_wrap=True)
        table.add_column("Aspect", no_wrap=True)
        table.add_column("Orb",    no_wrap=True, justify="right")
        for asp in aspects:
            body = _body_str(asp.body_one.name, asp.body_two.name, glyphs)
            table.add_row(body, f"{asp.glyph} {asp.name.capitalize()}", f"{asp.orb:.2f}°")
        Console().print(table)


def _handle_seek(args):
    global cli_wizard
    if cli_wizard is None:
        cli_wizard = _initialize_cli(verbose=False)

    targets   = args.targets or list(config.get("celestials", {}).keys())
    has_range = getattr(args, "from_dt", None) and getattr(args, "to_dt", None)

    try:
        # Aspect snapshot: active aspects at a moment (no time scanning needed)
        if args.type == "aspect" and not has_range and args.limit == 1:
            states  = [cli_wizard.conjure_celestial_state(
                           dt=args.datetime, location=args.location, target=t,
                           zodiac=args.zodiac, properties=["position"], frames=["ecliptic"])
                       for t in targets]
            aspects = cli_wizard.conjure_aspects(states)
            if args.detail:
                aspects = [a for a in aspects if args.detail.lower() in a.name.lower()]
            _display_aspect_snapshot(aspects, concise=args.concise)

        elif has_range:
            # Entry-based search over an explicit range (all event types)
            events = cli_wizard.conjure_events(
                targets     = targets,
                start_dt    = args.from_dt,
                end_dt      = args.to_dt,
                location    = args.location,
                zodiac      = args.zodiac,
                event_types = [args.type],
            )
            if args.detail:
                events = [e for e in events if args.detail.lower() in e.detail.lower()]
            _display_seek_results(events, location=args.location, concise=args.concise)

        else:
            # Rolling next-occurrence search (all types; --limit > 1 with aspect = entry mode)
            start   = args.datetime
            horizon = start + timedelta(days=365)
            window  = timedelta(days=30)
            results = []
            current = start
            while current < horizon and len(results) < args.limit:
                end    = min(current + window, horizon)
                events = cli_wizard.conjure_events(
                    targets     = targets,
                    start_dt    = current,
                    end_dt      = end,
                    location    = args.location,
                    zodiac      = args.zodiac,
                    event_types = [args.type],
                )
                if args.detail:
                    events = [e for e in events if args.detail.lower() in e.detail.lower()]
                results.extend(events)
                current = end
            _display_seek_results(results[:args.limit], location=args.location, concise=args.concise)

    except Exception:
        handle_log("error", "failed to handle seek command", source="cli")
        traceback.print_exc()


def main():
    parser = _build_parser()
    args   = _parse_arguments(parser)
    _handle_command(args)


if __name__ == "__main__":
    main()
