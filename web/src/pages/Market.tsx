import { Failed, Fig, Loading, Seg, Status, n0, navigate, pct, useData, usePath, withParam } from "../lib";
import { MarketField, Nest, RangeLine, TierMix, moneyRange, moneyScale } from "../parts";
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
  const { data, error, reload } = useData<{ by: string; rows: Row[]; figures: any }>(`/api/market?by=${by}`);
  const me = useData<any>("/api/me").data;
  const waiting: { what: string; path: string }[] = me?.waiting || [];
  const head = (
    <>
      <div className="head">
        <h1>Market</h1>
        <Seg label="Rows" value={by === "segment" ? "segment" : "region"} options={[["segment", "Segments"], ["region", "Regions"]]}
          onChange={(v) => navigate(withParam("by", v === "region" ? "region" : null), true)} />
      </div>
      {waiting.length ? (
        <div className="notice waiting"><Status kind="wait">Waiting on you</Status>
          {waiting.map((w, i) => <button key={i} className="link" onClick={() => navigate(w.path)}>{w.what}</button>)}
        </div>
      ) : null}
    </>
  );
  if (error) return <div className="page">{head}<Failed error={error} retry={reload} /></div>;
  if (!data || data.by !== by) return <div className="page">{head}<Loading /></div>;
  const f = data.figures;
  const seg = by === "segment";
  const open = (k: string) => (seg ? openSheet("segment", k) : navigate(`/accounts?region=${encodeURIComponent(k)}`));
  const [floor, ceil] = moneyScale(data.rows.flatMap((r) => [r.tam_high, r.som_low, r.som_high]));
  const tiles = data.rows.map((r) => ({
    key: r.key, label: r.label, weight: r.sam_high || 0, value: moneyRange(r.sam_low, r.sam_high),
    aShare: r.fit_a / Math.max(1, r.universe_count), muted: r.key === "outside",
  }));
  const cols = "minmax(150px,1.2fr) 80px 80px minmax(150px,1.2fr) minmax(280px,2.4fr)" + (seg ? " minmax(150px,1.1fr)" : "");
  return (
    <div className="page">
      {head}
      <div className="figs">
        <Fig value={n0(f.companies)} label="Companies" />
        <Fig value={n0(f.in_profile)} label="Tier A or B" />
        <Fig value={n0(f.reachable)} label="Reachable, A or B" />
        <Fig value={moneyRange(f.som_low, f.som_high)} label="SOM, 12 months" />
      </div>
      <section>
        <MarketField tiles={tiles} onPick={open} smaller={seg ? "Smaller segments" : "Smaller regions"} />
        <div className="field-key"><span>Tile size: SAM</span><span>Darker: more tier A</span></div>
      </section>
      <div className="ledger market" role="table" aria-label={seg ? "Segments" : "Regions"}>
        <div className="row head" role="row" style={{ gridTemplateColumns: cols }}>
          <span>{seg ? "Segment" : "Region"}</span><span className="num">Companies</span><span className="num">Reachable</span>
          <span>Tiers</span><span>TAM, SAM, SOM</span>{seg ? <span>Win rate</span> : null}
        </div>
        {data.rows.map((r) => (
          <button key={r.key} className="row" role="row" style={{ gridTemplateColumns: cols }} onClick={() => open(r.key)}>
            <span className="cell-main"><span className="t">{r.label}</span>
              <span className="s">{r.coverage_share === null ? "No public count" : `${pct(Math.min(r.coverage_share, 1))} of public count`}</span></span>
            <span className="num" data-label="Companies">{n0(r.universe_count)}</span>
            <span className="num" data-label="Reachable">{n0(r.sam_count)}</span>
            <TierMix a={r.fit_a} b={r.fit_b} c={r.fit_c} x={r.fit_x} nj={r.not_judged} />
            <Nest floor={floor} ceil={ceil} rows={[["TAM", r.tam_low, r.tam_high], ["SAM", r.sam_low, r.sam_high], ["SOM", r.som_low, r.som_high]]} />
            {seg ? <span data-label="Win rate">{r.win_rate ? <RangeLine rate={r.win_rate.rate} low={r.win_rate.low} high={r.win_rate.high} /> : <span className="faint">No deals</span>}</span> : null}
          </button>
        ))}
      </div>
    </div>
  );
}
