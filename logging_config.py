"""Centralized logging configuration.

Routes Loguru through Rich's :class:`~rich.logging.RichHandler` so that every
``from loguru import logger`` call across the codebase renders with colorized
level badges, aligned timestamps, and Rich-rendered tracebacks — without having
to touch the individual log calls.

Usage:
    from logging_config import setup_logging
    setup_logging()          # once, at process startup

The shared :data:`console` is exported for modules that want to print other
Rich content (tables, panels, colored status lines) to the same stream.
"""

import logging

from loguru import logger
from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback

# Shared console (stderr, matching Loguru's default sink). Import this anywhere
# you want Rich output to land on the same stream as the logs.
console = Console(stderr=True)

_configured = False


def setup_logging(level: str = "INFO") -> None:
    """Route Loguru output through Rich. Idempotent — safe to call repeatedly.

    Args:
        level: Minimum level to emit (e.g. "DEBUG", "INFO", "WARNING").
    """
    global _configured
    if _configured:
        return

    # Pretty, colorized tracebacks for uncaught exceptions too.
    install_rich_traceback(console=console, show_locals=False)

    rich_handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        show_time=True,
        show_level=True,
        show_path=False,
        markup=False,
        log_time_format="[%H:%M:%S]",
    )

    def rich_sink(message) -> None:
        """Bridge a Loguru record to the Rich handler.

        We rebuild a stdlib LogRecord from the *bare* message plus the exception
        info, rather than handing Loguru's pre-formatted string straight to Rich.
        That way RichHandler owns the traceback rendering (one pretty box) instead
        of Loguru also appending its own plain-text copy.
        """
        record = message.record
        exc = record["exception"]
        exc_info = (exc.type, exc.value, exc.traceback) if exc else None

        std_record = logging.LogRecord(
            name=record["name"] or "root",
            level=record["level"].no,
            pathname=record["file"].path,
            lineno=record["line"],
            msg=record["message"],
            args=(),
            exc_info=exc_info,
        )
        # Preserve Loguru's own level names (INFO/WARNING/SUCCESS/…) verbatim.
        std_record.levelname = record["level"].name
        rich_handler.handle(std_record)

    # Replace Loguru's default stderr sink with the Rich bridge.
    logger.remove()
    logger.add(rich_sink, level=level, format="{message}")

    # Make stdlib logging (Flask/Werkzeug, third-party libs) share the same look.
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[rich_handler],
        force=True,
    )

    _configured = True
