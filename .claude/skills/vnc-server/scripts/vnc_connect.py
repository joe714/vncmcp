#!/usr/bin/env python3
"""
Connect to a VNC server

Usage: python vnc_connect.py <host> <port> [password]

Starts a background daemon that maintains the VNC connection.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from vnc_client import STATE_DIR, STATE_FILE, PID_FILE, SOCKET_PATH, get_session


def is_daemon_running() -> bool:
    """Check if VNC daemon is already running"""
    if not PID_FILE.exists():
        return False

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return True
    except (ProcessLookupError, ValueError):
        # Clean up stale files
        for f in [PID_FILE, STATE_FILE, SOCKET_PATH]:
            if f.exists():
                f.unlink()
        return False


def main():
    parser = argparse.ArgumentParser(description="Connect to a VNC server")
    parser.add_argument("host", help="VNC server hostname or IP")
    parser.add_argument("port", type=int, help="VNC server port (usually 5900)")
    parser.add_argument("--password", "-p", help="VNC password (if required)")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Force reconnect even if already connected")

    args = parser.parse_args()

    # Check if already connected
    if is_daemon_running() and not args.force:
        session = get_session()
        if session:
            print(json.dumps({
                "status": "already_connected",
                "host": session.host,
                "port": session.port,
                "width": session.width,
                "height": session.height,
                "pid": session.pid,
                "message": "Already connected. Use --force to reconnect."
            }))
            return 0

    # Kill existing daemon if force reconnect
    if args.force and is_daemon_running():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except:
            pass

    # Ensure state directory exists
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Start daemon in background
    daemon_cmd = [
        sys.executable,
        str(SCRIPT_DIR / "vnc_client.py"),
        "daemon",
        args.host,
        str(args.port),
    ]
    if args.password:
        daemon_cmd.append(args.password)

    # Start daemon process
    process = subprocess.Popen(
        daemon_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    # Wait for connection result
    try:
        stdout, stderr = process.communicate(timeout=15)
        output = stdout.decode('utf-8').strip()

        if output:
            try:
                result = json.loads(output)
                print(json.dumps(result, indent=2))
                return 0 if result.get("status") == "connected" else 1
            except json.JSONDecodeError:
                print(output)
                return 0

        if stderr:
            print(json.dumps({
                "status": "error",
                "error": stderr.decode('utf-8').strip()
            }))
            return 1

    except subprocess.TimeoutExpired:
        # Check if daemon started successfully
        time.sleep(1)
        if is_daemon_running():
            session = get_session()
            if session:
                print(json.dumps({
                    "status": "connected",
                    "host": session.host,
                    "port": session.port,
                    "width": session.width,
                    "height": session.height,
                    "pid": session.pid,
                }))
                return 0

        print(json.dumps({
            "status": "error",
            "error": "Connection timed out"
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
