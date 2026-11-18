// One fetch helper. In the demo the acting-as choice travels as a header; behind a real proxy it is ignored.
// A link may name who to act as (?as=3), so a shared demo link opens as that person.
// The choice lasts for this browser tab (m4): a new visit opens as the default person, never as whoever the last visitor picked.
const KEY = "acting-as";
export function storedActingAs(): string | null {
  try { return sessionStorage.getItem(KEY); } catch { return null; }
}
let actingAs: string | null = (() => {
  const fromUrl = new URLSearchParams(window.location.search).get("as");
  if (fromUrl && /^\d+$/.test(fromUrl)) {
    try { sessionStorage.setItem(KEY, fromUrl); } catch { /* private mode */ }
    return fromUrl;
  }
  return storedActingAs();
})();

export function setActingAs(id: number) {
  actingAs = String(id);
  try { sessionStorage.setItem(KEY, actingAs); } catch { /* private mode */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: { "Content-Type": "application/json", ...(actingAs ? { "X-Acting-As": actingAs } : {}) },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : data?.error || "That did not go through.";
    throw new ApiError(res.status, msg);
  }
  return data as T;
}
