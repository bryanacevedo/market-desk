import { useState } from "react";
import { CheckSquare, Lightbulb } from "@phosphor-icons/react";
import { api } from "../api";
import { Empty, Failed, Loading, Section, Status, navigate, useBusy, useData } from "../lib";
import { RangeLine } from "../parts";
import { openSheet } from "../sheets";

export const KIND: Record<string, string> = {
  add_rule: "Add a rule", drop_rule: "Drop a rule", penalty: "Add a penalty", add_exclude: "Exclude",
  reweight: "Reweight", segment_expand: "Expand a segment", segment_drop: "Drop a segment",
};

/** A proposal's words: the model's two sentences, or its figures alone when the wording was withheld. */
export function ProposalWords({ p }: { p: any }) {
  if (p.sentences) return <div className="prop-words">{p.sentences.map((s: any, i: number) => <p key={i}>{s.text}</p>)}</div>;
  const f = p.findings[0];
  return (
    <dl className="kv small">
      <dt>Change</dt><dd>{p.change.field_label}: {p.change.value_label}</dd>
      {f ? <><dt>Win rate</dt><dd>{f.win_rate} ({f.range})</dd><dt>Others</dt><dd>{f.rest_win_rate}</dd><dt>Deals</dt><dd>{Number(f.opportunities).toLocaleString("en-US")}</dd></> : null}
    </dl>
  );
}

/** The evidence behind a proposal, drawn: the win rate (or, for a test, the meeting rate) against the others. */
function Evidence({ p }: { p: any }) {
  const f = p.findings[0];
  if (!f) return null;
  const num = (x: string) => (x ? Number(String(x).replace("%", "")) / 100 : null);
  const range = String(f.range || "").match(/(\d+)% to (\d+)%/);
  const test = !p.finding_ids.length;
  return (
    <dl className="kv prop-ev">
      <dt>{test ? "Worked, met" : "Win rate"}</dt>
      <dd><RangeLine rate={num(f.win_rate)} low={test || !range ? null : Number(range[1]) / 100} high={test || !range ? null : Number(range[2]) / 100}
        other={num(f.rest_win_rate)} /></dd>
      <dt>{test ? "Accounts" : "Deals"}</dt><dd>{Number(f.opportunities).toLocaleString("en-US")}</dd>
      {f.top_loss ? <><dt>Top loss</dt><dd>{f.top_loss[0].toUpperCase() + f.top_loss.slice(1)}</dd></> : null}
    </dl>
  );
}

export function Changes() {
  const { data, error, reload } = useData<any>("/api/changes");
  const me = useData<any>("/api/me").data;
  const [busy, run] = useBusy();
  const [picked, setPicked] = useState<number[]>([]);
  const [dismissing, setDismissing] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Changes</h1></div><Loading /></div>;
  const revops = me?.user.role === "revops";
  const toggle = (id: number) => setPicked((x) => (x.includes(id) ? x.filter((y) => y !== id) : [...x, id]));
  return (
    <div className="page">
      <div className="head">
        <h1>Changes</h1>
        {revops ? <button className="btn" disabled={busy || !picked.length}
          onClick={() => run(async () => { const r = await api<any>("/api/proposals/draft", { method: "POST", body: { ids: picked } }); setPicked([]); navigate(`/profile?sheet=version:${r.version}`); }, "Draft made.")}>
          Make a draft{picked.length ? ` of ${picked.length}` : ""}</button> : null}
      </div>
      <Section title="Open" count={data.open.length} icon={Lightbulb}>
        {data.open.length ? (
          <div className="props">
            {data.open.map((p: any, i: number) => (
              <div key={p.id} className={`prop${i === 0 ? " halo" : ""}`}>
                <div className="prop-top">
                  {revops ? <label><input type="checkbox" aria-label="Choose for a draft" checked={picked.includes(p.id)} onChange={() => toggle(p.id)} /></label> : null}
                  <button className="link-row" onClick={() => openSheet("proposal", p.id)}>
                    <span className="t prop-kind">{KIND[p.kind]}: {p.change.value_label}</span>
                  </button>
                  <span className="grow" />
                  {p.text_status === "withheld" ? <Status kind="none">Withheld</Status> : null}
                </div>
                <ProposalWords p={p} />
                <Evidence p={p} />
                <div className="prop-foot">
                  {p.findings.map((f: any) => p.finding_ids.length ? (
                    <button key={f.id} className="link small" onClick={() => openSheet("finding", f.id)}>{f.value}: {f.verdict}</button>
                  ) : <button key={f.id} className="link small" onClick={() => openSheet("test", p.test_ids[0])}>{f.value}: segment test</button>)}
                  <span className="grow" />
                  {dismissing === p.id ? (
                    <span className="actions">
                      <input className="input" style={{ width: 240 }} placeholder="Why dismiss?" aria-label="Reason" value={reason} autoFocus onChange={(e) => setReason(e.target.value)} />
                      <button className="btn line sm" disabled={busy || reason.trim().length < 3}
                        onClick={() => run(() => api(`/api/proposals/${p.id}/dismiss`, { method: "POST", body: { reason } }), "Dismissed.").then(() => { setDismissing(null); setReason(""); })}>Dismiss</button>
                      <button className="btn quiet sm" onClick={() => setDismissing(null)}>Cancel</button>
                    </span>
                  ) : <button className="btn quiet sm" onClick={() => setDismissing(p.id)}>Dismiss</button>}
                </div>
              </div>
            ))}
          </div>
        ) : <Empty title="Nothing open" icon={CheckSquare} />}
      </Section>
      {data.decided.length ? (
        <Section title="Decided" count={data.decided.length}>
          <div className="ledger">
            {data.decided.map((p: any) => (
              <button key={p.id} className="row" style={{ gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1.4fr) 130px" }} onClick={() => openSheet("proposal", p.id)}>
                <span className="cell-main"><span className="t">{KIND[p.kind]}</span><span className="s">{p.change.field_label}: {p.change.value_label}</span></span>
                <span className="said-quote clip">{p.status === "dismissed" ? p.reason : `In draft v${p.draft_number}`}</span>
                <Status kind={p.status === "dismissed" ? "off" : "ok"}>{p.status === "dismissed" ? "Dismissed" : "Made a draft"}</Status>
              </button>
            ))}
          </div>
        </Section>
      ) : null}
    </div>
  );
}
