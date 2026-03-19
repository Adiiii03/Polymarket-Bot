"""
logger_setup.py — Coloured console + file logging.
"""

import logging
import colorlog
from config import LOG_LEVEL


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Already configured

    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Coloured console handler
    console = colorlog.StreamHandler()
    console.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(name)s] %(levelname)s%(reset)s  %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG":    "cyan",
            "INFO":     "white",
            "WARNING":  "yellow",
            "ERROR":    "red",
            "CRITICAL": "bold_red",
        }
    ))
    logger.addHandler(console)

    # Plain file handler
    fh = logging.FileHandler("bot.log")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s  %(message)s"
    ))
    logger.addHandler(fh)

    return logger
