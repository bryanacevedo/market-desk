// The static snapshot's stand-in for the server (scripts/build_static_snapshot.py). Loaded after snapshot-config.js and
// before the app, it answers every call the app makes to /api from the saved responses in /_snapshot, and refuses every
// change in plain words. Nothing here talks to a server: the snapshot has none.
(function () {
  "use strict";
  var REFUSED = "The public demo does not do this. Run it yourself to try it.";
  var MISSING = {
    accounts: "The snapshot keeps every page of the account list and the first pages of each single filter. Searches and combined filters need the full demo: run it yourself to try them.",
    other: "This view is not in the snapshot. Run the demo yourself to see it.",
  };
  var config = window.__SNAPSHOT || { actors: [], defaultActor: "" };
  var realFetch = window.fetch.bind(window);
  var shards = {};

  function canon(v) {
    if (Array.isArray(v)) return v.map(canon);
    if (v && typeof v === "object") {
      var o = {};
      Object.keys(v).sort().forEach(function (k) { o[k] = canon(v[k]); });
      return o;
    }
    return v;
  }

  // The same key as the build's request_key: method, path, sorted query pairs, body, and who the visitor acts as.
  function keyOf(method, url, body, actor) {
    var pairs = [];
    url.searchParams.forEach(function (v, k) { pairs.push([k, v]); });
    pairs.sort(function (a, b) { return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0; });
    return JSON.stringify([method, url.pathname, pairs, body === undefined || body === null ? null : canon(body), String(actor)]);
  }

  async function sha1(text) {
    var buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf)).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  }

  async function gunzipJson(path) {
    var res = await realFetch(path);
    if (!res.ok) return null;
    var bytes = new Uint8Array(await res.arrayBuffer());
    // A host may already have undone the gzip in transit; only gzip bytes go through the decompressor.
    if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
      var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
      return JSON.parse(await new Response(stream).text());
    }
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  function shard(name) {
    if (!shards[name]) shards[name] = gunzipJson("/_snapshot/" + name + ".json.gz").catch(function () { return null; });
    return shards[name];
  }

  function reply(status, body) {
    return new Response(JSON.stringify(body), { status: status, headers: { "Content-Type": "application/json" } });
  }

  function headerOf(init, input, name) {
    var h = (init && init.headers) || (input && input.headers);
    if (!h) return null;
    if (typeof h.get === "function") return h.get(name);
    var found = null;
    Object.keys(h).forEach(function (k) { if (k.toLowerCase() === name.toLowerCase()) found = h[k]; });
    return found;
  }

  function missingText(path) {
    return /^\/api\/accounts$/.test(path) ? MISSING.accounts : MISSING.other;
  }

  // For tests/test_static_snapshot.py: the key the shim looks up, compared with the build's.
  window.__snapshotKey = keyOf;

  window.fetch = async function (input, init) {
    var url = new URL(typeof input === "string" || input instanceof URL ? String(input) : input.url, location.href);
    if (url.origin !== location.origin || !/^\/api\//.test(url.pathname)) return realFetch(input, init);
    var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
    if (method !== "GET") return reply(403, { error: REFUSED });
    // Who the visitor acts as: the desk sends the choice as a header. A choice the snapshot did not save is the default.
    var actor = String(headerOf(init, input, "X-Acting-As") || "");
    if (config.actors.indexOf(actor) === -1) actor = config.defaultActor;
    var hash = await sha1(keyOf(method, url, null, actor));
    var saved = await shard(hash.slice(0, 3));
    var hit = saved && saved[hash];
    if (hit && hit.length > 2) {                    // the same answer for both people, kept once
      var other = await shard(hit[2].slice(0, 3));
      hit = other && other[hit[2]];
    }
    if (hit) return reply(hit[0], hit[1]);
    return reply(404, { error: missingText(url.pathname) });
  };
})();
