# gui/logging_setup.py
from __future__ import annotations

import logging
import os
import queue
from logging.handlers import RotatingFileHandler


class TkQueueHandler(logging.Handler):
    """Logging handler that pushes formatted log lines into a thread-safe queue."""

    def __init__(self, q: queue.Queue[str]):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            try:
                msg = record.getMessage()
            except Exception:
                msg = "Log formatting error"
        try:
            self.q.put_nowait(msg)
        except Exception:
            # drop if queue full
            pass


def setup_global_logging(log_queue: queue.Queue[str], log_dir: str = "logs") -> logging.Logger:
    """
    Configure root logger:
      - rotating file logs
      - console logs
      - GUI queue logs
    Returns root logger.
    """
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove existing handlers to avoid duplicates
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler (rotating)
    file_path = os.path.join(log_dir, "trading_bot.log")
    fh = RotatingFileHandler(
        file_path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # GUI queue handler
    qh = TkQueueHandler(log_queue)
    qh.setLevel(logging.DEBUG)
    qh.setFormatter(fmt)
    root.addHandler(qh)

    root.debug("Logging initialized. Log file: %s", os.path.abspath(file_path))
    return root
