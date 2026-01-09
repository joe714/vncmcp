#!/usr/bin/env python3
"""
Perform mouse operations on the VNC server

Usage:
    python vnc_mouse.py click <x> <y> [--button 1|2|3]
    python vnc_mouse.py double-click <x> <y> [--button 1|2|3]
    python vnc_mouse.py move <x> <y>
    python vnc_mouse.py drag <start_x> <start_y> <end_x> <end_y> [--button 1|2|3]
    python vnc_mouse.py scroll <x> <y> <direction> [--amount N]

Mouse buttons: 1=left, 2=middle, 3=right
Scroll direction: up, down, left, right
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from vnc_client import send_command, get_session


def main():
    parser = argparse.ArgumentParser(description="VNC mouse operations")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Click command
    click_parser = subparsers.add_parser("click", help="Single click")
    click_parser.add_argument("x", type=int, help="X coordinate")
    click_parser.add_argument("y", type=int, help="Y coordinate")
    click_parser.add_argument("--button", "-b", type=int, default=1, choices=[1, 2, 3],
                              help="Mouse button (1=left, 2=middle, 3=right)")

    # Double-click command
    dbl_parser = subparsers.add_parser("double-click", help="Double click")
    dbl_parser.add_argument("x", type=int, help="X coordinate")
    dbl_parser.add_argument("y", type=int, help="Y coordinate")
    dbl_parser.add_argument("--button", "-b", type=int, default=1, choices=[1, 2, 3],
                            help="Mouse button")

    # Move command
    move_parser = subparsers.add_parser("move", help="Move mouse cursor")
    move_parser.add_argument("x", type=int, help="X coordinate")
    move_parser.add_argument("y", type=int, help="Y coordinate")

    # Drag command
    drag_parser = subparsers.add_parser("drag", help="Drag operation")
    drag_parser.add_argument("start_x", type=int, help="Start X coordinate")
    drag_parser.add_argument("start_y", type=int, help="Start Y coordinate")
    drag_parser.add_argument("end_x", type=int, help="End X coordinate")
    drag_parser.add_argument("end_y", type=int, help="End Y coordinate")
    drag_parser.add_argument("--button", "-b", type=int, default=1, choices=[1, 2, 3],
                             help="Mouse button")

    # Scroll command
    scroll_parser = subparsers.add_parser("scroll", help="Scroll wheel")
    scroll_parser.add_argument("x", type=int, help="X coordinate")
    scroll_parser.add_argument("y", type=int, help="Y coordinate")
    scroll_parser.add_argument("direction", choices=["up", "down", "left", "right"],
                               help="Scroll direction")
    scroll_parser.add_argument("--amount", "-a", type=int, default=3,
                               help="Number of scroll steps")

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
    if args.action == "click":
        result = send_command({
            "command": "click",
            "x": args.x,
            "y": args.y,
            "button": args.button,
        })

    elif args.action == "double-click":
        result = send_command({
            "command": "double_click",
            "x": args.x,
            "y": args.y,
            "button": args.button,
        })

    elif args.action == "move":
        result = send_command({
            "command": "move",
            "x": args.x,
            "y": args.y,
        })

    elif args.action == "drag":
        result = send_command({
            "command": "drag",
            "start_x": args.start_x,
            "start_y": args.start_y,
            "end_x": args.end_x,
            "end_y": args.end_y,
            "button": args.button,
        })

    elif args.action == "scroll":
        # Scroll is implemented via mouse button 4/5 (up/down) or 6/7 (left/right)
        scroll_buttons = {
            "up": 4,
            "down": 5,
            "left": 6,
            "right": 7,
        }
        button = scroll_buttons[args.direction]

        # Perform multiple scroll clicks
        for _ in range(args.amount):
            result = send_command({
                "command": "click",
                "x": args.x,
                "y": args.y,
                "button": button,
            })
            if "error" in result:
                break

    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
