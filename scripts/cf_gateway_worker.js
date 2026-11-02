/**
 * Panodrome AI Gateway — Cloudflare Worker + location-pinned Durable Object
 * -------------------------------------------------------------------------
 * Purpose: stable access to the Google Generative Language API (Gemini)
 * from networks where Google applies a regional availability block
 * (e.g. this build sandbox egresses from Hong Kong; the team also works
 * from Iran — both are on Google's unsupported-locations list).
 *
 * Architecture:
 *   client ──> workers.dev edge (any colo, fast for the caller)
 *                 └──> Durable Object "gemini" (locationHint: enam —
 *                      Eastern North America, near Google's infra)
 *                          └──> generativelanguage.googleapis.com
 *
 * The actual upstream fetch executes INSIDE the Durable Object, so its
 * egress IP geolocates to North America and Google's regional block is
 * bypassed. Authentication passes through unchanged — callers still send
 * their own key (x-goog-api-key header or ?key= query param). This Worker
 * holds NO secrets.
 *
 * Routes:
 *   /                     -> liveness
 *   /__trace              -> which colo serves the edge Worker
 *   /__placement          -> which colo executes the Durable Object
 *   /v1beta/* /v1/*       -> proxied to generativelanguage.googleapis.com
 */
const UPSTREAM_ORIGIN = 'https://generativelanguage.googleapis.com';
const DO_NAME = 'gemini';
const LOCATION_HINT = 'enam'; // Eastern North America (best-effort pin)

const STRIP_REQUEST_HEADERS = [
  'cf-connecting-ip', 'cf-ipcountry', 'cf-ray', 'cf-visitor',
  'cf-worker', 'cf-etag', 'cdn-loop',
  'x-forwarded-for', 'x-forwarded-proto', 'x-real-ip',
  'host',            // fetch() sets Host from the target URL
  'content-length',  // recomputed for replayed bodies
];

const STRIP_RESPONSE_HEADERS = [
  'content-encoding', // Workers decompresses automatically; avoid mismatch
  'content-length',   // let the runtime recompute for the proxied body
];

async function proxyToUpstream(request) {
  const incoming = new URL(request.url);
  const upstream = new URL(incoming.pathname + incoming.search, UPSTREAM_ORIGIN);
  const headers = new Headers(request.headers);
  for (const h of STRIP_REQUEST_HEADERS) headers.delete(h);

  const init = { method: request.method, headers, redirect: 'manual' };
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = await request.arrayBuffer();
  }

  const resp = await fetch(upstream, init);
  const outHeaders = new Headers(resp.headers);
  for (const h of STRIP_RESPONSE_HEADERS) outHeaders.delete(h);
  outHeaders.set('x-panodrome-gateway', 'do-' + LOCATION_HINT);
  return new Response(resp.body, {
    status: resp.status,
    statusText: resp.statusText,
    headers: outHeaders,
  });
}

/** Durable Object class — the fetch below executes in the hinted region. */
export class GeminiOriginFetcher {
  async fetch(request) {
    const incoming = new URL(request.url);

    // Diagnostic: which colo is THIS Durable Object running in?
    if (incoming.pathname === '/__placement') {
      const r = await fetch('https://www.cloudflare.com/cdn-cgi/trace');
      const text = await r.text();
      const colo = (text.match(/^colo=(.+)$/m) || [])[1] || 'unknown';
      const loc = (text.match(/^loc=(.+)$/m) || [])[1] || 'unknown';
      return new Response(
        JSON.stringify({ do_colo: colo.trim(), do_loc: loc.trim() }, null, 2),
        { headers: { 'content-type': 'application/json', 'x-panodrome-gateway': 'do' } },
      );
    }

    return proxyToUpstream(request);
  }
}

/** Edge Worker — validates the route, then hands off to the pinned DO. */
export default {
  async fetch(request, env) {
    const incoming = new URL(request.url);

    // Diagnostic: which colo serves this edge Worker (should follow clients).
    if (incoming.pathname === '/__trace') {
      const cf = request.cf || {};
      return new Response(
        JSON.stringify(
          { colo: cf.colo, country: cf.country, city: cf.city, asOrganization: cf.asOrganization },
          null, 2,
        ),
        { headers: { 'content-type': 'application/json', 'x-panodrome-gateway': 'edge' } },
      );
    }

    if (incoming.pathname === '/') {
      return new Response('Panodrome AI Gateway OK', {
        status: 200,
        headers: { 'x-panodrome-gateway': 'edge' },
      });
    }

    const allowed =
      incoming.pathname.startsWith('/v1beta') ||
      incoming.pathname.startsWith('/v1') ||
      incoming.pathname === '/__placement';
    if (!allowed) {
      return new Response('Panodrome AI Gateway: /v1beta/* and /v1/* only', { status: 403 });
    }

    const id = env.ORIGIN_FETCHER.idFromName(DO_NAME);
    // locationHint applies at DO creation (first get()); pass it every time.
    const stub = env.ORIGIN_FETCHER.get(id, { locationHint: LOCATION_HINT });
    return stub.fetch(request);
  },
};
