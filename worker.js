// Hitman Absolution contracts - sharing hub for Cloudflare Workers + D1.
// Same job as hub.py, but contracts are kept in a Cloudflare database, so they are never wiped.
// Needs a D1 database bound to this Worker with the variable name DB.

const FIELDS = ["_id", "DisplayId", "LevelIndex", "CheckpointIndex", "Difficulty", "ExitId", "UserId",
  "UserName", "Likes", "Dislikes", "Plays", "UserScore", "Title", "Description",
  "CompetitionHighestScore", "HighestScoringFriendName", "HighestScoringFriendScore",
  "StartingWeaponToken", "StartingOutfitToken", "Targets", "Restrictions"];
const NUMERIC = new Set(["LevelIndex", "CheckpointIndex", "Difficulty", "ExitId", "Likes", "Dislikes",
  "Plays", "UserScore", "CompetitionHighestScore", "HighestScoringFriendScore",
  "StartingWeaponToken", "StartingOutfitToken"]);
const LIMITS = { Description: 1500, Targets: 4000, Restrictions: 2000 };
const PAGE = 1000;
const MAX_CONTRACTS = 20000;
const POSTS_PER_MINUTE = 60;

const hits = new Map();
let hubId = null;

function clean(rec) {
  if (!rec || typeof rec !== "object" || Array.isArray(rec)) return null;
  const out = {};
  for (const k of FIELDS) {
    let v = rec[k];
    if (typeof v === "number") v = String(v);
    if (typeof v !== "string" || v.length > (LIMITS[k] || 200)) return null;
    if (NUMERIC.has(k) && !/^-?\d{1,12}$/.test(v)) return null;
    out[k] = v;
  }
  if (!/^[0-9a-f]{40}$/.test(out._id)) return null;
  for (const k of ["Targets", "Restrictions"]) {
    try { JSON.parse(out[k]); } catch (e) { return null; }
  }
  return out;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

async function getHubId(db) {
  if (hubId) return hubId;
  await db.prepare("INSERT OR IGNORE INTO meta (key, value) VALUES ('hub_id', ?)")
    .bind(crypto.randomUUID().replace(/-/g, "")).run();
  const row = await db.prepare("SELECT value FROM meta WHERE key = 'hub_id'").first();
  hubId = row.value;
  return hubId;
}

function allowed(ip) {
  const now = Date.now();
  const recent = (hits.get(ip) || []).filter((t) => now - t < 60000);
  if (recent.length >= POSTS_PER_MINUTE) return false;
  recent.push(now);
  hits.set(ip, recent);
  return true;
}

export default {
  async fetch(request, env) {
    const db = env.DB;
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/contracts") {
      const since = parseFloat(url.searchParams.get("since") || "0") || 0;
      const { results } = await db
        .prepare("SELECT data, created FROM contracts WHERE created > ? ORDER BY created ASC LIMIT ?")
        .bind(since, PAGE + 1).all();
      const page = results.slice(0, PAGE);
      const now = results.length > PAGE ? page[page.length - 1].created : Date.now() / 1000;
      return json({
        hub_id: await getHubId(db),
        now,
        contracts: page.map((r) => Object.assign(JSON.parse(r.data), { Created: r.created })),
      });
    }

    if (request.method === "POST" && url.pathname === "/contracts") {
      const ip = request.headers.get("CF-Connecting-IP") || "unknown";
      if (!allowed(ip)) return json({ ok: false, error: "slow down" }, 429);
      const text = await request.text();
      if (text.length === 0 || text.length > 20000) return json({ ok: false, error: "bad size" }, 400);
      let rec;
      try { rec = JSON.parse(text); } catch (e) { return json({ ok: false, error: "bad json" }, 400); }
      const c = clean(rec);
      if (!c) return json({ ok: false, error: "invalid contract" }, 400);
      const n = await db.prepare("SELECT COUNT(*) AS n FROM contracts").first();
      if (n.n < MAX_CONTRACTS) {
        await db.prepare("INSERT OR IGNORE INTO contracts (id, created, data) VALUES (?, ?, ?)")
          .bind(c._id, Date.now() / 1000, JSON.stringify(c)).run();
      }
      return json({ ok: true });
    }

    if (request.method === "GET" && url.pathname === "/") {
      const n = await db.prepare("SELECT COUNT(*) AS n FROM contracts").first();
      return json({ status: "Hitman Absolution contracts hub", contracts: n.n });
    }
    return json({ ok: false }, 404);
  },
};
