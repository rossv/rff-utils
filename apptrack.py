"""Lightweight application telemetry helpers.

The tracker intentionally never raises to the caller. If telemetry cannot be
sent (offline machine, endpoint timeout, etc.), the app keeps running.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import os
import platform
import socket
import threading
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional
from urllib.request import Request, urlopen

APPTRACK_ID = "1033"
APPTRACK_URL = "https://hook.us1.make.com/vak9i0ypopw4vzu82ajclyfgue3jbv2c"
APPTRACK_COMPANY = "Wade Trim"


def _safe_username() -> str:
    """Return a best-effort local username without raising."""

    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def _runtime_seconds(start_time: _dt.datetime) -> float:
    return (_dt.datetime.now() - start_time).total_seconds()


def send_apptrack_ping(
    *,
    start_time: _dt.datetime,
    channel: str,
    version: Optional[str] = None,
) -> None:
    """Send telemetry for this app execution.

    Failures are swallowed by design so telemetry remains non-fatal.
    """

    runtime_seconds = _runtime_seconds(start_time)
    version_text = version or platform.python_version()
    query_string = urllib.parse.urlencode(
        {
            "appID": APPTRACK_ID,
            "company": APPTRACK_COMPANY,
            "hostname": socket.gethostname(),
            "user": _safe_username(),
            "version": version_text,
            "runtime": f"{runtime_seconds:.3f}",
            "channel": channel,
        }
    )
    try:
        request_site = Request(
            f"{APPTRACK_URL}?{query_string}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        urlopen(request_site, timeout=4).read()
    except Exception:
        # Tracking should never block app workflows.
        return


@dataclass
class AppTracker:
    """Runtime-scoped telemetry helper for CLI and GUI entry points."""

    channel: str
    version: Optional[str] = None
    start_time: _dt.datetime = field(default_factory=_dt.datetime.now)

    def ping_async(self) -> None:
        """Fire-and-forget telemetry call so UI shutdown never blocks."""

        thread = threading.Thread(
            target=send_apptrack_ping,
            kwargs={
                "start_time": self.start_time,
                "channel": self.channel,
                "version": self.version,
            },
            daemon=True,
        )
        thread.start()

