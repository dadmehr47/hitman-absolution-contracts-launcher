"""Hitman Absolution contracts - sharing hub.

A tiny public server that only stores contracts so players can share them.
Run it on any web host that can run Python:   python hub.py
It uses the PORT environment variable when the host sets one. Standard library only.
"""
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

FIELDS = ["_id", "DisplayId", "LevelIndex", "CheckpointIndex", "Difficulty", "ExitId", "UserId",
          "UserName", "Likes", "Dislikes", "Plays", "UserScore", "Title", "Description",
          "CompetitionHighestScore", "HighestScoringFriendName", "HighestScoringFriendScore",
          "StartingWeaponToken", "StartingOutfitToken", "Targets", "Restrictions"]
NUMERIC = {"LevelIndex", "CheckpointIndex", "Difficulty", "ExitId", "Likes", "Dislikes", "Plays",
           "UserScore", "CompetitionHighestScore", "HighestScoringFriendScore",
           "StartingWeaponToken", "StartingOutfitToken"}
LIMITS = {"Description": 1500, "Targets": 4000, "Restrictions": 2000}
MAX_CONTRACTS = 20000
PAGE = 1000
POSTS_PER_MINUTE = 60


def clean_record(rec):
    if not isinstance(rec, dict):
        return None
    out = {}
    for k in FIELDS:
        v = rec.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v)
        if not isinstance(v, str) or len(v) > LIMITS.get(k, 200):
            return None
        if k in NUMERIC and not re.fullmatch(r"-?\d{1,12}", v):
            return None
        out[k] = v
    if not re.fullmatch(r"[0-9a-f]{40}", out["_id"]):
        return None
    for k in ("Targets", "Restrictions"):
        try:
            json.loads(out[k])
        except ValueError:
            return None
    return out


class State:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        self.hub_id = d.get("hub_id") or uuid.uuid4().hex
        self.contracts = d.get("contracts", {})
        self.save()

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"hub_id": self.hub_id, "contracts": self.contracts}, f, ensure_ascii=False)
        os.replace(tmp, self.path)


def make_hub(data_path, host="0.0.0.0", port=8080):
    state = State(data_path)
    hits = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, obj, status=200):
            body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/contracts":
                try:
                    since = float(parse_qs(u.query).get("since", ["0"])[0])
                except ValueError:
                    since = 0.0
                with state.lock:
                    items = sorted((c for c in state.contracts.values()
                                    if c.get("Created", 0) > since), key=lambda c: c["Created"])
                    page = items[:PAGE]
                    now = page[-1]["Created"] if len(items) > PAGE else time.time()
                return self._send({"hub_id": state.hub_id, "now": now, "contracts": page})
            with state.lock:
                n = len(state.contracts)
            self._send({"status": "Hitman Absolution contracts hub", "contracts": n})

        def do_POST(self):
            if urlparse(self.path).path != "/contracts":
                return self._send({"ok": False}, 404)
            ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
            now = time.time()
            recent = [t for t in hits.get(ip, []) if now - t < 60]
            if len(recent) >= POSTS_PER_MINUTE:
                return self._send({"ok": False, "error": "slow down"}, 429)
            hits[ip] = recent + [now]
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > 20000:
                    return self._send({"ok": False, "error": "bad size"}, 400)
                rec = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, OSError):
                return self._send({"ok": False, "error": "bad json"}, 400)
            clean = clean_record(rec)
            if not clean:
                return self._send({"ok": False, "error": "invalid contract"}, 400)
            with state.lock:
                if clean["_id"] not in state.contracts and len(state.contracts) < MAX_CONTRACTS:
                    clean["Created"] = time.time()
                    state.contracts[clean["_id"]] = clean
                    state.save()
            self._send({"ok": True})

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.state = state
    return httpd


def main():
    port = int(os.environ.get("PORT", "8080"))
    path = os.environ.get("HUB_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "hub_data.json"))
    httpd = make_hub(path, "0.0.0.0", port)
    print("Hub running on port %d" % port, flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
