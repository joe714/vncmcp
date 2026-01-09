#!/usr/bin/env python3
"""
Perform keyboard operations on the VNC server

Usage:
    python vnc_keyboard.py type "Hello World"
    python vnc_keyboard.py key Return
    python vnc_keyboard.py key ctrl+c
    python vnc_keyboard.py key alt+F4
    python vnc_keyboard.py key shift+a

Supported special keys:
    Modifiers: ctrl, alt, shift, meta, super, win, cmd
    Function: f1-f12
    Navigation: escape, tab, backspace, return/enter, insert, delete,
                home, end, pageup, pagedown, left, right, up, down
    Other: space, print, scrolllock, pause, capslock, numlock
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from vnc_client import send_command, get_session


def parse_key_combo(combo: str) -> list:
    """Parse a key combination like 'ctrl+shift+a' into list of keys"""
    parts = combo.lower().replace("-", "+").split("+")
    return [p.strip() for p in parts if p.strip()]


def main():
    parser = argparse.ArgumentParser(description="VNC keyboard operations")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Type command
    type_parser = subparsers.add_parser("type", help="Type a string of text")
    type_parser.add_argument("text", help="Text to type")

    # Key command
    key_parser = subparsers.add_parser("key", help="Press a key or key combination")
    key_parser.add_argument("key", help="Key or key combination (e.g., 'Return', 'ctrl+c', 'alt+F4')")
    key_parser.add_argument("--hold", action="store_true",
                            help="Hold the key down (don't release)")
    key_parser.add_argument("--release", action="store_true",
                            help="Release a held key")

    args = parser.parse_args()

    # Check if connected
    session = get_session()
    if not session or not session.connected:
        print(json.dumps({
            "status": "error",
            "error": "Not connected to VNC server. Run vnc_connect.py first."
        }))
        return 1

    # Execute action
    if args.action == "type":
        result = send_command({
            "command": "type",
            "text": args.text,
        })

    elif args.action == "key":
        keys = parse_key_combo(args.key)

        if len(keys) == 1 and not args.hold and not args.release:
            # Single key press and release
            result = send_command({
                "command": "key",
                "key": keys[0],
            })
        elif len(keys) == 1 and (args.hold or args.release):
            # Hold or release single key
            result = send_command({
                "command": "key",
                "key": keys[0],
                "down": args.hold,  # True for hold, False for release
            })
        else:
            # Key combination (e.g., ctrl+c)
            result = send_command({
                "command": "key_combo",
                "keys": keys,
            })

    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
