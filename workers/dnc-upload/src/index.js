// The DNC snapshot upload Worker.
//
// Division of labour, held deliberately: this Worker enforces SAFETY, and
// mail-engine's record_snapshot() enforces VALIDITY. So a filename is checked
// here for traversal and charset but NOT for being FTC-shaped — a garbage name
// must still reach the Python side, which records the rejection as evidence.
// Compliance judgment lives in exactly one place, and it is not here.
//
// The object key is derived from the TOKEN, never from client input beyond a bare
// basename: otherwise one rep could write into another rep's prefix.

const PREFIX = "dnc/";
const FILENAME = /^[A-Za-z0-9._-]{1,128}$/;
const HASH = /^[0-9a-f]{64}$/;
const MAX_BYTES = 64 * 1024 * 1024;
const LIST_LIMIT = 1000;

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Compare digests, not the secrets themselves: equal length, no early exit.
async function secretsMatch(given, expected) {
  if (!given || !expected) return false;
  const [a, b] = await Promise.all([sha256Hex(given), sha256Hex(expected)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function isAdmin(request, env) {
  const header = request.headers.get("Authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  return secretsMatch(token, env.ADMIN_TOKEN);
}

// The partner token is never stored here in plaintext: KV is keyed by its digest.
async function partnerFor(request, env) {
  const token = request.headers.get("X-API-KEY");
  if (!token) return null;
  return env.TOKENS.get(await sha256Hex(token));
}

function safeKey(key) {
  return key.startsWith(PREFIX) && !key.split("/").includes("..");
}

async function upload(request, env, filename) {
  const partnerId = await partnerFor(request, env);
  if (!partnerId) return json({ error: "unknown token" }, 401);
  if (!FILENAME.test(filename)) return json({ error: "bad filename" }, 400);

  const length = Number(request.headers.get("content-length"));
  if (!Number.isFinite(length) || length <= 0) {
    return json({ error: "content-length required" }, 411);
  }
  if (length > MAX_BYTES) return json({ error: "too large" }, 413);

  const key = `${PREFIX}${partnerId}/${filename}`;
  await env.SNAPSHOTS.put(key, request.body, {
    customMetadata: {
      partner_id: partnerId,
      claimed_fetched_at: request.headers.get("X-Fetched-At") || "",
    },
  });
  return json({ key }, 201);
}

async function pending(env) {
  // `include` is not optional: without it R2 omits customMetadata from a listing
  // and every object comes back with a null partner_id.
  const listing = await env.SNAPSHOTS.list({
    prefix: PREFIX,
    limit: LIST_LIMIT,
    include: ["customMetadata"],
  });
  return json({
    objects: listing.objects.map((object) => ({
      key: object.key,
      partner_id: object.customMetadata?.partner_id ?? null,
      claimed_fetched_at: object.customMetadata?.claimed_fetched_at || null,
      uploaded_at: object.uploaded.toISOString(),
      size: object.size,
    })),
    // The puller REFUSES a truncated listing rather than pulling a partial set:
    // keys sort lexicographically, so a full page can hide newer uploads forever.
    truncated: listing.truncated === true,
  });
}

async function fetchObject(env, key) {
  if (!safeKey(key)) return json({ error: "key outside the prefix" }, 400);
  const object = await env.SNAPSHOTS.get(key);
  if (!object) return json({ error: "not found" }, 404);
  return new Response(object.body, {
    headers: { "content-type": "application/zip" },
  });
}

async function putToken(request, env, hash) {
  if (!HASH.test(hash)) return json({ error: "not a sha-256" }, 400);
  const body = await request.json().catch(() => null);
  if (!body?.partner_id) return json({ error: "partner_id required" }, 400);
  await env.TOKENS.put(hash, body.partner_id);
  return json({ ok: true });
}

async function deleteToken(env, hash) {
  if (!HASH.test(hash)) return json({ error: "not a sha-256" }, 400);
  await env.TOKENS.delete(hash);
  return json({ ok: true });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = decodeURIComponent(url.pathname);

    if (request.method === "POST" && path.startsWith("/upload/")) {
      return upload(request, env, path.slice("/upload/".length));
    }

    if (!(await isAdmin(request, env))) return json({ error: "unauthorized" }, 401);

    if (request.method === "GET" && path === "/pending") return pending(env);
    if (request.method === "GET" && path.startsWith("/object/")) {
      return fetchObject(env, path.slice("/object/".length));
    }
    if (path.startsWith("/admin/tokens/")) {
      const hash = path.slice("/admin/tokens/".length);
      if (request.method === "PUT") return putToken(request, env, hash);
      if (request.method === "DELETE") return deleteToken(env, hash);
    }
    return json({ error: "not found" }, 404);
  },
};
