import { Failed, Fig, Loading, Seg, n0, navigate, pct, useData, usePath, withParam } from "../lib";
import { Rate, TierMix, moneyRange } from "../parts";
import { openSheet } from "../sheets";

type Row = {
  key: string; label: string; universe_count: number; fit_a: number; fit_b: number; fit_c: number; fit_x: number; not_judged: number;
  coverage_share: number | null; reachable_count: number; sam_count: number; owned: number; story: string | null;
  tam_low?: number; tam_high?: number; sam_low?: number; sam_high?: number; som_low?: number; som_high?: number;
  win_rate: { rate: number; low: number; high: number; opps: number } | null;
};

export function Market() {
  const [, params] = usePath();
  const by = params.get("by") === "region" ? "region_group" : "segment";
  const { data, error, reload } = useData<{ rows: Row[]; figures: any }>(`/api/market?by=${by}`);
  const head = (
    <div className="head">
      <h1>Market</h1>
      <Seg label="Rows" value={by === "segment" ? "segment" : "region"} options={[["segment", "Segments"], ["region", "Regions"]]}
        onChange={(v) => navigate(withParam("by", v === "region" ? "region" : null), true)} />
    </div>
  );
  if (error) return <div className="page">{head}<Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page">{head}<Loading /></div>;
  const f = data.figures;
  const seg = by === "segment";
  const cols = seg ? "minmax(150px,1.2fr) 70px minmax(170px,1.6fr) 74px 82px minmax(118px,1fr) minmax(118px,1fr) minmax(118px,1fr) 110px"
    : "minmax(150px,1.2fr) 70px minmax(170px,1.6fr) 74px 82px minmax(118px,1fr) minmax(118px,1fr) minmax(118px,1fr)";
  return (
    <div className="page">
      {head}
      <div className="figs">
        <Fig value={n0(f.companies)} label="Companies" />
        <Fig value={n0(f.in_profile)} label="Tier A or B" />
        <Fig value={n0(f.reachable)} label="Reachable, A or B" />
        {f.som_low !== undefined ? <Fig value={moneyRange(f.som_low, f.som_high)} label="SOM, 12 months" /> : null}
      </div>
      <div className="ledger market wide-table" role="table" aria-label={seg ? "Segments" : "Regions"}>
        <div className="row head" role="row" style={{ gridTemplateColumns: cols }}>
          <span>{seg ? "Segment" : "Region"}</span><span className="num">Companies</span><span>Tiers</span>
          <span className="num">Coverage</span><span className="num">Reachable</span><span className="num">TAM</span>
          <span className="num">SAM</span><span className="num">SOM, 12 months</span>{seg ? <span className="num">Win rate</span> : null}
        </div>
        {data.rows.map((r) => (
          <button key={r.key} className="row" role="row" style={{ gridTemplateColumns: cols }}
            onClick={() => (seg ? openSheet("segment", r.key) : navigate(`/accounts?region=${encodeURIComponent(r.key)}`))}>
            <span className="cell-main"><span className="t">{r.label}</span><span className="s">{n0(r.owned)} owned</span></span>
            <span className="num" data-label="Companies">{n0(r.universe_count)}</span>
            <TierMix a={r.fit_a} b={r.fit_b} c={r.fit_c} x={r.fit_x} nj={r.not_judged} />
            <span className="num" data-label="Coverage">{r.coverage_share === null ? <span className="faint">Unknown</span> : pct(Math.min(r.coverage_share, 1))}</span>
            <span className="num" data-label="Reachable">{n0(r.sam_count)}</span>
            <span className="num" data-label="TAM">{moneyRange(r.tam_low, r.tam_high)}</span>
            <span className="num" data-label="SAM">{moneyRange(r.sam_low, r.sam_high)}</span>
            <span className="num" data-label="SOM">{moneyRange(r.som_low, r.som_high)}</span>
            {seg ? <span className="num" data-label="Win rate">{r.win_rate ? <Rate rate={r.win_rate.rate} low={r.win_rate.low} high={r.win_rate.high} /> : <span className="faint">No deals</span>}</span> : null}
          </button>
        ))}
      </div>
    </div>
  );
}
