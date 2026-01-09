#!/usr/bin/env python3
"""
VNC Client Module for Claude Code VNC Skill

This module provides a VNC client daemon that maintains a persistent connection
to a VNC server and accepts commands via a Unix socket.
"""

import asyncio
import json
import os
import signal
import socket
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Tuple
import hashlib

# State file and socket paths
STATE_DIR = Path(tempfile.gettempdir()) / "vnc_skill"
STATE_FILE = STATE_DIR / "session.json"
SOCKET_PATH = STATE_DIR / "vnc.sock"
PID_FILE = STATE_DIR / "daemon.pid"
SCREENSHOT_DIR = STATE_DIR / "screenshots"


@dataclass
class VNCSession:
    """Represents a VNC session state"""
    host: str
    port: int
    connected: bool
    pid: int
    width: int = 0
    height: int = 0
    started_at: float = 0.0
    last_activity: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> 'VNCSession':
        return cls(**json.loads(data))


class RFBClient:
    """
    RFB (Remote Framebuffer) Protocol Client
    Implements VNC protocol for screen capture and input
    """

    # RFB Protocol Constants
    RFB_VERSION = b"RFB 003.008\n"

    # Security types
    SEC_INVALID = 0
    SEC_NONE = 1
    SEC_VNC_AUTH = 2

    # Message types - client to server
    MSG_SET_PIXEL_FORMAT = 0
    MSG_SET_ENCODINGS = 2
    MSG_FRAMEBUFFER_UPDATE_REQUEST = 3
    MSG_KEY_EVENT = 4
    MSG_POINTER_EVENT = 5
    MSG_CLIENT_CUT_TEXT = 6

    # Message types - server to client
    MSG_FRAMEBUFFER_UPDATE = 0
    MSG_SET_COLOUR_MAP_ENTRIES = 1
    MSG_BELL = 2
    MSG_SERVER_CUT_TEXT = 3

    # Encoding types
    ENC_RAW = 0
    ENC_COPYRECT = 1
    ENC_RRE = 2
    ENC_HEXTILE = 5
    ENC_ZRLE = 16
    ENC_CURSOR = -239
    ENC_DESKTOP_SIZE = -223

    def __init__(self, host: str, port: int, password: Optional[str] = None):
        self.host = host
        self.port = port
        self.password = password
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.width = 0
        self.height = 0
        self.pixel_format = None
        self.framebuffer = None
        self.name = ""
        self._connected = False
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connected and self.writer is not None

    async def connect(self) -> bool:
        """Establish connection to VNC server"""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=10.0
            )

            # Protocol version handshake
            server_version = await self.reader.read(12)
            if not server_version.startswith(b"RFB "):
                raise ConnectionError(f"Invalid RFB version: {server_version}")

            self.writer.write(self.RFB_VERSION)
            await self.writer.drain()

            # Security handshake
            if not await self._handle_security():
                raise ConnectionError("Security handshake failed")

            # ClientInit - shared flag
            self.writer.write(struct.pack("!B", 1))  # shared = True
            await self.writer.drain()

            # ServerInit
            await self._handle_server_init()

            # Set preferred pixel format (32-bit RGBA)
            await self._set_pixel_format()

            # Set encodings
            await self._set_encodings()

            self._connected = True
            return True

        except Exception as e:
            print(f"Connection error: {e}", file=sys.stderr)
            await self.disconnect()
            return False

    async def _handle_security(self) -> bool:
        """Handle VNC security negotiation"""
        # Read number of security types
        num_types = struct.unpack("!B", await self.reader.read(1))[0]

        if num_types == 0:
            # Read error message
            msg_len = struct.unpack("!I", await self.reader.read(4))[0]
            error_msg = (await self.reader.read(msg_len)).decode('utf-8')
            raise ConnectionError(f"Server error: {error_msg}")

        security_types = list(await self.reader.read(num_types))

        # Prefer no authentication, fall back to VNC auth
        if self.SEC_NONE in security_types:
            self.writer.write(struct.pack("!B", self.SEC_NONE))
            await self.writer.drain()
        elif self.SEC_VNC_AUTH in security_types and self.password:
            self.writer.write(struct.pack("!B", self.SEC_VNC_AUTH))
            await self.writer.drain()
            if not await self._vnc_auth():
                return False
        else:
            raise ConnectionError(f"No supported security type. Available: {security_types}")

        # Read security result
        result = struct.unpack("!I", await self.reader.read(4))[0]
        if result != 0:
            # Try to read error message (RFB 3.8+)
            try:
                msg_len = struct.unpack("!I", await self.reader.read(4))[0]
                error_msg = (await self.reader.read(msg_len)).decode('utf-8')
                raise ConnectionError(f"Authentication failed: {error_msg}")
            except:
                raise ConnectionError("Authentication failed")

        return True

    async def _vnc_auth(self) -> bool:
        """Handle VNC authentication (DES challenge-response)"""
        challenge = await self.reader.read(16)

        # VNC uses a modified DES where each byte is bit-reversed
        key = (self.password or "").ljust(8, '\x00')[:8].encode('latin-1')

        # Bit-reverse each byte of the key
        def reverse_bits(b):
            result = 0
            for i in range(8):
                if b & (1 << i):
                    result |= 1 << (7 - i)
            return result

        reversed_key = bytes(reverse_bits(b) for b in key)

        # Use DES to encrypt the challenge
        try:
            from Crypto.Cipher import DES
            cipher = DES.new(reversed_key, DES.MODE_ECB)
            response = cipher.encrypt(challenge[:8]) + cipher.encrypt(challenge[8:16])
        except ImportError:
            # Fallback: try pyDes
            try:
                import pyDes
                cipher = pyDes.des(reversed_key, pyDes.ECB)
                response = cipher.encrypt(challenge)
            except ImportError:
                raise ImportError("No DES library available. Install pycryptodome or pyDes.")

        self.writer.write(response)
        await self.writer.drain()
        return True

    async def _handle_server_init(self):
        """Handle ServerInit message"""
        # Read framebuffer size
        data = await self.reader.read(4)
        self.width, self.height = struct.unpack("!HH", data)

        # Read pixel format (16 bytes)
        pixel_data = await self.reader.read(16)
        self.pixel_format = {
            'bits_per_pixel': pixel_data[0],
            'depth': pixel_data[1],
            'big_endian': pixel_data[2],
            'true_color': pixel_data[3],
            'red_max': struct.unpack("!H", pixel_data[4:6])[0],
            'green_max': struct.unpack("!H", pixel_data[6:8])[0],
            'blue_max': struct.unpack("!H", pixel_data[8:10])[0],
            'red_shift': pixel_data[10],
            'green_shift': pixel_data[11],
            'blue_shift': pixel_data[12],
        }

        # Read desktop name
        name_len = struct.unpack("!I", await self.reader.read(4))[0]
        self.name = (await self.reader.read(name_len)).decode('utf-8', errors='replace')

        # Initialize framebuffer
        self.framebuffer = bytearray(self.width * self.height * 4)

    async def _set_pixel_format(self):
        """Set pixel format to 32-bit BGRA"""
        msg = struct.pack("!B3x", self.MSG_SET_PIXEL_FORMAT)
        # Pixel format: 32bpp, 24 depth, little-endian, true-color
        # BGRA format for easy PNG conversion
        pixel_format = struct.pack(
            "!BBBB HHH BBB 3x",
            32,  # bits per pixel
            24,  # depth
            0,   # big-endian = false
            1,   # true-color = true
            255, # red-max
            255, # green-max
            255, # blue-max
            16,  # red-shift (for BGRA)
            8,   # green-shift
            0,   # blue-shift
        )
        self.writer.write(msg + pixel_format)
        await self.writer.drain()

        # Update our pixel format
        self.pixel_format = {
            'bits_per_pixel': 32,
            'depth': 24,
            'big_endian': False,
            'true_color': True,
            'red_max': 255,
            'green_max': 255,
            'blue_max': 255,
            'red_shift': 16,
            'green_shift': 8,
            'blue_shift': 0,
        }

    async def _set_encodings(self):
        """Set preferred encodings"""
        encodings = [
            self.ENC_RAW,
            self.ENC_COPYRECT,
            self.ENC_DESKTOP_SIZE,
        ]
        msg = struct.pack("!BxH", self.MSG_SET_ENCODINGS, len(encodings))
        for enc in encodings:
            msg += struct.pack("!i", enc)
        self.writer.write(msg)
        await self.writer.drain()

    async def request_framebuffer_update(self, incremental: bool = True) -> bool:
        """Request a framebuffer update from server"""
        if not self.connected:
            return False

        async with self._lock:
            msg = struct.pack(
                "!BBHHHH",
                self.MSG_FRAMEBUFFER_UPDATE_REQUEST,
                1 if incremental else 0,
                0, 0,  # x, y
                self.width, self.height
            )
            self.writer.write(msg)
            await self.writer.drain()
        return True

    async def read_framebuffer_update(self) -> bool:
        """Read and process a framebuffer update"""
        if not self.connected:
            return False

        try:
            async with self._lock:
                # Read message type
                msg_type = struct.unpack("!B", await asyncio.wait_for(
                    self.reader.read(1), timeout=5.0
                ))[0]

                if msg_type != self.MSG_FRAMEBUFFER_UPDATE:
                    # Handle other message types
                    await self._handle_server_message(msg_type)
                    return False

                # Read padding and number of rectangles
                await self.reader.read(1)  # padding
                num_rects = struct.unpack("!H", await self.reader.read(2))[0]

                for _ in range(num_rects):
                    # Read rectangle header
                    x, y, w, h, encoding = struct.unpack(
                        "!HHHHi",
                        await self.reader.read(12)
                    )

                    if encoding == self.ENC_RAW:
                        await self._read_raw_rect(x, y, w, h)
                    elif encoding == self.ENC_COPYRECT:
                        await self._read_copyrect(x, y, w, h)
                    elif encoding == self.ENC_DESKTOP_SIZE:
                        self.width = w
                        self.height = h
                        self.framebuffer = bytearray(w * h * 4)
                    else:
                        print(f"Unknown encoding: {encoding}", file=sys.stderr)

            return True
        except asyncio.TimeoutError:
            return False
        except Exception as e:
            print(f"Error reading framebuffer: {e}", file=sys.stderr)
            return False

    async def _read_raw_rect(self, x: int, y: int, w: int, h: int):
        """Read a raw encoded rectangle"""
        bytes_per_pixel = 4
        row_bytes = w * bytes_per_pixel

        for row in range(h):
            data = await self.reader.readexactly(row_bytes)
            offset = ((y + row) * self.width + x) * bytes_per_pixel
            if offset + row_bytes <= len(self.framebuffer):
                self.framebuffer[offset:offset + row_bytes] = data

    async def _read_copyrect(self, x: int, y: int, w: int, h: int):
        """Read a copyrect encoded rectangle"""
        src_x, src_y = struct.unpack("!HH", await self.reader.read(4))
        bytes_per_pixel = 4

        # Copy pixels from source to destination
        for row in range(h):
            src_offset = ((src_y + row) * self.width + src_x) * bytes_per_pixel
            dst_offset = ((y + row) * self.width + x) * bytes_per_pixel
            row_bytes = w * bytes_per_pixel
            if (src_offset + row_bytes <= len(self.framebuffer) and
                dst_offset + row_bytes <= len(self.framebuffer)):
                self.framebuffer[dst_offset:dst_offset + row_bytes] = \
                    self.framebuffer[src_offset:src_offset + row_bytes]

    async def _handle_server_message(self, msg_type: int):
        """Handle non-framebuffer server messages"""
        if msg_type == self.MSG_BELL:
            pass  # Bell notification
        elif msg_type == self.MSG_SERVER_CUT_TEXT:
            await self.reader.read(3)  # padding
            length = struct.unpack("!I", await self.reader.read(4))[0]
            await self.reader.read(length)  # discard text
        elif msg_type == self.MSG_SET_COLOUR_MAP_ENTRIES:
            await self.reader.read(1)  # padding
            first_color = struct.unpack("!H", await self.reader.read(2))[0]
            num_colors = struct.unpack("!H", await self.reader.read(2))[0]
            await self.reader.read(num_colors * 6)

    async def capture_screen(self) -> Optional[bytes]:
        """Capture current screen as PNG bytes"""
        if not self.connected:
            return None

        # Request full framebuffer update
        await self.request_framebuffer_update(incremental=False)

        # Wait for and process update
        if not await self.read_framebuffer_update():
            return None

        # Convert framebuffer to PNG
        return self._framebuffer_to_png()

    def _framebuffer_to_png(self) -> bytes:
        """Convert framebuffer to PNG format"""
        import zlib

        width, height = self.width, self.height

        def make_png():
            def crc32(data):
                return zlib.crc32(data) & 0xffffffff

            def chunk(chunk_type, data):
                length = struct.pack(">I", len(data))
                crc = struct.pack(">I", crc32(chunk_type + data))
                return length + chunk_type + data + crc

            # PNG signature
            signature = b'\x89PNG\r\n\x1a\n'

            # IHDR chunk
            ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
            ihdr = chunk(b'IHDR', ihdr_data)

            # IDAT chunk - image data
            raw_data = bytearray()
            for y in range(height):
                raw_data.append(0)  # filter type: none
                for x in range(width):
                    offset = (y * width + x) * 4
                    # BGRA to RGB
                    b = self.framebuffer[offset]
                    g = self.framebuffer[offset + 1]
                    r = self.framebuffer[offset + 2]
                    raw_data.extend([r, g, b])

            compressed = zlib.compress(bytes(raw_data), 9)
            idat = chunk(b'IDAT', compressed)

            # IEND chunk
            iend = chunk(b'IEND', b'')

            return signature + ihdr + idat + iend

        return make_png()

    async def send_key_event(self, key: int, down: bool) -> bool:
        """Send a key press/release event"""
        if not self.connected:
            print(f"[DEBUG] send_key_event: NOT CONNECTED (key=0x{key:04x}, down={down})", file=sys.stderr)
            return False

        try:
            async with self._lock:
                msg = struct.pack("!BBHI", self.MSG_KEY_EVENT, 1 if down else 0, 0, key)
                print(f"[DEBUG] send_key_event: key=0x{key:04x} ({chr(key) if 0x20 <= key <= 0x7e else 'special'}), down={down}, msg={msg.hex()}", file=sys.stderr)
                self.writer.write(msg)
                await self.writer.drain()
                print(f"[DEBUG] send_key_event: sent successfully", file=sys.stderr)
                return True
        except Exception as e:
            print(f"[DEBUG] send_key_event: ERROR - {e}", file=sys.stderr)
            return False

    async def send_pointer_event(self, x: int, y: int, buttons: int) -> bool:
        """Send a mouse pointer event"""
        if not self.connected:
            print(f"[DEBUG] send_pointer_event: NOT CONNECTED (x={x}, y={y}, buttons={buttons})", file=sys.stderr)
            return False

        try:
            async with self._lock:
                msg = struct.pack("!BBHH", self.MSG_POINTER_EVENT, buttons, x, y)
                print(f"[DEBUG] send_pointer_event: x={x}, y={y}, buttons={buttons}, msg={msg.hex()}", file=sys.stderr)
                self.writer.write(msg)
                await self.writer.drain()
                print(f"[DEBUG] send_pointer_event: sent successfully", file=sys.stderr)
                return True
        except Exception as e:
            print(f"[DEBUG] send_pointer_event: ERROR - {e}", file=sys.stderr)
            return False

    async def type_text(self, text: str):
        """Type a string of text"""
        print(f"[DEBUG] type_text: typing '{text}' ({len(text)} chars)", file=sys.stderr)
        for i, char in enumerate(text):
            keysym = ord(char)
            # Handle special characters
            if keysym < 0x20 or keysym > 0x7e:
                keysym = self._char_to_keysym(char)

            print(f"[DEBUG] type_text: char[{i}]='{char}' (keysym=0x{keysym:04x})", file=sys.stderr)
            await self.send_key_event(keysym, True)
            await asyncio.sleep(0.02)
            await self.send_key_event(keysym, False)
            await asyncio.sleep(0.02)
        print(f"[DEBUG] type_text: done typing", file=sys.stderr)

    def _char_to_keysym(self, char: str) -> int:
        """Convert character to X11 keysym"""
        # Common special characters
        keysym_map = {
            '\n': 0xff0d,  # Return
            '\t': 0xff09,  # Tab
            '\r': 0xff0d,  # Return
            ' ': 0x20,     # Space
            '\b': 0xff08,  # BackSpace
            '\x1b': 0xff1b,  # Escape
        }
        return keysym_map.get(char, ord(char))

    async def click(self, x: int, y: int, button: int = 1):
        """Perform a mouse click"""
        button_mask = 1 << (button - 1)
        await self.send_pointer_event(x, y, button_mask)
        await asyncio.sleep(0.05)
        await self.send_pointer_event(x, y, 0)

    async def double_click(self, x: int, y: int, button: int = 1):
        """Perform a double click"""
        await self.click(x, y, button)
        await asyncio.sleep(0.1)
        await self.click(x, y, button)

    async def move_mouse(self, x: int, y: int):
        """Move mouse to position"""
        await self.send_pointer_event(x, y, 0)

    async def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: int = 1):
        """Perform a drag operation"""
        button_mask = 1 << (button - 1)

        # Move to start position
        await self.send_pointer_event(start_x, start_y, 0)
        await asyncio.sleep(0.05)

        # Press button
        await self.send_pointer_event(start_x, start_y, button_mask)
        await asyncio.sleep(0.05)

        # Move to end position with button held
        steps = max(abs(end_x - start_x), abs(end_y - start_y)) // 10 + 1
        for i in range(1, steps + 1):
            x = start_x + (end_x - start_x) * i // steps
            y = start_y + (end_y - start_y) * i // steps
            await self.send_pointer_event(x, y, button_mask)
            await asyncio.sleep(0.02)

        # Release button
        await self.send_pointer_event(end_x, end_y, 0)

    async def disconnect(self):
        """Close the VNC connection"""
        self._connected = False
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except:
                pass
        self.writer = None
        self.reader = None


