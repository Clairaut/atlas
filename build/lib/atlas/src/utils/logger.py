# src/utils/logger.py


# Standard libraries
import logging
from pathlib import Path


LOG_DIR = Path.cwd() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "atlas.log"

_LEVELS = {
	"debug": logging.DEBUG,
	"info": logging.INFO,
	"warning": logging.WARNING,
	"error": logging.ERROR,
	"critical": logging.CRITICAL,
}

_logger = logging.getLogger("atlas")
if not _logger.handlers:
	_logger.setLevel(logging.DEBUG)
	_logger.propagate = False

	formatter = logging.Formatter(
		"%(asctime)s [%(levelname)s] %(source)s: %(message)s"
	)

	file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
	file_handler.setFormatter(formatter)

	stream_handler = logging.StreamHandler()
	stream_handler.setFormatter(formatter)

	_logger.addHandler(file_handler)
	_logger.addHandler(stream_handler)


def handle_log(level: str, message: str, *args, source: str = "atlas", **kwargs):
	log_level = _LEVELS.get(level.lower(), logging.INFO)
	_logger.log(log_level, message, *args, extra={"source": source}, **kwargs)
