import { ClockCounterClockwise, ListChecks, PencilSimpleLine, Scales } from "@phosphor-icons/react";
import { api } from "../api";
import { Bar, Empty, Failed, Fig, Loading, Section, Status, day, n0, useBusy, useData } from "../lib";
import { Verdict } from "../parts";
import { openSheet } from "../sheets";

export function RuleRows({ rules }: { rules: any[] }) {
  const kinds: [string, string][] = [["factors", "Adds to the score"], ["penalties", "Takes away"], ["excludes", "Never a fit"]];
  return (
    <div className="ledger">
      {kinds.map(([k, label]) => {
        const rs = rules.filter((r) => r.kind === k);
        if (!rs.length) return null;
        return (
          <div key={k} style={{ display: "contents" }}>
            <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) 56px 170px" }}><span>{label}</span><span className="num">Weight</span><span>Evidence</span></div>
            {rs.map((r) => (
              <button key={r.key} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 56px 170px" }}
                onClick={() => r.finding && openSheet("finding", r.finding.id)} disabled={!r.finding}>
                <span className="cell-main"><span className="t">{r.label}</span>{r.reason ? <span className="s">{r.reason}</span> : null}
                  {!r.travels ? <span className="s">Account Desk cannot read this rule</span> : null}</span>
                <span className="num">{r.weight === null || r.weight === undefined ? "" : k === "penalties" ? `−${r.weight}` : r.weight}</span>
                {r.finding ? <Verdict v={r.finding.verdict} /> : <Status kind="none">Hypothesis</Status>}
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}

export function Moves({ id }: { id: number }) {
  const { data, error, reload } = useData<any>(`/api/profile/versions/${id}/moves`);
  if (error) return <Failed error={error} retry={reload} />;
  if (!data) return <Loading rows={4} />;
  const max = Math.max(1, ...data.moves.map((m: any) => m.count));
  return (
    <div className="two">
      <Section title="What moves" count={data.total}>
        <div className="bars">
          {data.moves.slice(0, 8).map((m: any) => <Bar key={`${m.from}${m.to}`} label={`${m.from} to ${m.to}`} value={m.count} of={max} />)}
        </div>
        <div className="ledger" style={{ marginTop: 12 }}>
          {data.by_segment.slice(0, 6).map((s: any) => (
            <div key={s.segment} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}><span>{s.label}</span><span className="num">{n0(s.count)}</span></div>
          ))}
        </div>
      </Section>
      <Section title="Backtest">
        <div className="ledger">
          <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) repeat(3, 52px)" }}><span>Group</span><span className="num">A</span><span className="num">B</span><span className="num">C or X</span></div>
          {data.backtest.map((g: any) => {
            const t = Math.max(1, g.n);
            const s = (k: number) => `${Math.round((100 * k) / t)}%`;
            return (
              <div key={g.group} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) repeat(3, 52px)" }}>
                <span className="cell-main"><span className="t">{g.group}</span><span className="s">{n0(g.n)} companies</span></span>
                <span className="num">{s(g.mix.A)}</span><span className="num">{s(g.mix.B)}</span><span className="num">{s(g.mix.C + g.mix.X + g.mix["Not judged"])}</span>
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

export function Profile() {
  const { data, error, reload } = useData<any>("/api/profile");
  const [busy, run] = useBusy();
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Profile</h1></div><Loading /></div>;
  const p = data.published;
  return (
    <div className="page">
      <div className="head"><h1>Profile</h1></div>
      <div className="figs">
        <Fig value={`v${p.number}`} label="Published" />
        <Fig value={day(p.published_at)} label="Since" />
        <Fig value={p.tiers.A} label="Tier A from" />
        <Fig value={p.tiers.B} label="Tier B from" />
      </div>
      {data.job ? <div className="notice"><Status kind="wait">Waiting</Status>Rescoring every company</div> : null}
      <Section title="Published" icon={ListChecks}><RuleRows rules={p.rules} /></Section>
      {data.drafts.map((d: any) => (
        <div key={d.id} className="halo"><Section title={`Draft, version ${d.number}`} icon={PencilSimpleLine}
          right={<div className="actions">
            <button className="btn line sm" onClick={() => openSheet("version", d.id)}>Open</button>
            <button className="btn sm" disabled={busy || !d.can_publish}
              title={d.can_publish ? undefined : "A manager other than the author publishes"}
              onClick={() => run(() => api(`/api/profile/versions/${d.id}/publish`, { method: "POST" }), "Published. Every company is being rescored.")}>Publish</button>
          </div>}>
          <div className="small mute">{d.author}, {day(d.created_at)}. {d.note}</div>
          <Moves id={d.id} />
        </Section></div>
      ))}
      {!data.drafts.length ? <Empty title="No draft" icon={Scales} /> : null}
      <Section title="Versions" icon={ClockCounterClockwise}>
        <div className="ledger">
          {data.versions.map((v: any) => (
            <button key={v.id} className="row" style={{ gridTemplateColumns: "56px minmax(0,1fr) 120px 110px" }} onClick={() => openSheet("version", v.id)}>
              <span className="strong">v{v.number}</span>
              <span className="cell-main"><span className="t">{v.note}</span><span className="s">{v.author}{v.published_by ? `, published by ${v.published_by}` : ""}</span></span>
              <Status kind={v.status === "published" ? "ok" : v.status === "draft" ? "wait" : "off"}>{v.status === "published" ? "Published" : v.status === "draft" ? "Draft" : "Retired"}</Status>
              <span className="num mute">{day(v.published_at || v.created_at)}</span>
            </button>
          ))}
        </div>
      </Section>
    </div>
  );
}
