#!/usr/bin/env python3
"""
Capture a screenshot from the VNC server

Usage: python vnc_screenshot.py [--output FILE]

Returns the path to the captured screenshot image.
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from vnc_client import send_command, get_session


def main():
    parser = argparse.ArgumentParser(description="Capture a VNC screenshot")
    parser.add_argument("--output", "-o", help="Output file path (default: auto-generated)")

    args = parser.parse_args()

    # Check if connected
    session = get_session()
    if not session or not session.connected:
        print(json.dumps({
            "status": "error",
            "error": "Not connected to VNC server. Run vnc_connect.py first."
        }))
        return 1

    # Request screenshot
    result = send_command({"command": "screenshot"})

    if "error" in result:
        print(json.dumps(result))
        return 1

    # Copy to specified output if provided
    if args.output:
        import shutil
        src_path = Path(result["path"])
        dst_path = Path(args.output)
        shutil.copy(src_path, dst_path)
        result["path"] = str(dst_path.absolute())

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
