#!/usr/bin/env python3
"""
VNC Session Monitor - Web-based viewer for monitoring VNC sessions

Starts a local web server that streams the VNC session to a browser canvas
via WebSocket. Restricted to localhost for security.

Usage:
    python vnc_monitor.py [--port 8080] [--fps 10]

Then open http://localhost:8080 in your browser.
"""

import argparse
import asyncio
import base64
import http.server
import json
import os
import signal
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Set

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from vnc_client import send_command, get_session

# HTML/JS client for the monitor
MONITOR_HTML = '''<!DOCTYPE html>
<html>
<head>
    <title>VNC Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #1a1a2e;
            color: #eee;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        h1 {
            margin-bottom: 10px;
            color: #0f9;
        }
        #status {
            margin-bottom: 15px;
            padding: 8px 16px;
            border-radius: 4px;
            font-size: 14px;
        }
        #status.connected { background: #0a3; }
        #status.disconnected { background: #a30; }
        #status.connecting { background: #a50; }
        #canvas-container {
            border: 2px solid #333;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        }
        #vnc-canvas {
            display: block;
            background: #000;
        }
        #stats {
            margin-top: 15px;
            font-size: 12px;
            color: #888;
        }
        #controls {
            margin-top: 15px;
            display: flex;
            gap: 10px;
        }
        button {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            background: #333;
            color: #fff;
            cursor: pointer;
            font-size: 14px;
        }
        button:hover { background: #444; }
        button:active { background: #555; }
        #info {
            margin-top: 20px;
            padding: 15px;
            background: #222;
            border-radius: 8px;
            font-size: 13px;
            max-width: 600px;
        }
        #info code {
            background: #333;
            padding: 2px 6px;
            border-radius: 3px;
        }
    </style>
</head>
<body>
    <h1>VNC Session Monitor</h1>
    <div id="status" class="connecting">Connecting...</div>
    <div id="canvas-container">
        <canvas id="vnc-canvas" width="800" height="600"></canvas>
    </div>
    <div id="stats">
        <span id="resolution">--</span> |
        <span id="fps">-- FPS</span> |
        <span id="bandwidth">-- KB/s</span>
    </div>
    <div id="controls">
        <button onclick="togglePause()">⏸ Pause</button>
        <button onclick="takeSnapshot()">📷 Snapshot</button>
        <button onclick="toggleFullscreen()">⛶ Fullscreen</button>
    </div>
    <div id="info">
        <p>This is a <strong>read-only</strong> monitor for the VNC session.</p>
        <p>The actual VNC interaction is done via Claude Code scripts.</p>
        <p style="margin-top:10px; color:#666;">
            Tip: Open browser DevTools (F12) to see frame timing details.
        </p>
    </div>

    <script>
        const canvas = document.getElementById('vnc-canvas');
        const ctx = canvas.getContext('2d');
        const statusEl = document.getElementById('status');
        const resolutionEl = document.getElementById('resolution');
        const fpsEl = document.getElementById('fps');
        const bandwidthEl = document.getElementById('bandwidth');

        let ws = null;
        let paused = false;
        let frameCount = 0;
        let bytesReceived = 0;
        let lastStatsTime = Date.now();

        function connect() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${location.host}/ws`);

            ws.onopen = () => {
                statusEl.textContent = 'Connected';
                statusEl.className = 'connected';
                console.log('WebSocket connected');
            };

            ws.onclose = () => {
                statusEl.textContent = 'Disconnected - Reconnecting...';
                statusEl.className = 'disconnected';
                console.log('WebSocket closed, reconnecting in 2s...');
                setTimeout(connect, 2000);
            };

            ws.onerror = (err) => {
                console.error('WebSocket error:', err);
            };

            ws.onmessage = (event) => {
                if (paused) return;

                const data = JSON.parse(event.data);

                if (data.type === 'frame') {
                    // Update canvas size if needed
                    if (canvas.width !== data.width || canvas.height !== data.height) {
                        canvas.width = data.width;
                        canvas.height = data.height;
                        resolutionEl.textContent = `${data.width}x${data.height}`;
                    }

                    // Draw the frame
                    const img = new Image();
                    img.onload = () => {
                        ctx.drawImage(img, 0, 0);
                        frameCount++;
                    };
                    img.src = 'data:image/png;base64,' + data.image;

                    bytesReceived += data.image.length * 0.75; // Approximate decoded size

                } else if (data.type === 'status') {
                    if (data.connected) {
                        resolutionEl.textContent = `${data.width}x${data.height}`;
                    } else {
                        statusEl.textContent = 'VNC Not Connected';
                        statusEl.className = 'disconnected';
                    }
                } else if (data.type === 'error') {
                    console.error('Server error:', data.message);
                    statusEl.textContent = 'Error: ' + data.message;
                    statusEl.className = 'disconnected';
                }
            };
        }

        // Update stats every second
        setInterval(() => {
            const now = Date.now();
            const elapsed = (now - lastStatsTime) / 1000;

            const fps = (frameCount / elapsed).toFixed(1);
            const kbps = ((bytesReceived / 1024) / elapsed).toFixed(1);

            fpsEl.textContent = `${fps} FPS`;
            bandwidthEl.textContent = `${kbps} KB/s`;

            frameCount = 0;
            bytesReceived = 0;
            lastStatsTime = now;
        }, 1000);

        function togglePause() {
            paused = !paused;
            event.target.textContent = paused ? '▶ Resume' : '⏸ Pause';
        }

        function takeSnapshot() {
            const link = document.createElement('a');
            link.download = `vnc-snapshot-${Date.now()}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
        }

        function toggleFullscreen() {
            if (!document.fullscreenElement) {
                canvas.requestFullscreen();
            } else {
                document.exitFullscreen();
            }
        }

        // Start connection
        connect();
    </script>
</body>
</html>
'''


