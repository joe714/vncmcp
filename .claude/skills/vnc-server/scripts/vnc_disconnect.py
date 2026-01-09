#!/usr/bin/env python3
"""
Disconnect from VNC server

Usage: python vnc_disconnect.py
"""

import json
import os
import signal
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from vnc_client import send_command, get_session, PID_FILE, STATE_FILE, SOCKET_PATH


def main():
    session = get_session()

    if not session:
        print(json.dumps({
            "status": "not_connected",
            "message": "No active VNC session."
        }))
        return 0

    # Try graceful disconnect via socket
    result = send_command({"command": "disconnect"})

    # Give daemon time to clean up
    time.sleep(0.5)

    # Force kill if still running
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.3)
            # Force kill if still alive
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except (ProcessLookupError, ValueError):
            pass

    # Clean up files
    for f in [PID_FILE, STATE_FILE, SOCKET_PATH]:
        if f.exists():
            try:
                f.unlink()
            except:
                pass

    print(json.dumps({
        "status": "disconnected",
        "previous_host": session.host,
        "previous_port": session.port,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