class VNCDaemon:
    """
    Daemon process that maintains VNC connection and accepts commands
    via Unix socket
    """

    def __init__(self):
        self.client: Optional[RFBClient] = None
        self.running = False

    async def start(self, host: str, port: int, password: Optional[str] = None):
        """Start the daemon and connect to VNC server"""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        # Create VNC client and connect
        self.client = RFBClient(host, port, password)
        if not await self.client.connect():
            return False

        # Save session state
        session = VNCSession(
            host=host,
            port=port,
            connected=True,
            pid=os.getpid(),
            width=self.client.width,
            height=self.client.height,
            started_at=time.time(),
            last_activity=time.time(),
        )
        STATE_FILE.write_text(session.to_json())
        PID_FILE.write_text(str(os.getpid()))

        # Remove existing socket
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        # Start Unix socket server
        self.running = True
        server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(SOCKET_PATH)
        )

        # Set socket permissions
        os.chmod(SOCKET_PATH, 0o600)

        print(json.dumps({
            "status": "connected",
            "host": host,
            "port": port,
            "width": self.client.width,
            "height": self.client.height,
            "name": self.client.name,
            "pid": os.getpid(),
        }))

        # Handle signals
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        try:
            while self.running and self.client.connected:
                await asyncio.sleep(1)
                # Update last activity
                session.last_activity = time.time()
                session.connected = self.client.connected
                STATE_FILE.write_text(session.to_json())
        finally:
            server.close()
            await self.stop()

    async def stop(self):
        """Stop the daemon"""
        self.running = False
        if self.client:
            await self.client.disconnect()

        # Cleanup files
        for f in [STATE_FILE, PID_FILE, SOCKET_PATH]:
            if f.exists():
                try:
                    f.unlink()
                except:
                    pass

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming command from Unix socket client"""
        try:
            data = await reader.read(65536)
            if not data:
                return

            request = json.loads(data.decode('utf-8'))
            print(f"[DEBUG] _handle_client: received command: {request}", file=sys.stderr)
            print(f"[DEBUG] _handle_client: client.connected={self.client.connected if self.client else 'No client'}", file=sys.stderr)
            response = await self._process_command(request)
            print(f"[DEBUG] _handle_client: response: {response}", file=sys.stderr)

            writer.write(json.dumps(response).encode('utf-8'))
            await writer.drain()
        except Exception as e:
            print(f"[DEBUG] _handle_client: ERROR - {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            error_response = {"error": str(e)}
            writer.write(json.dumps(error_response).encode('utf-8'))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _process_command(self, request: dict) -> dict:
        """Process a command and return response"""
        cmd = request.get("command")

        if cmd == "screenshot":
            png_data = await self.client.capture_screen()
            if png_data:
                # Save to file
                filename = f"screenshot_{int(time.time() * 1000)}.png"
                filepath = SCREENSHOT_DIR / filename
                filepath.write_bytes(png_data)
                return {
                    "status": "ok",
                    "path": str(filepath),
                    "width": self.client.width,
                    "height": self.client.height,
                }
            return {"error": "Failed to capture screenshot"}

        elif cmd == "click":
            x, y = request["x"], request["y"]
            button = request.get("button", 1)
            await self.client.click(x, y, button)
            return {"status": "ok"}

        elif cmd == "double_click":
            x, y = request["x"], request["y"]
            button = request.get("button", 1)
            await self.client.double_click(x, y, button)
            return {"status": "ok"}

        elif cmd == "move":
            x, y = request["x"], request["y"]
            await self.client.move_mouse(x, y)
            return {"status": "ok"}

        elif cmd == "drag":
            await self.client.drag(
                request["start_x"], request["start_y"],
                request["end_x"], request["end_y"],
                request.get("button", 1)
            )
            return {"status": "ok"}

        elif cmd == "type":
            text = request["text"]
            await self.client.type_text(text)
            return {"status": "ok"}

        elif cmd == "key":
            key = request["key"]
            down = request.get("down", None)
            keysym = self._parse_key(key)

            if down is None:
                # Press and release
                await self.client.send_key_event(keysym, True)
                await asyncio.sleep(0.05)
                await self.client.send_key_event(keysym, False)
            else:
                await self.client.send_key_event(keysym, down)

            return {"status": "ok"}

        elif cmd == "key_combo":
            keys = request["keys"]
            keysyms = [self._parse_key(k) for k in keys]

            # Press all keys
            for keysym in keysyms:
                await self.client.send_key_event(keysym, True)
                await asyncio.sleep(0.02)

            # Release all keys in reverse order
            for keysym in reversed(keysyms):
                await self.client.send_key_event(keysym, False)
                await asyncio.sleep(0.02)

            return {"status": "ok"}

        elif cmd == "status":
            return {
                "status": "ok",
                "connected": self.client.connected,
                "host": self.client.host,
                "port": self.client.port,
                "width": self.client.width,
                "height": self.client.height,
                "name": self.client.name,
            }

        elif cmd == "disconnect":
            await self.stop()
            return {"status": "disconnected"}

        return {"error": f"Unknown command: {cmd}"}

    def _parse_key(self, key: str) -> int:
        """Parse key name to X11 keysym"""
        # Common key mappings
        key_map = {
            # Function keys
            "f1": 0xffbe, "f2": 0xffbf, "f3": 0xffc0, "f4": 0xffc1,
            "f5": 0xffc2, "f6": 0xffc3, "f7": 0xffc4, "f8": 0xffc5,
            "f9": 0xffc6, "f10": 0xffc7, "f11": 0xffc8, "f12": 0xffc9,

            # Modifier keys
            "shift": 0xffe1, "shift_l": 0xffe1, "shift_r": 0xffe2,
            "ctrl": 0xffe3, "ctrl_l": 0xffe3, "ctrl_r": 0xffe4,
            "control": 0xffe3, "control_l": 0xffe3, "control_r": 0xffe4,
            "alt": 0xffe9, "alt_l": 0xffe9, "alt_r": 0xffea,
            "meta": 0xffe7, "meta_l": 0xffe7, "meta_r": 0xffe8,
            "super": 0xffeb, "super_l": 0xffeb, "super_r": 0xffec,
            "win": 0xffeb, "cmd": 0xffe7, "command": 0xffe7,

            # Navigation keys
            "escape": 0xff1b, "esc": 0xff1b,
            "tab": 0xff09,
            "backspace": 0xff08, "back": 0xff08,
            "return": 0xff0d, "enter": 0xff0d,
            "insert": 0xff63, "ins": 0xff63,
            "delete": 0xffff, "del": 0xffff,
            "home": 0xff50,
            "end": 0xff57,
            "pageup": 0xff55, "page_up": 0xff55, "pgup": 0xff55,
            "pagedown": 0xff56, "page_down": 0xff56, "pgdn": 0xff56,

            # Arrow keys
            "left": 0xff51, "up": 0xff52, "right": 0xff53, "down": 0xff54,

            # Other
            "space": 0x20,
            "print": 0xff61, "printscreen": 0xff61,
            "scrolllock": 0xff14, "scroll_lock": 0xff14,
            "pause": 0xff13,
            "capslock": 0xffe5, "caps_lock": 0xffe5,
            "numlock": 0xff7f, "num_lock": 0xff7f,
        }

        key_lower = key.lower()
        if key_lower in key_map:
            return key_map[key_lower]

        # Single character
        if len(key) == 1:
            return ord(key)

        # Try to parse as hex keysym
        if key.startswith("0x"):
            return int(key, 16)

        raise ValueError(f"Unknown key: {key}")


def send_command(command: dict) -> dict:
    """Send a command to the VNC daemon via Unix socket"""
    if not SOCKET_PATH.exists():
        return {"error": "VNC daemon not running. Connect first."}

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(str(SOCKET_PATH))

        sock.sendall(json.dumps(command).encode('utf-8'))
        response = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response += chunk

        sock.close()
        return json.loads(response.decode('utf-8'))
    except FileNotFoundError:
        return {"error": "VNC daemon not running. Connect first."}
    except Exception as e:
        return {"error": str(e)}


def get_session() -> Optional[VNCSession]:
    """Get current session info"""
    if not STATE_FILE.exists():
        return None
    try:
        return VNCSession.from_json(STATE_FILE.read_text())
    except:
        return None


if __name__ == "__main__":
    # Can be run as daemon: python vnc_client.py daemon HOST PORT [PASSWORD]
    if len(sys.argv) >= 4 and sys.argv[1] == "daemon":
        host = sys.argv[2]
        port = int(sys.argv[3])
        password = sys.argv[4] if len(sys.argv) > 4 else None

        daemon = VNCDaemon()
        asyncio.run(daemon.start(host, port, password))
