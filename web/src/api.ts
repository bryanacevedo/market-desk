// One fetch helper. In the demo the acting-as choice travels as a header; behind a real proxy it is ignored.
// A link may name who to act as (?as=3), so a shared demo link opens as that person.
let actingAs: string | null = (() => {
  const fromUrl = new URLSearchParams(window.location.search).get("as");
  if (fromUrl && /^\d+$/.test(fromUrl)) {
    try { localStorage.setItem("acting-as", fromUrl); } catch { /* private mode */ }
    return fromUrl;
  }
  try { return localStorage.getItem("acting-as"); } catch { return null; }
})();

export function setActingAs(id: number) {
  actingAs = String(id);
  try { localStorage.setItem("acting-as", actingAs); } catch { /* private mode */ }
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
