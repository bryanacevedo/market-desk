import { useEffect, useState } from "react";
import { Books, MagnifyingGlass } from "@phosphor-icons/react";
import { Logo } from "../marks";
import { Empty, Failed, Fig, Loading, Section, Status, n0, navigate, pct, useData, usePath, withParam } from "../lib";
import { FitBand, Hours, Tier } from "../parts";
import { openSheet } from "../sheets";

const REASON: Record<string, string> = {
  rule: "Territory rule", test: "Segment test", existing_owner: "Customer", open_deal: "Open deal", customer_team: "Customer team",
  balance_move: "Moved to balance", manual: "Moved by hand",
};
export const reasonWord = (r: string | null | undefined) => (r ? REASON[r] || r : "Unassigned");

export function Accounts() {
  const [, params] = usePath();
  const [q, setQ] = useState(params.get("q") || "");
  const qs = new URLSearchParams();
  for (const k of ["q", "tier", "segment", "owner", "page", "region"]) if (params.get(k)) qs.set(k, params.get(k)!);
  const { data, error, reload } = useData<any>(`/api/accounts?${qs.toString()}`);
  const me = useData<any>("/api/me").data;
  useEffect(() => {
    const t = setTimeout(() => { if ((params.get("q") || "") !== q) navigate(withParam("q", q || null).replace(/([?&])page=\d+&?/, "$1"), true); }, 250);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: string, v: string) => { const u = new URL(window.location.href); if (v) u.searchParams.set(k, v); else u.searchParams.delete(k); u.searchParams.delete("page"); navigate(u.pathname + u.search, true); };
  const lead = me && ["revops", "manager"].includes(me.user.role);
  const cols = "28px minmax(0,1.4fr) minmax(0,1fr) 70px 70px minmax(0,0.9fr) 92px";
  return (
    <div className="page">
      <div className="head"><h1>Accounts</h1>{data ? <span className="mute">{n0(data.total)}</span> : null}</div>
      <div className="toolbar">
        <div className="search"><MagnifyingGlass size={16} className="mute" /><input className="input" placeholder="Name or domain" aria-label="Search accounts" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div className="actions">
          <select className="select" aria-label="Tier" value={params.get("tier") || ""} onChange={(e) => set("tier", e.target.value)} style={{ width: 130 }}>
            <option value="">Every tier</option><option value="A">Tier A</option><option value="B">Tier B</option><option value="C">Tier C</option><option value="X">Tier X</option><option value="NJ">Not judged</option>
          </select>
          <select className="select" aria-label="Segment" value={params.get("segment") || ""} onChange={(e) => set("segment", e.target.value)} style={{ width: 190 }}>
            <option value="">Every segment</option>{data?.segments.map((s: any) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          {lead ? (
            <select className="select" aria-label="Owner" value={params.get("owner") || ""} onChange={(e) => set("owner", e.target.value)} style={{ width: 170 }}>
              <option value="">Every owner</option><option value="unassigned">Unassigned</option>{data?.owners.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          ) : null}
          {params.get("region") ? <button className="btn line sm" onClick={() => set("region", "")}>{params.get("region")} ×</button> : null}
        </div>
      </div>
      {error ? <Failed error={error} retry={reload} /> : !data ? <Loading /> : data.rows.length ? (
        <>
          <div className="ledger wrap-names accounts">
            <div className="row head" style={{ gridTemplateColumns: cols }}>
              <span /><span>Company</span><span>Segment</span><span className="num">Tier</span><span className="num">Data known</span><span>Owner</span><span className="num">Last result</span>
            </div>
            {data.rows.map((r: any) => (
              <button key={r.id} className="row" style={{ gridTemplateColumns: cols }} onClick={() => openSheet("company", r.id)}>
                <Logo domain={r.primary_domain} name={r.name} />
                <span className="cell-main"><span className="t">{r.name}</span><span className="s">{r.industry || "Industry unknown"}{r.employees ? `, ${n0(r.employees)} employees` : ""}</span></span>
                <span className="clip mute">{r.segment_label}</span>
                <span className="num"><Tier tier={r.tier} judged={r.judged} />{r.judged && r.score !== null ? <small className="mute"> {r.score}</small> : null}</span>
                <span className="num mute">{pct(r.scored_out_of)}</span>
                <span className="cell-main">{r.over_capacity ? <Status kind="hold">Unassigned: no capacity</Status> : <span className="t" style={{ fontWeight: 450 }}>{r.owner || <span className="faint">Unassigned</span>}</span>}{r.owner ? <span className="s">{reasonWord(r.reason_code)}</span> : null}</span>
                <span className="num mute">{r.last_dest ? (r.last_meetings ? <Status kind="ok">Meeting</Status> : "No meeting") : ""}</span>
              </button>
            ))}
          </div>
          <div className="pager">
            <span className="mute">Page {data.page} of {data.pages}</span>
            <span className="pager-buttons">
              <button className="btn line sm" disabled={data.page <= 1} onClick={() => navigate(withParam("page", String(data.page - 1)))}>Previous</button>
              <button className="btn line sm" disabled={data.page >= data.pages} onClick={() => navigate(withParam("page", String(data.page + 1)))}>Next</button>
            </span>
          </div>
        </>
      ) : <Empty title="No accounts match" />}
    </div>
  );
}

export function MyBook() {
  const { data, error, reload } = useData<any>("/api/mybook");
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>My book</h1></div><Loading /></div>;
  const by = (t: string) => data.rows.filter((r: any) => r.tier === t);
  return (
    <div className="page">
      <div className="head"><h1>My book</h1></div>
      <div className="figs">
        <Fig value={n0(by("A").length)} label="Tier A" />
        <Fig value={n0(by("B").length)} label="Tier B" />
        <Fig value={n0(by("X").length)} label="Customers and open deals" />
      </div>
      {data.capacity ? <div style={{ maxWidth: 420 }}><Hours used={data.capacity.hours_required} of={data.capacity.hours_available} /></div> : null}
      {data.rows.length ? ["A", "B", "C", "X"].map((t) => by(t).length ? (
        <Section key={t} title={t === "X" ? "Customers and open deals" : `Tier ${t}`} count={by(t).length} icon={Books}>
          <div className="ledger wrap-names">
            <div className="row head" style={{ gridTemplateColumns: "28px minmax(0,1.4fr) minmax(120px,0.9fr) minmax(0,1fr) minmax(0,1fr)" }}><span /><span>Company</span><span>Score</span><span>Segment</span><span>Note</span></div>
            {by(t).slice(0, 120).map((r: any) => (
              <button key={r.id} className="row" style={{ gridTemplateColumns: "28px minmax(0,1.4fr) minmax(120px,0.9fr) minmax(0,1fr) minmax(0,1fr)" }} onClick={() => openSheet("company", r.id)}>
                <Logo domain={r.primary_domain} name={r.name} />
                <span className="cell-main"><span className="t">{r.name}</span><span className="s">{r.industry}</span></span>
                <span data-label="Score"><FitBand score={r.score} a={data.tiers?.A ?? 85} b={data.tiers?.B ?? 65} /></span>
                <span className="clip mute">{r.segment_label}</span>
                <span className="clip mute">{r.reason_code === "rule" ? "" : r.note || reasonWord(r.reason_code)}</span>
              </button>
            ))}
          </div>
        </Section>
      ) : null) : <Empty title="No accounts in your book" />}
      {Object.entries(data.stories).map(([k, s]: [string, any]) => (
        <Section key={k} title={s.label}>
          {s.status === "ok" ? <Story sentences={s.sentences} quotes={s.quotes} /> : <Status kind="none">No summary</Status>}
        </Section>
      ))}
    </div>
  );
}

/** Why a segment buys: the desk's sentences, each quoting the buyer's own words. */
export function Story({ sentences }: { sentences: any[]; quotes?: Record<string, any> }) {
  return (
    <div className="story">
      {sentences.map((s, i) => (
        <div key={i} className="story-s">
          <p>{s.text}</p>
        </div>
      ))}
    </div>
  );
}
