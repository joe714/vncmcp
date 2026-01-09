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

### 6. Monitor Session in Browser (Optional)

Start a web-based monitor to view the VNC session in real-time:

```bash
python .claude/skills/vnc-server/scripts/vnc_monitor.py
```

Then open http://localhost:8080 in your browser to watch the session.

Options:
- `--port 8080` - Web UI and WebSocket port (single port for SSH tunneling)
- `--fps 10` - Target frame rate (default: 10)
- `--host 127.0.0.1` - Bind address (localhost only by default for security)

The monitor is **read-only** - it shows the screen but doesn't capture input. All interaction is done via the Claude Code scripts.

### 7. Disconnect

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

## Calculating Coordinates

**Important:** The screenshot response includes the actual framebuffer dimensions (e.g., `"width": 1920, "height": 1080`). You must use coordinates based on these actual dimensions, NOT the scaled image dimensions you see when viewing screenshots.

### Coordinate Calculation

1. Take a screenshot and note the dimensions from the response:
   ```json
   {"status": "ok", "width": 1920, "height": 1080, ...}
   ```

2. When viewing the screenshot image, it may be displayed at a smaller scale. Calculate coordinates relative to the **actual** dimensions returned in the response.

3. Estimate target position as a percentage of the screen, then multiply by actual dimensions:
   - If a button appears at roughly 50% from left and 40% from top:
   - x = 0.50 × 1920 = 960
   - y = 0.40 × 1080 = 432

### Common Coordinate References (for 1920x1080 screen)

| Location | Coordinates |
|----------|-------------|
| Top-left corner | (0, 0) |
| Top-center | (960, 0) |
| Screen center | (960, 540) |
| Bottom-right corner | (1920, 1080) |
| Typical taskbar (bottom) | (960, 1050) |

### Tips for Accuracy

1. **Start with obvious landmarks** - Desktop icons, taskbars, and window title bars have predictable positions
2. **Take screenshots after each action** - Verify your click landed where expected
3. **Click center of targets** - Aim for the middle of buttons and text fields
4. **Account for window decorations** - Title bars, borders, and menus take up space
5. **Use focus before typing** - Always click on a text field before sending keyboard input

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

The optional web monitor (`vnc_monitor.py`) provides real-time viewing:
- Serves both HTTP and WebSocket on a single port (SSH tunnel friendly)
- Canvas auto-scales to fit browser viewport while maintaining aspect ratio
- Restricted to localhost (127.0.0.1) by default for security
- Read-only viewing - does not capture or forward mouse/keyboard input

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
