"""Hitman Absolution - Contracts mode server (replacement for HM5.Server.exe).

Saves contracts, keeps a wallet per player, pays money for finished contracts,
and has an "unlimited money" switch. Standard library only.
"""
import hashlib
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
from urllib.parse import parse_qs, urlparse

APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
DATA_DIR = os.path.join(APP_DIR, "data")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
INT_MAX = 2147483647
DEFAULT_HUB = "https://hitman-absolution-contracts-hub.www-dadmehr47.workers.dev"
OLD_HUBS = {"https://hitman-absolution-contracts-hub.onrender.com"}

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 40147,
    "unlimited_money": False,
    "unlimited_amount": INT_MAX,
    "start_money": 0,
    "reward_multiplier": 1.0,
    "share_online": False,
    "hub_url": DEFAULT_HUB,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    if not cfg.get("hub_url") or cfg["hub_url"] in OLD_HUBS:
        cfg["hub_url"] = DEFAULT_HUB
    return cfg


def save_config(cfg):
    data = dict(cfg)
    if data.get("hub_url") == DEFAULT_HUB:  # only remember a custom address
        data.pop("hub_url", None)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


FIELDS = ["_id", "DisplayId", "LevelIndex", "CheckpointIndex", "Difficulty", "ExitId", "UserId",
          "UserName", "Likes", "Dislikes", "Plays", "UserScore", "Title", "Description",
          "CompetitionHighestScore", "HighestScoringFriendName", "HighestScoringFriendScore",
          "StartingWeaponToken", "StartingOutfitToken", "Targets", "Restrictions"]
NUMERIC = {"LevelIndex", "CheckpointIndex", "Difficulty", "ExitId", "Likes", "Dislikes", "Plays",
           "UserScore", "CompetitionHighestScore", "HighestScoringFriendScore",
           "StartingWeaponToken", "StartingOutfitToken"}
LIMITS = {"Description": 1500, "Targets": 4000, "Restrictions": 2000}


def clean_record(rec):
    """Accept a contract only if every field is plain, expected data (used for shared contracts)."""
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


def http_json(method, url, payload=None, timeout=70):
    try:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Content-Type": "application/json", "User-Agent": "HM5ContractsClient/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


