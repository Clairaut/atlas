# Standard libraries
from typing import TYPE_CHECKING
from datetime import datetime
import argparse


# Internal libraries
from src.core.wizard import Wizard
from src.core.observatory import Observatory
from src.clients.ephe_client import EphemerisClient
from src.models.location import Location
from src.utils.logger import handle_log
from src.utils.config import load_config

if TYPE_CHECKING:
    from atlas.src.models.location import Location


# Load configuration
config: dict = load_config()

# Extract default location from config
lat: float = config.get("location", {}).get("latitude", 0)
lon: float = config.get("location", {}).get("longitude", 0)
alt: float = config.get("location", {}).get("altitude", 0)

# Create default location object
default_location_str: str = f"({lat}, {lon}, {alt})"
default_location = Location(lat=lat, lon=lon, alt=alt)


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
    observe_parser.add_argument("-t", "--time", help = "time of observation '(%H-%M-%s)'", nargs = "?", default = datetime.now().time().strftime("%H:%M:%s"))
    observe_parser.add_argument("-l", "--location", help = "location of observation", nargs = "?", default = default_location_str)
    observe_parser.add_argument("-z", "--zodiac", help = "zodiac type of observation", choices = ["tropical", "sidereal"], default = "tropical")
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

    # Parse the time argument into a datetime object
    if hasattr(args, "time"):
        try:
            args.time = datetime.strptime(args.time, "%H:%M:%s")
        except ValueError as e:
            handle_log("error", "invalid time argument input for observation parser", source = "cli")

    # Parse the location argument into a Location object
    if hasattr(args, "location"):
        try:
            # Strip argument and split it into its components
            stripped_location_arg = args.location.strip(" ")
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


#===================#
 # HANDLE COMMANDS #
#===================#

def _handle_command(args):
    # Call the function to handle the relative command
    if args.command == 'observe':
        _handle_observe(args)
        

# MAIN HANDLERS

def _handle_observe(args):





if __name__ == "__main__":
    cli_wizard = _initialize_cli(verbose=True)

