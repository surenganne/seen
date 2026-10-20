import fixtures from "./fixtures.json";

/** The API as the pages see it, from responses captured off a seeded scratch home (scripts/capture_web_fixtures.py).
 *  ok: the captured data. empty: the same shapes with every list emptied. down: every call answers 500. */
export type Mode = "ok" | "empty" | "down";
/** replies: a one-off answer for a pathname suffix (a status the captured fixtures do not cover, such as a 404). */
export const state: { mode: Mode; calls: string[]; replies: Record<string, { status: number; body: unknown }> } = { mode: "ok", calls: [], replies: {} };
export const ids = (fixtures as unknown as { _ids: { pid: string; cid: string } })._ids;

function empty(v: unknown): unknown {
  if (Array.isArray(v)) return [];
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, k === "total" ? 0 : empty(x)]));
  return v;
}

export async function mockFetch(input: RequestInfo | URL): Promise<Response> {
  const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost");
  state.calls.push(url.pathname);
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  if (state.mode === "down") return json(500, { detail: "the ledger is unavailable" });
  const reply = Object.entries(state.replies).find(([k]) => url.pathname.endsWith(k))?.[1];
  if (reply) return json(reply.status, reply.body);
  const hit = (fixtures as Record<string, unknown>)[url.pathname];
  if (hit === undefined) return json(404, { detail: `no fixture for ${url.pathname}` });
  return json(200, state.mode === "empty" ? empty(hit) : hit);
}
