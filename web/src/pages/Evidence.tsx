import { Empty, Failed, Fig, Loading, Section, Seg, money, n0, navigate, pct, useData, usePath, withParam } from "../lib";
import { Rate, Verdict } from "../parts";
import { openSheet } from "../sheets";

const monthsBetween = (a: string, b: string) => Math.round((new Date(b).getTime() - new Date(a).getTime()) / (30.44 * 86400000));

const VERDICTS: [string, string][] = [["all", "All"], ["clear", "Clear"], ["explained_by_size", "Explained by size"], ["not_clear", "Not clear"], ["too_few", "Too few"]];

export function Evidence() {
  const [, params] = usePath();
  const verdict = params.get("verdict") || "all";
  const trait = params.get("trait") || "";
  const { data, error, reload } = useData<any>("/api/evidence");
  const me = useData<any>("/api/me").data;
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Evidence</h1></div><Loading /></div>;
  const rows = (data.rows as any[]).filter((r) =>
    (verdict === "all" || (verdict === "clear" ? r.verdict.startsWith("clear") : r.verdict === verdict)) && (!trait || r.trait === trait));
  const clear = data.rows.filter((r: any) => r.verdict.startsWith("clear")).length;
  const cols = "minmax(160px,1.3fr) 64px 132px 64px 120px 84px 150px";
  return (
    <div className="page">
      <div className="head">
        <h1>Evidence</h1>
      </div>
      <div className="figs">
        <Fig value={`${monthsBetween(data.run.window_start, data.run.window_end)}`} unit=" months" label="Closed in the last" />
        <Fig value={n0(data.run.deals)} label="Deals" />
        <Fig value={n0(data.run.tested)} label="Values tested" />
        <Fig value={clear} label="Clear" />
      </div>
      {data.changes.length ? (
        <Section title="Since the last run" count={data.changes.length}>
          <div className="ledger">
            {data.changes.map((c: any) => (
              <button key={c.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }} onClick={() => openSheet("finding", c.id)}>
                <span className="t">{c.value_label}</span><Verdict v={c.verdict} />
              </button>
            ))}
          </div>
        </Section>
      ) : null}
      <div className="toolbar">
        <Seg label="Verdict" value={verdict} options={VERDICTS} onChange={(v) => navigate(withParam("verdict", v === "all" ? null : v), true)} />
        <select className="select" aria-label="Trait" value={trait} style={{ width: 200 }}
          onChange={(e) => navigate(withParam("trait", e.target.value || null), true)}>
          <option value="">Every trait</option>
          {data.traits.map(([k, l]: [string, string]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>
      {rows.length ? (
        <div className="ledger wide-table">
          <div className="row head" style={{ gridTemplateColumns: cols }}>
            <span>Trait</span><span className="num">Deals</span><span className="num">Win rate</span><span className="num">Others</span>
            <span className="num">Won-deal cycle</span><span className="num">{me?.money ? "Deal size" : ""}</span><span>Verdict</span>
          </div>
          {rows.map((r: any) => (
            <button key={r.id} className="row" style={{ gridTemplateColumns: cols }} onClick={() => openSheet("finding", r.id)}>
              <span className="cell-main"><span className="t">{r.value}</span><span className="s">{r.trait_label}</span></span>
              <span className="num" data-label="Deals">{n0(r.opps)}</span>
              <span className="num" data-label="Win rate"><Rate rate={r.rate} low={r.low} high={r.high} /></span>
              <span className="num" data-label="Others">{pct(r.rest_rate)}</span>
              <span className="num" data-label="Won-deal cycle">{r.cycle ? `${Math.round(r.cycle.median)} days` : <span className="faint">Too few</span>}</span>
              <span className="num" data-label={me?.money ? "Deal size" : undefined}>{me?.money ? money(r.acv_median) : ""}</span>
              <Verdict v={r.verdict} />
            </button>
          ))}
        </div>
      ) : <Empty title="No findings match" />}
    </div>
  );
}
