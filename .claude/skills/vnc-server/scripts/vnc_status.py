#!/usr/bin/env python3
"""
Check VNC connection status

Usage: python vnc_status.py
"""

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from vnc_client import send_command, get_session, PID_FILE, STATE_FILE, SOCKET_PATH


def is_daemon_running() -> bool:
    """Check if VNC daemon process is running"""
    if not PID_FILE.exists():
        return False

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return True
    except (ProcessLookupError, ValueError):
        return False


def main():
    # Check for session state
    session = get_session()

    if not session:
        print(json.dumps({
            "status": "disconnected",
            "message": "No VNC session. Run vnc_connect.py to connect."
        }))
        return 0

    # Check if daemon is still running
    if not is_daemon_running():
        # Clean up stale files
        for f in [PID_FILE, STATE_FILE, SOCKET_PATH]:
            if f.exists():
                try:
                    f.unlink()
                except:
                    pass

        print(json.dumps({
            "status": "disconnected",
            "message": "VNC daemon not running. Session was terminated."
        }))
        return 0

    # Query daemon for live status
    result = send_command({"command": "status"})

    if "error" in result:
        print(json.dumps({
            "status": "error",
            "error": result["error"],
            "session": {
                "host": session.host,
                "port": session.port,
                "pid": session.pid,
            }
        }))
        return 1

    # Add session timing info
    result["started_at"] = session.started_at
    result["last_activity"] = session.last_activity
    result["pid"] = session.pid

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
