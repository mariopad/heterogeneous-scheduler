"""
shared/logging.py

Structured JSON logging with human-readable console output.

Logs are output in two formats:
1. JSON to stderr (machine-parseable for analysis)
2. Human-readable to stdout (real-time monitoring in console)
"""

import json
import sys
from enum import Enum
from typing import Any, Dict, Optional

from shared.timeutils import utc_now


class LogLevel(Enum):
    """Log severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class StructuredLogger:
    """
    Logger that outputs both JSON (for analysis) and human-readable (for console).
    """

    def __init__(self, name: str, min_level: LogLevel = LogLevel.INFO):
        self.name = name
        self.min_level = min_level
        self.context: Dict[str, Any] = {}

    def set_context(self, **kwargs):
        """Add contextual information to all subsequent logs."""
        self.context.update(kwargs)

    def clear_context(self):
        """Clear contextual information."""
        self.context.clear()

    def _should_log(self, level: LogLevel) -> bool:
        """Check if this level should be logged."""
        levels = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR]
        return levels.index(level) >= levels.index(self.min_level)

    def _format_json(
        self,
        level: LogLevel,
        message: str,
        **kwargs
    ) -> str:
        """Format log entry as JSON."""
        entry = {
            "timestamp": utc_now().isoformat(),
            "logger": self.name,
            "level": level.value,
            "message": message,
            **self.context,
            **kwargs,
        }
        return json.dumps(entry, default=str)

    def _format_console(
        self,
        level: LogLevel,
        message: str,
        state: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """Format log entry for console (human-readable with state info)."""
        # Build state line
        state_parts = []
        if state:
            if "nodes" in state:
                state_parts.append(f"nodes={state['nodes']}")
            if "queue_size" in state:
                state_parts.append(f"queue={state['queue_size']}")
            if "running_jobs" in state:
                state_parts.append(f"running={state['running_jobs']}")
            if "db_jobs_completed" in state:
                state_parts.append(f"completed={state['db_jobs_completed']}")

        state_str = " | " + " ".join(state_parts) if state_parts else ""

        # Color codes for terminal
        colors = {
            LogLevel.DEBUG: "\033[36m",    # Cyan
            LogLevel.INFO: "\033[32m",     # Green
            LogLevel.WARNING: "\033[33m",  # Yellow
            LogLevel.ERROR: "\033[31m",    # Red
        }
        reset = "\033[0m"

        color = colors.get(level, "")
        level_str = f"{color}[{level.value}]{reset}"

        return f"{level_str} {message}{state_str}"

    def log(
        self,
        level: LogLevel,
        message: str,
        state: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """Log a message at the specified level."""
        if not self._should_log(level):
            return

        # Output JSON to stderr
        json_log = self._format_json(level, message, **kwargs)
        print(json_log, file=sys.stderr)

        # Output human-readable to stdout
        console_log = self._format_console(level, message, state, **kwargs)
        print(console_log, file=sys.stdout, flush=True)

    def debug(self, message: str, state: Optional[Dict] = None, **kwargs):
        """Log at DEBUG level."""
        self.log(LogLevel.DEBUG, message, state, **kwargs)

    def info(self, message: str, state: Optional[Dict] = None, **kwargs):
        """Log at INFO level."""
        self.log(LogLevel.INFO, message, state, **kwargs)

    def warning(self, message: str, state: Optional[Dict] = None, **kwargs):
        """Log at WARNING level."""
        self.log(LogLevel.WARNING, message, state, **kwargs)

    def error(self, message: str, state: Optional[Dict] = None, **kwargs):
        """Log at ERROR level."""
        self.log(LogLevel.ERROR, message, state, **kwargs)

    def event(
        self,
        event_type: str,
        message: str,
        state: Optional[Dict] = None,
        **kwargs
    ):
        """Log an event with a specific type (e.g., 'job.submitted', 'node.registered')."""
        self.log(
            LogLevel.INFO,
            message,
            state,
            event_type=event_type,
            **kwargs
        )


# Module-level logger factories
def get_logger(name: str) -> StructuredLogger:
    """Get or create a logger for the given name."""
    return StructuredLogger(name)
