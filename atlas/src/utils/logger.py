# src/utils/logger.py


# Standard libraries
import logging
import traceback


_logger = logging.getLogger("atlas")
if not _logger.handlers:
	# Initialize handler
	handler = logging.StreamHandler()

	# Initialize formatter
	formatter = logging.Formatter(
		"%(asctime)s [%(levelname)s] %(name)s: %(message)s"
	)

	# Set the formatter to the handler
	handler.setFormatter(formatter)

	# Add handler to the logger
	_logger.addHandler(handler)


def handle_log(level: str, message: str, *args, **kwargs):
	# Handle log by level
	match level:
		case "debug":
			_logger.log(logging.DEBUG, message, *args, **kwargs)

		case "info":
			_logger.log(logging.INFO, message, *args, **kwargs)

		case "warning":
			_logger.log(logging.WARNING, message, *args, **kwargs)

		case "error":
			_logger.log(logging.ERROR, message, *args, **kwargs)

		case "critical":
			_logger.log(logging.CRITICAL, message, *args, **kwargs)

		case _:
			_logger.log(logging.INFO, message, *args, **kwargs)