class WebSocketServer:
    """Simple WebSocket server implementation (RFC 6455)"""

    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, host: str, port: int, fps: float = 10):
        self.host = host
        self.port = port
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.clients: Set[asyncio.StreamWriter] = set()
        self.running = False
        self._http_server = None
        self._http_thread = None

    async def start(self):
        """Start the WebSocket server"""
        self.running = True

        # Start HTTP server for serving the HTML page
        self._start_http_server()

        # Start WebSocket server
        server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port + 1,  # WebSocket on port+1
        )

        print(f"VNC Monitor started!")
        print(f"  Web UI: http://{self.host}:{self.port}")
        print(f"  WebSocket: ws://{self.host}:{self.port + 1}/ws")
        print(f"  Frame rate: {self.fps} FPS")
        print(f"\nOpen http://localhost:{self.port} in your browser to view the VNC session.")

        # Start frame streaming task
        asyncio.create_task(self._stream_frames())

        async with server:
            await server.serve_forever()

    def _start_http_server(self):
        """Start HTTP server in a separate thread"""

        class MonitorHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress logging

            def do_GET(self):
                if self.path == '/' or self.path == '/index.html':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.end_headers()
                    # Inject the correct WebSocket port
                    html = MONITOR_HTML.replace(
                        "location.host",
                        f"'{self.server.server_address[0]}:{self.server.server_address[1] + 1}'"
                    )
                    self.wfile.write(html.encode())
                else:
                    self.send_error(404)

        class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            allow_reuse_address = True

        self._http_server = ThreadedHTTPServer((self.host, self.port), MonitorHandler)
        self._http_thread = threading.Thread(target=self._http_server.serve_forever)
        self._http_thread.daemon = True
        self._http_thread.start()

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming WebSocket connection"""
        try:
            # Read HTTP request
            request_line = await reader.readline()
            headers = {}

            while True:
                line = await reader.readline()
                if line == b'\r\n':
                    break
                if b':' in line:
                    key, value = line.decode().split(':', 1)
                    headers[key.strip().lower()] = value.strip()

            # Verify WebSocket upgrade request
            if headers.get('upgrade', '').lower() != 'websocket':
                writer.close()
                return

            # Perform WebSocket handshake
            key = headers.get('sec-websocket-key', '')
            accept = self._compute_accept_key(key)

            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            )
            writer.write(response.encode())
            await writer.drain()

            # Add to clients
            self.clients.add(writer)

            # Send initial status
            session = get_session()
            if session:
                await self._send_json(writer, {
                    "type": "status",
                    "connected": session.connected,
                    "width": session.width,
                    "height": session.height,
                })

            # Keep connection alive and handle incoming messages
            try:
                while self.running:
                    # Read frames (for ping/pong handling)
                    try:
                        data = await asyncio.wait_for(reader.read(1024), timeout=30)
                        if not data:
                            break
                        # Handle ping frames, close frames, etc.
                        if len(data) >= 2:
                            opcode = data[0] & 0x0F
                            if opcode == 0x8:  # Close
                                break
                            elif opcode == 0x9:  # Ping
                                await self._send_pong(writer, data)
                    except asyncio.TimeoutError:
                        # Send ping to keep alive
                        await self._send_ping(writer)

            except (ConnectionResetError, BrokenPipeError):
                pass
            finally:
                self.clients.discard(writer)
                writer.close()

        except Exception as e:
            print(f"Connection error: {e}")
            self.clients.discard(writer)

    def _compute_accept_key(self, key: str) -> str:
        """Compute Sec-WebSocket-Accept header value"""
        import hashlib
        import base64
        combined = key + self.GUID
        sha1 = hashlib.sha1(combined.encode()).digest()
        return base64.b64encode(sha1).decode()

    async def _send_json(self, writer: asyncio.StreamWriter, data: dict):
        """Send JSON data as WebSocket text frame"""
        payload = json.dumps(data).encode()
        await self._send_frame(writer, payload, opcode=0x1)

    async def _send_frame(self, writer: asyncio.StreamWriter, payload: bytes, opcode: int = 0x1):
        """Send a WebSocket frame"""
        length = len(payload)

        # Build frame header
        frame = bytearray()
        frame.append(0x80 | opcode)  # FIN + opcode

        if length < 126:
            frame.append(length)
        elif length < 65536:
            frame.append(126)
            frame.extend(length.to_bytes(2, 'big'))
        else:
            frame.append(127)
            frame.extend(length.to_bytes(8, 'big'))

        frame.extend(payload)

        try:
            writer.write(bytes(frame))
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            self.clients.discard(writer)

    async def _send_ping(self, writer: asyncio.StreamWriter):
        """Send WebSocket ping frame"""
        await self._send_frame(writer, b'ping', opcode=0x9)

    async def _send_pong(self, writer: asyncio.StreamWriter, ping_frame: bytes):
        """Send WebSocket pong frame"""
        # Extract payload from ping and send as pong
        await self._send_frame(writer, b'pong', opcode=0xA)

    async def _stream_frames(self):
        """Continuously capture and stream frames to all clients"""
        while self.running:
            start_time = time.time()

            if self.clients:
                # Check if VNC is connected
                session = get_session()
                if not session or not session.connected:
                    # Send disconnected status
                    for client in list(self.clients):
                        try:
                            await self._send_json(client, {
                                "type": "status",
                                "connected": False,
                            })
                        except:
                            self.clients.discard(client)
                else:
                    # Capture screenshot
                    result = send_command({"command": "screenshot"})

                    if "error" not in result and "path" in result:
                        # Read the screenshot file
                        try:
                            screenshot_path = Path(result["path"])
                            if screenshot_path.exists():
                                image_data = screenshot_path.read_bytes()
                                image_b64 = base64.b64encode(image_data).decode()

                                # Send to all clients
                                frame_data = {
                                    "type": "frame",
                                    "width": result.get("width", 800),
                                    "height": result.get("height", 600),
                                    "image": image_b64,
                                }

                                for client in list(self.clients):
                                    try:
                                        await self._send_json(client, frame_data)
                                    except:
                                        self.clients.discard(client)

                                # Clean up screenshot file
                                try:
                                    screenshot_path.unlink()
                                except:
                                    pass
                        except Exception as e:
                            print(f"Error reading screenshot: {e}")

            # Wait for next frame interval
            elapsed = time.time() - start_time
            sleep_time = max(0, self.frame_interval - elapsed)
            await asyncio.sleep(sleep_time)

    def stop(self):
        """Stop the server"""
        self.running = False
        if self._http_server:
            self._http_server.shutdown()


async def main():
    parser = argparse.ArgumentParser(description="VNC Session Monitor")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind to (default: 127.0.0.1 for localhost only)")
    parser.add_argument("--port", "-p", type=int, default=8080,
                        help="Port for web UI (WebSocket will be port+1)")
    parser.add_argument("--fps", "-f", type=float, default=10,
                        help="Target frame rate (default: 10)")

    args = parser.parse_args()

    # Check if VNC is connected
    session = get_session()
    if not session:
        print(json.dumps({
            "status": "warning",
            "message": "No VNC session active. Monitor will wait for connection.",
            "url": f"http://{args.host}:{args.port}"
        }))
    else:
        print(json.dumps({
            "status": "ok",
            "message": "Starting VNC monitor",
            "vnc_host": session.host,
            "vnc_port": session.port,
            "url": f"http://{args.host}:{args.port}"
        }))

    server = WebSocketServer(args.host, args.port, args.fps)

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, server.stop)

    try:
        await server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
