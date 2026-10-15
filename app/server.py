"""Local HTTP server for the Charter console. Standard library
only, loopback only."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import socket
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import urlparse

from . import __version__
from . import api_changeset, console
from . import host_state as hs

# Every console action, the coordinated change sets' among them.
POST_ROUTES = dict(console.POST_ROUTES, **api_changeset.ROUTES)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 64 * 1024 * 1024  # 64 MB uploads

# The console page carries this per-launch token and sends it on every API
# request. With the Host allow-list below, it is what distinguishes the real
# console page from any other origin — including a page that has rebound a
# hostname to this loopback address.
TOKEN_HEADER = "X-Charter-Console-Token"
TOKEN_PLACEHOLDER = b"__CHARTER_CONSOLE_TOKEN__"
# A 500 never carries an exception name or a local path to the client; the
# detail is printed to the console window the person started.
INTERNAL_ERROR = ("Charter hit an unexpected problem. Check the console window "
                  "for details.")


def resolves_within(base: str, path: str) -> bool:
    """Whether `path`, with every link resolved, is `base` or lies inside it.

    Both sides are resolved and compared by path components, case-folded where
    the filesystem is, so a sibling such as `static-private` is not inside
    `static`. Another drive, a dangling link, a link loop or any other
    resolution failure answers False: what cannot be resolved is not inside.
    """
    try:
        if not os.path.exists(path):
            return False
        real_base = os.path.normcase(os.path.realpath(base))
        real = os.path.normcase(os.path.realpath(path))
        return os.path.commonpath([real_base, real]) == real_base
    except (OSError, ValueError):
        return False


def make_handler(session: console.Session, token: str = ""):

    class Handler(BaseHTTPRequestHandler):
        server_version = f"Charter/{__version__}"
        protocol_version = "HTTP/1.1"

        # -- plumbing ---------------------------------------------------
        def log_message(self, fmt: str, *args: Any) -> None:  # quieter console
            if "/api/" in (self.path or ""):
                super().log_message(fmt, *args)

        # -- request trust boundary -------------------------------------
        def _loopback(self, scheme: str = "") -> set:
            port = self.server.server_address[1]
            pre = f"{scheme}://" if scheme else ""
            return {f"{pre}127.0.0.1:{port}", f"{pre}localhost:{port}", f"{pre}[::1]:{port}"}

        def _host_ok(self) -> bool:
            """The Host header must name this loopback server. A browser cannot
            forge Host, so this is what stops a rebound hostname from reaching
            any route — the page included, which is where the token lives."""
            return self.headers.get("Host", "") in self._loopback()

        def _origin_ok(self) -> bool:
            """A present Origin must be this server's own; an absent Origin (an
            ordinary same-origin GET, or a fetch that sends none) is allowed."""
            origin = self.headers.get("Origin")
            return origin is None or origin in self._loopback("http")

        def _token_ok(self) -> bool:
            if not token:
                return True
            sent = self.headers.get(TOKEN_HEADER, "")
            return secrets.compare_digest(sent, token)

        def _forbid_host(self) -> None:
            self.close_connection = True
            self._send(403, b"Forbidden: this address is not Charter's console.",
                       "text/plain; charset=utf-8")

        def _send(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status: int, data: Dict[str, Any]) -> None:
            # allow_nan=False: Charter never emits a value a browser's JSON.parse
            # cannot read. A value that somehow is non-finite becomes a safe 500
            # rather than an unparseable body.
            try:
                payload = json.dumps(data, allow_nan=False).encode("utf-8")
            except ValueError:
                return self._internal_error()
            self._send(status, payload, "application/json; charset=utf-8")

        def _error(self, exc: console.ApiError) -> None:
            body: Dict[str, Any] = {"error": exc.message}
            body.update(exc.payload)
            self._json(exc.status, body)

        def _internal_error(self) -> None:
            traceback.print_exc()  # the detail stays in the console window only
            self._send(500, json.dumps({"error": INTERNAL_ERROR}).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _read_body(self) -> bytes:
            """The whole request body, read before any answer is given, so a
            refusal is never lost to a reset connection or read as the next
            request. An unreadable or oversized length is refused unread, and
            that connection is closed."""
            raw_length = self.headers.get("Content-Length") or "0"
            try:
                length = int(raw_length)
            except ValueError:
                length = -1
            if length < 0:
                self.close_connection = True
                raise console.ApiError("Malformed request body.")
            if length > MAX_BODY:
                self.close_connection = True
                raise console.ApiError("That file is too large to add.", 413)
            return self.rfile.read(length) if length else b""

        @staticmethod
        def _parse(raw: bytes) -> Dict[str, Any]:
            if not raw:
                return {}
            try:
                data = hs.loads_strict(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise console.ApiError("Malformed request body.")
            if not isinstance(data, dict):
                raise console.ApiError("Malformed request body.")
            return data

        def _from_console(self) -> bool:
            return self.headers.get(console.CONSOLE_HEADER) == console.CONSOLE_HEADER_VALUE

        # -- routes -----------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._forbid_host()
            path = urlparse(self.path).path
            try:
                if path in console.GET_ROUTES:
                    if not self._from_console() or not self._token_ok():
                        return self._json(403, {"error": "This is available only in the console."})
                    return self._json(200, console.GET_ROUTES[path](session))
                if path.startswith("/api/"):
                    return self._json(404, {"error": "Unknown endpoint."})
                return self._static(path)
            except console.ApiError as exc:
                return self._error(exc)
            except Exception:  # noqa: BLE001
                return self._internal_error()

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._forbid_host()
            path = urlparse(self.path).path
            try:
                raw = self._read_body()  # before any answer, refusals included
            except console.ApiError as exc:
                return self._error(exc)
            try:
                route = POST_ROUTES.get(path)
                if route is None:
                    return self._json(404, {"error": "Unknown endpoint."})
                if not self._from_console() or not self._token_ok() or not self._origin_ok():
                    return self._json(403, {"error": "This action is available only in the "
                                                     "console."})
                return self._json(200, route(session, self._parse(raw)))
            except console.ApiError as exc:
                return self._error(exc)
            except Exception:  # noqa: BLE001
                return self._internal_error()

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            # Relative only, and contained by resolved path components: a
            # string prefix would admit a sibling such as `static-private/`.
            absolute = os.path.isabs(rel) or rel.startswith(("/", "\\")) or \
                bool(os.path.splitdrive(rel)[0]) or re.match(r"^[A-Za-z]:", rel)
            target = os.path.join(STATIC_DIR, rel)
            if absolute or not resolves_within(STATIC_DIR, target) or not os.path.isfile(target):
                return self._send(404, b"Not found", "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
            with open(target, "rb") as fh:
                data = fh.read()
            if token and os.path.basename(target) == "index.html":
                data = data.replace(TOKEN_PLACEHOLDER, token.encode("utf-8"))
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, data, ctype)

    return Handler


class ConsoleServer(ThreadingHTTPServer):
    """The console's HTTP server. It never reuses an address already in use: on
    Windows the default `SO_REUSEADDR` would let a second `charter serve` bind the
    same port silently, so the person's browser could reach a different console.
    Binding an in-use port fails cleanly instead."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt":
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except (OSError, AttributeError):
                pass
        super().server_bind()


def serve(folder: str = "", host: str = "127.0.0.1", port: int = 8765) -> int:
    session = console.Session()
    if folder:
        try:
            console.open_context(session, {"path": folder})
        except console.ApiError as exc:
            print(f"! {exc.message}")
    token = secrets.token_urlsafe(32)
    try:
        httpd = ConsoleServer((host, port), make_handler(session, token))
    except OSError as exc:
        print(f"! Port {port} on {host} is not available ({exc.strerror or exc}).")
        print("  Another program — perhaps another `charter serve` — may be using it. "
              "Start the console on a different port with `--port`.")
        return 1
    print("Charter")
    print(f"  Agent Context: {session.folder or '(none open)'}")
    print(f"  open:          http://{host}:{httpd.server_address[1]}")
    print("  stop:          Ctrl-C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0
