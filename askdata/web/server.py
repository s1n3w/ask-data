"""Local HTTP server for the desktop UI: static files plus a small JSON API.

Endpoints
  GET  /api/status?dataset=chinook  -> model readiness, the dataset's UI text and a one-line summary
  POST /api/ask      {question, dataset} -> answer, SQL, columns, rows, refusal/error, timing
"""
import json
import mimetypes
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from urllib.parse import parse_qs, urlparse

from ..ask import ask
from ..datasets import CHINOOK, DATASETS, Dataset

STATIC = Path(__file__).with_name("static")
MAX_ROWS_SENT = 500
# One model: questions run one at a time.
_work_lock = threading.Lock()


class AppState:
    model_ready = False
    model_error: str | None = None


def summary(dataset: Dataset) -> str:
    """One sentence describing what the dataset holds, shown under the question box."""
    db = sqlite3.connect(f"file:{dataset.db_path.as_posix()}?mode=ro", uri=True)
    one = lambda sql: db.execute(sql).fetchone()[0]
    try:
        return (f"Chinook is a sample sales database: {one('SELECT COUNT(*) FROM Customer')} customers in "
                f"{one('SELECT COUNT(DISTINCT Country) FROM Customer')} countries, {one('SELECT COUNT(*) FROM Track'):,} tracks, "
                f"and {one('SELECT COUNT(*) FROM Invoice')} invoices worth ${one('SELECT SUM(Total) FROM Invoice'):,.2f} "
                f"from 2009 to 2013.")
    finally:
        db.close()


def answer_question(question: str, dataset: Dataset) -> dict:
    with _work_lock:
        r = ask(question, dataset=dataset)
    return {
        "question": r.question,
        "answer": r.answer,
        "refusal": r.refusal,
        "error": r.error,
        "sql": r.sql,
        "columns": r.columns,
        "rows": [list(row) for row in r.rows[:MAX_ROWS_SENT]],
        "truncated": r.truncated or len(r.rows) > MAX_ROWS_SENT,
        "seconds": round(r.seconds, 1),
        "attempts": r.attempts,
        "corrections": [{"typed": typed, "matched": matched} for typed, matched in r.corrections],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # keep the console/log quiet
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, status: int = 200) -> None:
        self._send(status, json.dumps(data, default=str).encode("utf-8"), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/status":
            dataset = DATASETS.get(parse_qs(url.query).get("dataset", ["chinook"])[0], CHINOOK)
            return self._json({
                "model_ready": AppState.model_ready, "model_error": AppState.model_error,
                "datasets": [{"key": d.key, "title": d.title} for d in DATASETS.values()],
                "dataset": {"key": dataset.key, "title": dataset.title, "ask_label": dataset.ask_label,
                            "examples": dataset.examples},
                "summary": summary(dataset),
            })
        name = "index.html" if url.path in ("/", "/index.html") else url.path.lstrip("/")
        file = (STATIC / name).resolve()
        if not file.is_file() or STATIC.resolve() not in file.parents:
            return self._send(404, b"Not found", "text/plain")
        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self._send(200, file.read_bytes(), content_type)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/ask":
                question = str(payload.get("question", "")).strip()
                if not question:
                    return self._json({"error": "Type a question first."}, 400)
                dataset = DATASETS.get(str(payload.get("dataset", "chinook")), CHINOOK)
                return self._json(answer_question(question, dataset))
            self._json({"error": "Unknown endpoint."}, 404)
        except Exception as e:  # surface the reason in the UI instead of a dead request
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def start_server(port: int = 0) -> ThreadingHTTPServer:
    """Serve on 127.0.0.1 (a free port when port=0) in a background thread."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
