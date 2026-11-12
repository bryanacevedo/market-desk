import { useState } from "react";
import { Flask } from "@phosphor-icons/react";
import { api } from "../api";
import { Empty, Failed, Loading, Section, Status, day, n0, pct, useBusy, useData } from "../lib";
import { RangeLine } from "../parts";
import { openSheet } from "../sheets";

const DECISION: Record<string, string> = { expand: "Expand proposed", drop: "Dropped", extend: "Extended" };

export function testState(t: any): [any, string] {
  if (t.status === "draft") return ["wait", "Draft"];
  if (t.status === "running" && !t.report.enough) return ["wait", "Needs more accounts"];
  if (!t.report.enough) return ["wait", "Needs more accounts"];
  return t.report.clear ? ["ok", "Clear difference"] : ["none", "No clear difference"];
}

export function Lift({ r }: { r: any }) {
  return (
    <div className="lift">
      <div className="lift-pair">
        <div><b>{pct(r.treated.rate)}</b><span>Worked</span><span className="mute">{n0(r.treated.meetings)} of {n0(r.treated.accounts)}</span></div>
        <div><b>{pct(r.holdout.rate)}</b><span>Held back</span><span className="mute">{n0(r.holdout.meetings)} of {n0(r.holdout.accounts)}</span></div>
      </div>
      {r.enough ? (
        <div className="lift-verdict">
          <span className="small">Difference: {Math.round(r.interval[0] * 100)} to {Math.round(r.interval[1] * 100)} points</span>
        </div>
      ) : <div className="small">Needs {n0(r.still_needed.holdout + r.still_needed.treated)} more accounts</div>}
    </div>
  );
}

export function Tests() {
  const { data, error, reload } = useData<any>("/api/tests");
  const me = useData<any>("/api/me").data;
  const [busy, run] = useBusy();
  const [segment, setSegment] = useState("");
  const [hyp, setHyp] = useState("");
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Tests</h1></div><Loading /></div>;
  const chosen = data.segments.find((s: any) => s.key === segment);
  const cols = "minmax(0,1.2fr) 110px minmax(200px,1.4fr) minmax(170px,1fr)";
  return (
    <div className="page">
      <div className="head"><h1>Tests</h1></div>
      {data.rows.length ? (
        <div className="ledger">
          <div className="row head" style={{ gridTemplateColumns: cols }}><span>Segment</span><span>Started</span><span>Meeting rate, worked vs held back</span><span>Result</span></div>
          {data.rows.map((t: any) => {
            const [g, w] = testState(t);
            return (
              <button key={t.id} className="row" style={{ gridTemplateColumns: cols }} onClick={() => openSheet("test", t.id)}>
                <span className="cell-main"><span className="t">{t.segment_label}</span><span className="s">{n0(t.members)} accounts</span></span>
                <span className="mute">{t.started_on ? day(t.started_on) : "Not started"}</span>
                <span data-label="Meeting rate, worked vs held back"><RangeLine rate={t.report.treated.rate} other={t.report.holdout.rate} max={0.3} /></span>
                <span className="cell-main"><Status kind={g}>{w}</Status>{t.decision ? <span className="s">{DECISION[t.decision]}</span> : null}</span>
              </button>
            );
          })}
        </div>
      ) : <Empty title="No tests yet" icon={Flask} />}
      {me?.user.role === "revops" ? (
        <Section title="New test">
          <div className="form-row" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,2fr) auto" }}>
            <label className="field"><span className="small mute">Segment</span>
              <select className="select" value={segment} onChange={(e) => setSegment(e.target.value)}>
                <option value="">Choose</option>
                {data.segments.map((s: any) => <option key={s.key} value={s.key}>{s.label}, {n0(s.eligible)} eligible</option>)}
              </select>
            </label>
            <label className="field"><span className="small mute">What we expect</span>
              <input className="input" value={hyp} onChange={(e) => setHyp(e.target.value)} maxLength={300} />
            </label>
            <button className="btn" disabled={busy || !segment || hyp.trim().length < 5}
              onClick={() => run(() => api("/api/tests", { method: "POST", body: { segment, hypothesis: hyp } }), "Test drafted.").then(() => { setHyp(""); })}>Draft it</button>
          </div>
          {chosen ? <div className="small mute">{n0(chosen.eligible)} eligible, {n0(data.cohort)} needed</div> : null}
        </Section>
      ) : null}
    </div>
  );
}