class Store:
    """Contracts, players and scores, kept in small JSON files."""

    def __init__(self, cfg, data_dir=None, log=None):
        self.cfg = cfg
        self.dir = data_dir or DATA_DIR
        self.log = log or (lambda m: None)
        self.lock = threading.RLock()
        self.sync_lock = threading.Lock()
        self._sync_failed = False
        os.makedirs(self.dir, exist_ok=True)
        self.contracts = self._load("contracts.json", [])
        self.users = self._load("users.json", {})
        self.scores = self._load("scores.json", {})
        self.sync_state = self._load("sync.json", {})
        self.import_contracts(os.path.join(APP_DIR, "Contracts"))

    def _load(self, name, default):
        try:
            with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    def _save(self, name, obj):
        path = os.path.join(self.dir, name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)

    def save_all(self):
        self._save("contracts.json", self.contracts)
        self._save("users.json", self.users)
        self._save("scores.json", self.scores)
        self._save("sync.json", self.sync_state)

    # ---- sharing with the online hub -----------------------------------
    def kick_sync(self):
        if self.cfg.get("share_online"):
            threading.Thread(target=self.sync, daemon=True).start()

    def sync(self):
        base = (self.cfg.get("hub_url") or "").strip().rstrip("/")
        if not (self.cfg.get("share_online") and base):
            return
        if not self.sync_lock.acquire(blocking=False):
            return
        try:
            self._sync(base)
        finally:
            self.sync_lock.release()

    def _sync(self, base):
        since = self.sync_state.get("last_pull", 0)
        r = http_json("GET", "%s/contracts?since=%s" % (base, since))
        if not r or "hub_id" not in r:
            if not self._sync_failed:
                self.log("Sharing server not reachable (will keep trying)")
            self._sync_failed = True
            return
        self._sync_failed = False
        with self.lock:
            if r["hub_id"] != self.sync_state.get("hub_id"):  # new or reset hub: share everything again
                for c in self.contracts:
                    c["_synced"] = False
                self.sync_state["hub_id"] = r["hub_id"]
                if since:
                    since = 0
        if since == 0 and r.get("contracts") is not None and self.sync_state.get("last_pull", 0):
            r = http_json("GET", "%s/contracts?since=0" % base) or r
        new = 0
        with self.lock:
            for rec in r.get("contracts", []):
                clean = clean_record(rec)
                if not clean or self.find(clean["_id"]):
                    continue
                ts = rec.get("Created")
                clean["_ts"] = float(ts) if isinstance(ts, (int, float)) else time.time()
                clean["_synced"] = True
                self.contracts.append(clean)
                new += 1
            pending = []
            for c in self.contracts:
                if not c.get("_synced"):
                    clean = clean_record(public_contract(c))
                    if clean:
                        pending.append((c["_id"], dict(clean, Created=c.get("_ts", time.time()))))
        sent = 0
        for cid, rec in pending:
            if http_json("POST", base + "/contracts", rec):
                sent += 1
                with self.lock:
                    c = self.find(cid)
                    if c:
                        c["_synced"] = True
        with self.lock:
            self.sync_state["last_pull"] = r.get("now", self.sync_state.get("last_pull", 0))
            self.save_all()
        if new:
            self.log("Got %d new contract(s) from other players" % new)
        if sent:
            self.log("Shared %d of your contract(s)" % sent)

    def import_contracts(self, folder):
        """Import contracts saved by the old HM5.Server.exe (one .json file each)."""
        if not os.path.isdir(folder):
            return
        added = 0
        for name in sorted(os.listdir(folder)):
            cid, ext = os.path.splitext(name)
            if ext.lower() != ".json" or self.find(cid):
                continue
            try:
                with open(os.path.join(folder, name), encoding="utf-8-sig") as f:
                    o = json.load(f)
                uid = str(o.get("UserId", ""))
                score = str(o.get("Score", 0))
                title = o.get("Title", "Contract")
                self.contracts.append({
                    "_id": cid, "DisplayId": title,
                    "LevelIndex": str(o.get("LevelIndex", 0)),
                    "CheckpointIndex": str(o.get("CheckpointIndex", 0)),
                    "Difficulty": str(o.get("Difficulty", 0)),
                    "ExitId": str(o.get("ExitId", 0)),
                    "UserId": uid, "UserName": self.users.get(uid, {}).get("name", uid),
                    "Likes": "0", "Dislikes": "0", "Plays": "0", "UserScore": score,
                    "Title": title, "Description": o.get("Description", ""),
                    "CompetitionHighestScore": "0",
                    "HighestScoringFriendName": self.users.get(uid, {}).get("name", uid),
                    "HighestScoringFriendScore": score,
                    "StartingWeaponToken": str(o.get("StartingWeaponToken", 0)),
                    "StartingOutfitToken": str(o.get("StartingOutfitToken", 0)),
                    "Targets": dumps({"Targets": _ordered_targets(o.get("Targets", []))}),
                    "Restrictions": dumps({"Restrictions": o.get("Restrictions", [])}),
                    "_ts": os.path.getmtime(os.path.join(folder, name)),
                })
                added += 1
            except (OSError, ValueError):
                continue
        if added:
            self.save_all()

    def user(self, uid):
        uid = uid or "default"
        if uid not in self.users:
            self.users[uid] = {"name": uid, "wallet": int(self.cfg["start_money"]), "plays": 0}
        return self.users[uid]

    def wallet(self, uid):
        if self.cfg["unlimited_money"]:
            return min(int(self.cfg["unlimited_amount"]), INT_MAX)
        return int(self.user(uid)["wallet"])

    def find(self, cid):
        for c in self.contracts:
            if c["_id"] == cid:
                return c
        return None


def _ordered_targets(raw):
    out = []
    for t in raw:
        item = {
            "Name": t.get("Name", ""),
            "WeaponToken": t.get("WeaponToken", 0),
            "OutfitToken": t.get("OutfitToken", 0),
            "AmmoType": t.get("AmmoType", 0),
            "SpecialSituation": t.get("SpecialSituation", 0),
        }
        for k, v in t.items():
            item.setdefault(k, v)
        out.append(item)
    return out


