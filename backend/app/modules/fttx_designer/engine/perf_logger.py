"""Verbatim port of ``PerformanceLogger`` from
``FTTx Designer — dual PON integrated.py``. Zero QGIS dependency in the
source already (stdlib ``logging``/``os``/``sys``/``time``/``re``/
``tempfile``/``datetime`` only), so nothing changed here.

Per the integration plan (§7.3), the web port's Celery task updates
``fttx_design_runs.progress_pct``/``current_stage`` at each pipeline stage
boundary instead of the PyQt GUI's ``pyqtSignal``-based ``GuiLogHandler`` —
but that replaces the *consumer* of this class's stdout/file logging, not
the class itself. ``PerformanceLogger`` keeps writing exactly as it did in
the standalone script; the Celery task additionally reads back
``get_findings()`` after a run to populate ``fttx_validation_findings``
(CLAUDE.md's own documented mechanism — this is "the only place validation
outcomes are actually captured as data").
"""

from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from typing import Dict, List


class PerformanceLogger:
    """Performance logging utility.

    [Run-log fix] This used to attach a bare ``logging.StreamHandler()``, which
    writes to **stderr**. The QGIS Python console does not surface stderr from a
    logging handler, so a run launched with ``exec(compile(...))`` produced a
    traceback and nothing else — every ``[B2B-HEADROOM]``, ``[B2B-OBJECTIVE]``
    and ``[DISTANCE-ORACLE]`` diagnostic was generated and then thrown away.

    Every run now writes to two places:
      • stdout, so the QGIS Python console shows it live
      • a timestamped file, so a whole run can be saved and inspected after

    The file path is printed at the top of every run. One file per run (mode
    'w' on a unique name), so running twice in one QGIS session gives two
    separate logs instead of one interleaved one.
    """

    #: Set False for console-only output.
    WRITE_LOG_FILE = True
    #: Directory for run logs. None = Desktop if writable, else the temp dir.
    LOG_DIR = None
    #: Resolved path of the most recent run's log file.
    last_log_path = None

    @classmethod
    def _resolve_log_dir(cls):
        if cls.LOG_DIR:
            return cls.LOG_DIR
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(desktop) and os.access(desktop, os.W_OK):
            return desktop
        return tempfile.gettempdir()

    def __init__(self):
        self.start_time = time.time()
        self.module_times = {}
        # Structured findings, classified from the same log()/error() calls
        # every validate_*/repair function in the pipeline already makes —
        # this is the ONLY interception point, so no call site anywhere else
        # needs to change (see get_findings() / DED report generator).
        self.findings: List[Dict[str, str]] = []
        self.logger = logging.getLogger('FTTX_Design')
        self.logger.setLevel(logging.INFO)

        # Do NOT reuse handlers across runs. The old `if not
        # self.logger.handlers` guard meant a handler attached by an earlier
        # run in the same QGIS session survived, so a second run kept writing
        # to the first run's destination (or to invisible stderr).
        for _h in list(self.logger.handlers):
            self.logger.removeHandler(_h)
            try:
                _h.close()
            except Exception:
                pass
        self.logger.propagate = False

        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'
        )

        # The ported pipeline logs plenty of non-ASCII punctuation
        # (arrows, em dashes, ✓/✗) in its messages. On a console whose
        # encoding isn't UTF-8-capable (Windows' default cp1252, seen
        # during Phase 6 load testing), the default 'strict' error policy
        # makes StreamHandler.emit() raise UnicodeEncodeError per message
        # — logging's own handleError() catches it so the process doesn't
        # crash, but the message is dropped and a traceback is spammed to
        # stderr instead. reconfigure() only changes behaviour for
        # characters the stream's codec can't represent; on an
        # already-UTF-8 stream (the normal case on Linux, where this
        # actually runs in production) it's a no-op. The persisted log
        # FILE handler below is unaffected either way — it already opens
        # with encoding='utf-8' explicitly.
        console_stream = sys.stdout
        try:
            console_stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
        console = logging.StreamHandler(console_stream)
        console.setFormatter(formatter)
        self.logger.addHandler(console)

        self.log_path = None
        if self.WRITE_LOG_FILE:
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = os.path.join(self._resolve_log_dir(), f"fttx_run_{stamp}.log")
                fh = logging.FileHandler(path, mode='w', encoding='utf-8')
                fh.setFormatter(formatter)
                self.logger.addHandler(fh)
                self.log_path = path
                PerformanceLogger.last_log_path = path
            except Exception as exc:
                # Logging setup must never break a run.
                self.logger.info(
                    f"WARNING: could not open a run-log file ({exc}); "
                    f"console output only."
                )

        if self.log_path:
            self.logger.info(f"Run log: {self.log_path}")
            # Printed unconditionally as well: if the console is filtering the
            # logging stream for any reason, this still says where the log went.
            print(f"[FTTx] Run log: {self.log_path}")

    def close(self):
        """Flush and detach handlers so the file is complete on disk.

        Called from run_fttx_design's finally block. Without it a handler can
        still hold buffered lines when the operator opens the log immediately
        after a failed run.
        """
        for _h in list(self.logger.handlers):
            try:
                _h.flush()
            except Exception:
                pass
            self.logger.removeHandler(_h)
            try:
                _h.close()
            except Exception:
                pass

    def start_module(self, module_name: str):
        """Start timing a module"""
        self.module_times[module_name] = time.time()
        self.logger.info(f"Starting module: {module_name}")

    def end_module(self, module_name: str):
        """End timing a module and log duration"""
        if module_name in self.module_times:
            duration = time.time() - self.module_times[module_name]
            self.logger.info(f"Completed module: {module_name} - Duration: {duration:.2f} seconds")
            return duration
        return 0

    def log(self, message: str):
        """Log an info message"""
        self.logger.info(message)
        if "WARNING" in message:
            self._record_finding("WARNING", message)

    def error(self, message: str):
        """Log an error message"""
        self.logger.error(message)
        self._record_finding("ERROR", message)

    def _record_finding(self, severity: str, message: str) -> None:
        """Classify a log/error message into a structured finding.

        Category is the first "[BRACKETED_TAG]" in the message (the
        convention already used throughout the pipeline, e.g.
        "WARNING [NO_POLE_IN_ZONE]: ..."), else "GENERAL". This never changes
        what gets validated or how — it only captures, for later reporting
        (see Validation_Results output layer / DED report generator), what
        the existing checks already decided to log.
        """
        match = re.search(r"\[([A-Za-z0-9_-]+)\]", message)
        category = match.group(1) if match else "GENERAL"
        self.findings.append({
            "severity": severity, "category": category, "message": message,
        })

    def get_findings(self) -> List[Dict[str, str]]:
        """Every WARNING/ERROR finding recorded so far this run."""
        return list(self.findings)
