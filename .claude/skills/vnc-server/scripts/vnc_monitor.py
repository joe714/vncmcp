#!/usr/bin/env python3
"""
VNC Session Monitor - Web-based viewer for monitoring VNC sessions

Starts a local web server that streams the VNC session to a browser canvas
via WebSocket. Both HTTP and WebSocket are served on the same port.

Usage:
    python vnc_monitor.py [--port 8080] [--fps 10]

Then open http://localhost:8080 in your browser.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import signal
import sys
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
            padding: 10px;
        }
        h1 {
            margin-bottom: 5px;
            color: #0f9;
            font-size: 1.2em;
        }
        #status {
            margin-bottom: 8px;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 12px;
        }
        #status.connected { background: #0a3; }
        #status.disconnected { background: #a30; }
        #status.connecting { background: #a50; }
        #canvas-container {
            border: 2px solid #333;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
            max-width: 100%;
            max-height: calc(100vh - 120px);
            display: flex;
            align-items: center;
            justify-content: center;
        }
        #vnc-canvas {
            display: block;
            background: #000;
            max-width: 100%;
            max-height: calc(100vh - 120px);
            object-fit: contain;
        }
        #stats {
            margin-top: 8px;
            font-size: 11px;
            color: #888;
        }
        #controls {
            margin-top: 8px;
            display: flex;
            gap: 8px;
        }
        button {
            padding: 6px 12px;
            border: none;
            border-radius: 4px;
            background: #333;
            color: #fff;
            cursor: pointer;
            font-size: 12px;
        }
        button:hover { background: #444; }
        button:active { background: #555; }
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
        <button onclick="togglePause()">Pause</button>
        <button onclick="takeSnapshot()">Snapshot</button>
        <button onclick="toggleFullscreen()">Fullscreen</button>
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
        let nativeWidth = 800;
        let nativeHeight = 600;

        function scaleCanvas() {
            const maxW = window.innerWidth - 24;
            const maxH = window.innerHeight - 120;
            const aspect = nativeWidth / nativeHeight;

            let w = maxW;
            let h = w / aspect;

            if (h > maxH) {
                h = maxH;
                w = h * aspect;
            }

            canvas.style.width = Math.floor(w) + 'px';
            canvas.style.height = Math.floor(h) + 'px';
        }

        window.addEventListener('resize', scaleCanvas);

        function connect() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${location.host}/ws`);

            ws.onopen = () => {
                statusEl.textContent = 'Connected';
                statusEl.className = 'connected';
            };

            ws.onclose = () => {
                statusEl.textContent = 'Disconnected - Reconnecting...';
                statusEl.className = 'disconnected';
                setTimeout(connect, 2000);
            };

            ws.onerror = (err) => {
                console.error('WebSocket error:', err);
            };

            ws.onmessage = (event) => {
                if (paused) return;

                const data = JSON.parse(event.data);

                if (data.type === 'frame') {
                    if (canvas.width !== data.width || canvas.height !== data.height) {
                        canvas.width = data.width;
                        canvas.height = data.height;
                        nativeWidth = data.width;
                        nativeHeight = data.height;
                        resolutionEl.textContent = `${data.width}x${data.height}`;
                        scaleCanvas();
                    }

                    const img = new Image();
                    img.onload = () => {
                        ctx.drawImage(img, 0, 0);
                        frameCount++;
                    };
                    img.src = 'data:image/png;base64,' + data.image;
                    bytesReceived += data.image.length * 0.75;

                } else if (data.type === 'status') {
                    if (data.connected) {
                        resolutionEl.textContent = `${data.width}x${data.height}`;
                    } else {
                        statusEl.textContent = 'VNC Not Connected';
                        statusEl.className = 'disconnected';
                    }
                } else if (data.type === 'error') {
                    statusEl.textContent = 'Error: ' + data.message;
                    statusEl.className = 'disconnected';
                }
            };
        }

        setInterval(() => {
            const now = Date.now();
            const elapsed = (now - lastStatsTime) / 1000;
            fpsEl.textContent = `${(frameCount / elapsed).toFixed(1)} FPS`;
            bandwidthEl.textContent = `${((bytesReceived / 1024) / elapsed).toFixed(0)} KB/s`;
            frameCount = 0;
            bytesReceived = 0;
            lastStatsTime = now;
        }, 1000);

        function togglePause() {
            paused = !paused;
            event.target.textContent = paused ? 'Resume' : 'Pause';
        }

        function takeSnapshot() {
            const link = document.createElement('a');
            link.download = `vnc-snapshot-${Date.now()}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
        }

        function toggleFullscreen() {
            if (!document.fullscreenElement) {
                document.getElementById('canvas-container').requestFullscreen();
            } else {
                document.exitFullscreen();
            }
        }

        connect();
        scaleCanvas();
    </script>
</body>
</html>
'''

# Simple HTTP response for the HTML page
HTTP_RESPONSE_TEMPLATE = """HTTP/1.1 200 OK\r
Content-Type: text/html; charset=utf-8\r
Content-Length: {length}\r
Connection: close\r
\r
"""

HTTP_404 = """HTTP/1.1 404 Not Found\r
Content-Type: text/plain\r
Content-Length: 9\r
Connection: close\r
\r
Not Found"""


class VNCMonitorServer:
    """Combined HTTP + WebSocket server on a single port"""

    WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, host: str, port: int, fps: float = 10):
        self.host = host
        self.port = port
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.ws_clients: Set[asyncio.StreamWriter] = set()
        self.running = False

    async def start(self):
        """Start the server"""
        self.running = True

        server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
        )

        print(f"VNC Monitor started!")
        print(f"  URL: http://{self.host}:{self.port}")
        print(f"  Frame rate: {self.fps} FPS")
        print(f"\nOpen http://localhost:{self.port} in your browser to view the VNC session.")

        # Start frame streaming task
        asyncio.create_task(self._stream_frames())

        async with server:
            await server.serve_forever()

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming connection - route to HTTP or WebSocket"""
        try:
            # Read the first line to determine request type
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not request_line:
                writer.close()
                return

            request_line = request_line.decode('utf-8', errors='ignore').strip()
            parts = request_line.split()
            if len(parts) < 2:
                writer.close()
                return

            method, path = parts[0], parts[1]

            # Read headers
            headers = {}
            while True:
                line = await reader.readline()
                if line == b'\r\n' or line == b'\n' or not line:
                    break
                if b':' in line:
                    key, value = line.decode('utf-8', errors='ignore').split(':', 1)
                    headers[key.strip().lower()] = value.strip()

            # Check if this is a WebSocket upgrade request
            if headers.get('upgrade', '').lower() == 'websocket' and path == '/ws':
                await self._handle_websocket(reader, writer, headers)
            else:
                await self._handle_http(writer, method, path)

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"Connection error: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass

    async def _handle_http(self, writer: asyncio.StreamWriter, method: str, path: str):
        """Handle HTTP request - serve the HTML page"""
        if method == 'GET' and path in ('/', '/index.html'):
            html_bytes = MONITOR_HTML.encode('utf-8')
            response = HTTP_RESPONSE_TEMPLATE.format(length=len(html_bytes))
            writer.write(response.encode('utf-8'))
            writer.write(html_bytes)
        else:
            writer.write(HTTP_404.encode('utf-8'))

        await writer.drain()

    async def _handle_websocket(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, headers: dict):
        """Handle WebSocket connection"""
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
        self.ws_clients.add(writer)

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
                try:
                    data = await asyncio.wait_for(reader.read(1024), timeout=30)
                    if not data:
                        break
                    # Handle WebSocket control frames
                    if len(data) >= 2:
                        opcode = data[0] & 0x0F
                        if opcode == 0x8:  # Close
                            break
                        elif opcode == 0x9:  # Ping
                            await self._send_pong(writer)
                except asyncio.TimeoutError:
                    # Send ping to keep alive
                    try:
                        await self._send_ping(writer)
                    except:
                        break

        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self.ws_clients.discard(writer)

    def _compute_accept_key(self, key: str) -> str:
        """Compute Sec-WebSocket-Accept header value"""
        combined = key + self.WEBSOCKET_GUID
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
            self.ws_clients.discard(writer)

    async def _send_ping(self, writer: asyncio.StreamWriter):
        """Send WebSocket ping frame"""
        await self._send_frame(writer, b'ping', opcode=0x9)

    async def _send_pong(self, writer: asyncio.StreamWriter):
        """Send WebSocket pong frame"""
        await self._send_frame(writer, b'pong', opcode=0xA)

    async def _stream_frames(self):
        """Continuously capture and stream frames to all clients"""
        while self.running:
            start_time = time.time()

            if self.ws_clients:
                # Check if VNC is connected
                session = get_session()
                if not session or not session.connected:
                    # Send disconnected status
                    for client in list(self.ws_clients):
                        try:
                            await self._send_json(client, {
                                "type": "status",
                                "connected": False,
                            })
                        except:
                            self.ws_clients.discard(client)
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

                                for client in list(self.ws_clients):
                                    try:
                                        await self._send_json(client, frame_data)
                                    except:
                                        self.ws_clients.discard(client)

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


async def main():
    parser = argparse.ArgumentParser(description="VNC Session Monitor")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind to (default: 127.0.0.1 for localhost only)")
    parser.add_argument("--port", "-p", type=int, default=8080,
                        help="Port for web UI and WebSocket")
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

    server = VNCMonitorServer(args.host, args.port, args.fps)

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