def _json_list(text):
    try:
        v = json.loads(text)
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def public_contract(c):
    return {k: v for k, v in c.items() if k == "_id" or not k.startswith("_")}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HM5Server/1.0"
    store = None
    cfg = None
    log = staticmethod(lambda msg: None)
    metadata = b"{}"

    def log_message(self, *args):
        pass

    # ---- plumbing -------------------------------------------------------
    def _send(self, body=b"", status=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            data = b""
            while True:
                size = int(self.rfile.readline().strip() or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    break
                data += self.rfile.read(size)
                self.rfile.readline()
            return data
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._read_body()
        self._handle()

    def _handle(self):
        u = urlparse(self.path)
        segs = u.path.strip("/").split("/", 1)
        if len(segs) < 2:
            return self._home()
        ep = segs[1]
        q = {k.lower(): v[0].strip("'") for k, v in
             parse_qs(u.query, keep_blank_values=True).items()}
        try:
            with self.store.lock:
                body = self.route(ep, q)
        except Exception as e:  # never crash the game on a bad request
            self.log("ERROR %s: %r" % (ep, e))
            body = ""
        if ep.lower() == "searchforcontracts2":
            self.log("Browsing contracts")
        self._send(body)

    def _home(self):
        n = len(self.store.contracts)
        self._send("{\"status\":\"Hitman Absolution contracts server\",\"contracts\":%d}" % n)

    # ---- the game's endpoints --------------------------------------------
    def route(self, ep, q):
        s, cfg = self.store, self.cfg
        uid = q.get("userid", "")
        e = ep.lower()

        if e == "os_getstatus":
            return dumps({"d": {"ClientIP": self.client_address[0]}})
        if e == "$os_metadata":
            return self.metadata
        if e == "getuserwallet":
            return dumps({"d": {"Key": str(s.wallet(uid))}})
        if e == "getnewmessagecount":
            return dumps({"d": {"Key": "0"}})
        if e == "getmessages":
            return dumps({"d": {"results": [], "__count": "0"}})
        if e == "mergeusertokens":
            return dumps({"d": {"results": [], "__count": "0"}})
        if e == "getfeaturedcontract":
            return dumps({"d": {}})
        if e == "getaveragescores":
            return dumps({"d": ["0", "0", "0", "0"]})
        if e == "getscores":
            return dumps({"d": {"results": [], "__count": "0"}})

        if e == "updateuserinfo":
            u = s.user(uid)
            if q.get("displayname"):
                u["name"] = q["displayname"]
            s.save_all()
            return ""
        if e.startswith("updateuserprofile") or e == "addmetrics" or e == "queueremovecontract":
            return ""

        if e == "getuseroverviewdata":
            u = s.user(uid)
            created = sum(1 for c in s.contracts if c.get("UserId") == uid)
            return dumps({"d": {"results": {
                "WalletAmount": str(s.wallet(uid)), "ContractPlays": str(u.get("plays", 0)),
                "RichestRank": "0", "RichestAverage": "0", "TrophiesEarned": "0",
                "CompetitionPlays": "0", "DeadliestRank": "0", "DeadliestAverage": "0",
                "ContractsCreated": str(created), "ContractsCreatedLikes": "0",
                "PopularRank": "0", "PopularAverage": "0"}}})

        if e == "uploadcontract":
            return self.upload(q, uid)
        if e == "searchforcontracts2":
            return self.search(q)
        if e == "markcontractasplayed":
            c = s.find(q.get("contractid", ""))
            if c:
                c["Plays"] = str(int(c.get("Plays", "0")) + 1)
            s.user(uid)["plays"] = s.user(uid).get("plays", 0) + 1
            s.save_all()
            return ""
        if e == "putscore":
            return self.put_score(q, uid)

        # Anything we do not know yet: answer politely and remember it.
        self.log("UNKNOWN endpoint: %s" % self.path[:300])
        try:
            with open(os.path.join(DATA_DIR, "unknown_requests.log"), "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), self.path[:2000]))
        except OSError:
            pass
        return dumps({"d": {}}) if e.startswith(("get", "search")) else ""

    def upload(self, q, uid):
        s = self.store
        title = q.get("title", "Contract")
        targets = _ordered_targets(_json_list(q.get("targetsjson")))
        restrictions = _json_list(q.get("restrictionsjson"))
        score = q.get("score", "0")
        seed = "%s|%s|%s|%s|%s" % (uid, time.time(), title, q.get("levelindex"), score)
        name = s.user(uid)["name"]
        rec = {
            "_id": hashlib.sha1(seed.encode()).hexdigest(),
            "DisplayId": title,
            "LevelIndex": q.get("levelindex", "0"),
            "CheckpointIndex": q.get("checkpointindex", "0"),
            "Difficulty": q.get("difficulty", "0"),
            "ExitId": q.get("exitid", "0"),
            "UserId": uid,
            "UserName": name,
            "Likes": "0", "Dislikes": "0", "Plays": "0",
            "UserScore": score,
            "Title": title,
            "Description": q.get("description", ""),
            "CompetitionHighestScore": "0",
            "HighestScoringFriendName": name,
            "HighestScoringFriendScore": score,
            "StartingWeaponToken": q.get("startingweapontoken", "0"),
            "StartingOutfitToken": q.get("startingoutfittoken", "0"),
            "Targets": dumps({"Targets": targets}),
            "Restrictions": dumps({"Restrictions": restrictions}),
            "_ts": time.time(),
        }
        s.contracts.append(rec)
        s.save_all()
        self.log("Saved new contract: %s" % title)
        s.kick_sync()
        return ""

    def search(self, q):
        items = list(reversed(sorted(self.store.contracts, key=lambda c: c.get("_ts", 0))))

        def keep(c):
            if q.get("contractid") and c["_id"] != q["contractid"]:
                return False
            if q.get("contractname") and q["contractname"].lower() not in c.get("Title", "").lower():
                return False
            for param, field in (("levelindex", "LevelIndex"), ("difficulty", "Difficulty"),
                                 ("checkpointid", "CheckpointIndex")):
                if q.get(param, "-1") not in ("-1", "") and c.get(field) != q[param]:
                    return False
            return True

        items = [c for c in items if keep(c)]
        try:
            start = max(int(q.get("startindex", "0")), 0)
            size = int(q.get("range", "10"))
        except ValueError:
            start, size = 0, 10
        page = items[start:start + size]
        return dumps({"d": {"results": [public_contract(c) for c in page],
                            "__count": str(len(page))}})

    def put_score(self, q, uid):
        s, cfg = self.store, self.cfg
        cid = q.get("leaderboardid", "")
        try:
            score = int(float(q.get("score", "0")))
        except ValueError:
            score = 0
        board = s.scores.setdefault(cid, {})
        c = s.find(cid)
        best = int(c.get("UserScore", "0") or 0) if c else 0
        best = max([best] + list(board.values()))
        board[uid] = max(score, board.get(uid, score))
        if c and score > int(c.get("HighestScoringFriendScore", "0") or 0):
            c["HighestScoringFriendScore"] = str(score)
            c["HighestScoringFriendName"] = s.user(uid)["name"]
        reward = int(max(score, 0) * float(cfg["reward_multiplier"]))
        u = s.user(uid)
        u["wallet"] = min(int(u["wallet"]) + reward, INT_MAX)
        s.save_all()
        self.log("Score %d -> reward $%d" % (score, reward))
        return dumps({"d": {"Key": str(score - best)}})


def make_server(cfg, log=None, data_dir=None):
    """Create (not start) the server. Raises OSError if the port is busy."""
    store = Store(cfg, data_dir, log)
    try:
        with open(os.path.join(RES_DIR, "metadata.json"), "rb") as f:
            meta = f.read()
    except OSError:
        meta = b"{}"

    class H(Handler):
        pass

    H.store, H.cfg, H.metadata = store, cfg, meta
    if log:
        H.log = staticmethod(log)
    httpd = ThreadingHTTPServer((cfg["host"], int(cfg["port"])), H)
    httpd.daemon_threads = True
    return httpd


def start_sync_loop(httpd, interval=60):
    """Every minute: fetch other players' contracts and share ours. Returns a stop Event."""
    stop = threading.Event()
    store = httpd.RequestHandlerClass.store

    def loop():
        while not stop.is_set():
            store.sync()
            stop.wait(interval)

    threading.Thread(target=loop, daemon=True).start()
    return stop


def main():
    cfg = load_config()
    if not os.path.exists(CONFIG_PATH):
        save_config(cfg)
    if os.environ.get("PORT"):  # free web hosts set this
        cfg["host"], cfg["port"] = "0.0.0.0", int(os.environ["PORT"])
    httpd = make_server(cfg, lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
    print("Server running on http://%s:%s  (unlimited money: %s)"
          % (cfg["host"], cfg["port"], cfg["unlimited_money"]), flush=True)
    start_sync_loop(httpd)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
