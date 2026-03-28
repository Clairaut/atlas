# Standard libraries
from typing import TYPE_CHECKING
from datetime import datetime
import argparse
import traceback

# Internal libraries
from atlas.src.core.wizard import Wizard
from atlas.src.core.observatory import Observatory
from atlas.src.clients.ephe_client import EphemerisClient
from atlas.src.models.location import Location
from atlas.src.models.celestial_state import CelestialState
from atlas.src.utils.logger import handle_log
from atlas.src.utils.config import load_config

if TYPE_CHECKING:
    from atlas.src.models.location import Location

# External libraries
from rich.table import Table
from rich.console import Console


# Load configuration
config: dict = load_config()

# Extract default location from config
lat: float = config.get("location", {}).get("latitude", 0)
lon: float = config.get("location", {}).get("longitude", 0)
alt: float = config.get("location", {}).get("altitude", 0)

# Create default location object
default_location_str: str = f"({lat}, {lon}, {alt})"
default_location = Location(lat=lat, lon=lon, alt=alt)


cli_wizard = None

# Initialize the CLI components
def _initialize_cli(verbose: bool = False) -> Wizard:
    # Setup Ephemeris Client, Observatory, and Wizard
    ephe_client = EphemerisClient(verbose=verbose)
    observatory = Observatory(ephe_client=ephe_client, dt=datetime.now(), location=default_location, verbose=verbose)
    wizard = Wizard(observatory=observatory, verbose=verbose)

    # Log initialization
    if verbose:
        handle_log("info", "CLI components initialized", source="cli")

    return wizard



#==========================#
 # MAIN PARSER CONSTRUCTION #
#==========================#

# Construct parser
def _build_parser() -> argparse.ArgumentParser:
    # Construct the arch parser
    parser = argparse.ArgumentParser(
        prog="atlas-dev",
        description="a SwissEph interface designed for visualizing astrological/astronomical data.",
        epilog="created by clairaut"
    )

    # Construct subparsers group
    subparsers = parser.add_subparsers(required = True, dest = "command")

    # Construct individual subparsers
    observe_parser = subparsers.add_parser(
        name = "observe", 
        help = "initiates the multi-faceted observation of listed celestial bodies",
        usage = "atlas observe {celestial_bodies}*"
    )

    # Add basic arguments to the observe parser
    observe_parser.add_argument("targets", help = "celestial bodies to be observed", nargs = "+")
    observe_parser.add_argument("-d", "--date", help = "date of observation '(%Y-%m-%d)'", nargs = "?", default = datetime.now().date().strftime("%Y-%m-%d"))
    observe_parser.add_argument("-t", "--time", help = "time of observation '(%H-%M-%s)'", nargs = "?", default = datetime.now().time().strftime("%H:%M:%S"))
    observe_parser.add_argument("-l", "--location", help = "location of observation", nargs = "?", default = default_location_str)
    observe_parser.add_argument("-z", "--zodiac", help = "zodiac type of observation", choices = ["tropical", "sidereal"], default = "tropical")
    observe_parser.add_argument("-a", "--attributes", help="additional attributes to be displayed within observation", choices=["phase", "distance"], nargs="*", default=None)
    observe_parser.add_argument("-f", "--frames", help = "frame to be utilized in observation of celestials", nargs = "*", default = ["phenomenon"])
    observe_parser.add_argument("-c", "--concise", help = "lowers verbosity of response", action = "store_true")


    return parser


#====================#
 # ARGUMENT PARSERS #
#====================#

# Parse all arguments
def _parse_arguments(parser: argparse.ArgumentParser):
    # Get arguments of the parser
    args = parser.parse_args()

    # Parse the date argument into a datetime object
    if hasattr(args, "date"):
        try:
            args.date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError as e:
            handle_log("error", "invalid date argument input for observation parser", source = "cli")
    else:
        args.date = datetime.now().date()

    # Parse the time argument into a datetime object
    if hasattr(args, "time"):
        try:
            args.time = datetime.strptime(args.time, "%H:%M:%S").time()
        except ValueError as e:
            handle_log("error", "invalid time argument input for observation parser", source = "cli")
            args.time = datetime.now().time()
    else:
        args.time = datetime.now().time()

    # Parse the location argument into a Location object
    if hasattr(args, "location"):
        try:
            # Remove parentheses and spaces, then split
            stripped_location_arg = args.location.strip(" ()")
            parts = [float(x) for x in stripped_location_arg.split(",")]

            # Initialize the location constituents  
            lat: float = 0.0
            lon: float = 0.0
            alt: float = 0.0

            # If the length of the parts is 3, include altitude, else exclude
            if len(parts) == 3:
                lat, lon, alt = parts
            elif len(parts) == 2:
                lat, lon = parts
            else:
                raise ValueError("2-3 components expected for location argument")

            # Construct location object
            args.location = Location(lat, lon, alt)

        except ValueError as e:
            handle_log("error", "invalid location argument input for observation parser", source = "cli")

    # Combine date and time into a datetime object for use in conjure_celestial_state
    try:
        args.datetime = datetime.combine(args.date, args.time)
    except Exception:
        args.datetime = datetime.now()

    return args



# Display celestial states
def _display_celestial_states(states: list["CelestialState"]):
    table = Table(show_header=True, title=None)
    table.add_column("Name")
    table.add_column("Sign")
    table.add_column("Orb")
    table.add_column("Retrograde")

    for state in states:
        glyph = getattr(state, "glyph", "?")
        name = getattr(state, "name", "?")
        full_name = f"{glyph} {name}"

        # Sign is a tuple (glyph, name)
        try:
            sign_glyph, sign_name = state.sign
            sign = f"{sign_glyph} {sign_name}"
        except Exception:
            sign = "?"

        # Get attributes if specified
        orb = f"{getattr(state, 'orb', '?'):.2f}" if getattr(state, 'orb', None) is not None else "?"

        retrograde = "℞" if getattr(state, "retrograde", False) else ""
        table.add_row(str(full_name), sign, orb, retrograde)

    console = Console()
    console.print(table)


#===================#
 # HANDLE COMMANDS #
#===================#

def _handle_command(args):
    # Call the function to handle the relative command
    if args.command == 'observe':
        _handle_observe(args)
        
def _handle_observe(args):
    global cli_wizard
    if cli_wizard is None:
        cli_wizard = _initialize_cli(verbose=True)
    try:
        # Initialize list of celestial states
        celestial_states: list = []

        # Determine which properties are to be included in query
        properties: list[str] = ["position"]
        if args.attributes and "phase" in args.attributes:
            properties.append("phenomenon") # Append phenomenon if phase is specified in attributes
    


        # Loop over targets and 
        for target in args.targets:
            celestial_state: "CelestialState" = cli_wizard.conjure_celestial_state(
                dt=args.datetime,
                location=args.location,
                target=target,
                zodiac=args.zodiac,
                properties=properties,
                frames=args.frames
            )
            
            celestial_states.append(celestial_state)

        # Make a table which overviews the data
        _display_celestial_states(celestial_states)

    except Exception as e:
        handle_log("error", "failed to handle observation command", source = "cli")
        traceback.print_exc()



def main():
    # Entry point for the CLI
    global cli_wizard
    cli_wizard = _initialize_cli(verbose=False)
    parser = _build_parser()
    args = _parse_arguments(parser)
    _handle_command(args)


if __name__ == "__main__":
    main()
