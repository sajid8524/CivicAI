from __future__ import annotations
import os
import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import database
from . import services


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / "app" / "static"


class CivicAIHandler(BaseHTTPRequestHandler):
    server_version = "CivicAI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[CivicAI] {self.address_string()} - {fmt % args}")

    @property
    def conn(self):
        return self.server.conn  # type: ignore[attr-defined]

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.add_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self.send_json({"ok": True, "service": "CivicAI"})
            return
        if path == "/api/complaints":
            self.send_json({"complaints": database.list_complaints(self.conn)})
            return
        if path.startswith("/api/complaints/"):
            complaint_id = unquote(path.rsplit("/", 1)[-1]).upper()
            complaint = database.get_complaint(self.conn, complaint_id)
            if not complaint:
                self.send_json({"error": "Complaint not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json({"complaint": complaint})
            return
        if path == "/api/dashboard":
            self.send_json(services.snapshot(self.conn))
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/complaints":
            payload = self.read_json()
            if not payload.get("description") or not payload.get("location"):
                self.send_json({"error": "description and location are required"}, status=HTTPStatus.BAD_REQUEST)
                return
            result = services.submit_complaint(self.conn, payload)
            self.send_json(result, status=HTTPStatus.CREATED)
            return
        if path == "/api/monitor/run":
            self.send_json(services.monitor(self.conn))
            return
        if path.startswith("/api/complaints/") and path.endswith("/feedback"):
            parts = path.strip("/").split("/")
            complaint_id = unquote(parts[2]).upper()
            payload = self.read_json()
            result = services.submit_feedback(self.conn, complaint_id, payload)
            if not result:
                self.send_json({"error": "Complaint not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json(result, status=HTTPStatus.CREATED)
            return
        self.send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/complaints/") and path.endswith("/status"):
            parts = path.strip("/").split("/")
            complaint_id = unquote(parts[2]).upper()
            payload = self.read_json()
            status = str(payload.get("status") or "").strip()
            if not status:
                self.send_json({"error": "status is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            complaint = services.update_status(self.conn, complaint_id, status, payload.get("note") or "")
            if not complaint:
                self.send_json({"error": "Complaint not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json({"complaint": complaint})
            return
        self.send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
        self.send_response(status)
        self.add_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def add_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def serve_static(self, request_path: str) -> None:
        if request_path in {"/", ""}:
            file_path = STATIC_DIR / "index.html"
        else:
            relative = Path(unquote(request_path.lstrip("/")))
            if relative.parts and relative.parts[0] == "static":
                relative = Path(*relative.parts[1:])
            file_path = (STATIC_DIR / relative).resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())):
                self.send_error(HTTPStatus.FORBIDDEN)
                return

        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = file_path.read_bytes()
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def build_server(host: str, port: int) -> ThreadingHTTPServer:
    database.init_database()
    conn = database.connect()
    server = ThreadingHTTPServer((host, port), CivicAIHandler)
    server.conn = conn  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CivicAI server")
    default_host = os.getenv("HOST", "0.0.0.0")
    default_port = int(os.getenv("PORT", "8080"))
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", default=default_port, type=int)
    args = parser.parse_args()
    server = build_server(args.host, args.port)
    print(f"CivicAI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping CivicAI")
    finally:
        server.conn.close()  # type: ignore[attr-defined]
        server.server_close()


if __name__ == "__main__":
    main()
