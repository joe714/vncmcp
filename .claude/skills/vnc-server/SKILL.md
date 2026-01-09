---
name: vnc-server
description: Connect to and interact with VNC remote desktop servers. Use this skill when you need to view remote screens, perform mouse clicks, type text, or automate GUI interactions on a VNC server.
allowed-tools: Bash, Read, Glob
---

# VNC Server Skill

This skill allows you to connect to VNC (Virtual Network Computing) servers and interact with remote desktops. You can view the screen, click on elements, type text, and perform complex mouse/keyboard operations.

## Prerequisites

Before using this skill, ensure:
1. Python 3.7+ is installed
2. The `pycryptodome` package is installed (for VNC authentication): `pip install pycryptodome`
3. You have VNC server connection details (host, port, and optionally password)

## Quick Start

### 1. Connect to a VNC Server

```bash
python .claude/skills/vnc-server/scripts/vnc_connect.py <host> <port> [--password <password>]
```

Example:
```bash
python .claude/skills/vnc-server/scripts/vnc_connect.py localhost 5900
python .claude/skills/vnc-server/scripts/vnc_connect.py 192.168.1.100 5901 --password mysecret
```

### 2. Take a Screenshot

```bash
python .claude/skills/vnc-server/scripts/vnc_screenshot.py
```

The screenshot is saved as a PNG file and the path is returned. Use the Read tool to view the screenshot image.

### 3. Perform Mouse Actions

```bash
# Single click at coordinates
python .claude/skills/vnc-server/scripts/vnc_mouse.py click <x> <y>

# Double-click
python .claude/skills/vnc-server/scripts/vnc_mouse.py double-click <x> <y>

# Right-click
python .claude/skills/vnc-server/scripts/vnc_mouse.py click <x> <y> --button 3

# Move mouse
python .claude/skills/vnc-server/scripts/vnc_mouse.py move <x> <y>

# Drag from one point to another
python .claude/skills/vnc-server/scripts/vnc_mouse.py drag <start_x> <start_y> <end_x> <end_y>

# Scroll
python .claude/skills/vnc-server/scripts/vnc_mouse.py scroll <x> <y> up --amount 5
```

### 4. Type Text and Send Keys

```bash
# Type text
python .claude/skills/vnc-server/scripts/vnc_keyboard.py type "Hello World"

# Press a single key
python .claude/skills/vnc-server/scripts/vnc_keyboard.py key Return
python .claude/skills/vnc-server/scripts/vnc_keyboard.py key Escape

# Key combinations
python .claude/skills/vnc-server/scripts/vnc_keyboard.py key ctrl+c
python .claude/skills/vnc-server/scripts/vnc_keyboard.py key ctrl+shift+s
python .claude/skills/vnc-server/scripts/vnc_keyboard.py key alt+F4
```

### 5. Check Connection Status

```bash
python .claude/skills/vnc-server/scripts/vnc_status.py
```

### 6. Disconnect

```bash
python .claude/skills/vnc-server/scripts/vnc_disconnect.py
```

## Supported Keys

**Modifiers:** ctrl, alt, shift, meta, super, win, cmd

**Function Keys:** f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12

**Navigation:** escape, tab, backspace, return/enter, insert, delete, home, end, pageup, pagedown, left, right, up, down

**Other:** space, print, scrolllock, pause, capslock, numlock

## Common Workflows

### Workflow: Explore a Remote Desktop

1. Connect to the VNC server
2. Take a screenshot to see the current state
3. Identify UI elements and their approximate coordinates
4. Click on elements or type text as needed
5. Take another screenshot to verify results

### Workflow: Automate a GUI Task

1. Connect to the VNC server
2. Take a screenshot to understand the initial state
3. Use mouse clicks to navigate to the target area
4. Type text or use keyboard shortcuts to perform actions
5. Take screenshots at each step to verify progress
6. Disconnect when done

### Workflow: Fill a Form

1. Connect and take a screenshot
2. Click on the first form field
3. Type the required text
4. Use Tab key to move to next field: `vnc_keyboard.py key Tab`
5. Repeat for all fields
6. Click submit button or press Enter

## Tips for Finding Coordinates

When you take a screenshot, the response includes the screen dimensions (width × height). To interact with UI elements:

1. Take a screenshot and view it using the Read tool
2. Estimate coordinates based on the visual layout
3. Most screens are laid out with (0,0) at the top-left corner
4. X increases to the right, Y increases downward

## Error Handling

All scripts return JSON responses:

**Success:**
```json
{
  "status": "ok",
  ...
}
```

**Error:**
```json
{
  "status": "error",
  "error": "Error description"
}
```

Common errors:
- "Not connected to VNC server" - Run vnc_connect.py first
- "Connection timed out" - Check host/port and network connectivity
- "Authentication failed" - Verify the password is correct

## Architecture

The skill uses a background daemon architecture:
- `vnc_connect.py` starts a daemon process that maintains the VNC connection
- The daemon listens on a Unix socket for commands
- Other scripts (`vnc_screenshot.py`, `vnc_mouse.py`, etc.) send commands to the daemon
- This allows the connection to persist between operations

State files are stored in `/tmp/vnc_skill/`:
- `session.json` - Current session information
- `daemon.pid` - Daemon process ID
- `vnc.sock` - Unix socket for IPC
- `screenshots/` - Captured screenshots

## Limitations

- Only one VNC connection at a time is supported
- The skill uses raw encoding which may be slower on high-latency connections
- Some advanced VNC features (like clipboard sync) are not implemented
- Coordinate-based clicking requires visual inspection of screenshots
