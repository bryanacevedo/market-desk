import type { ReactNode } from "react";
import { Status, money, pct, type Glyph } from "./lib";

// Parts this desk adds to Account Desk's shared set, in the same language: a rate with its range, a verdict, a tier,
// the tier mix of a group. Listed for Bryan in PROJECT-STATUS as new kinds of element.

/** A range of money, written once: "$1.2M to $3.4M". */
export const moneyRange = (lo: number | null | undefined, hi: number | null | undefined) =>
  lo === null || lo === undefined ? "" : money(lo) === money(hi) ? money(lo) : `${money(lo)} to ${money(hi)}`;

/** A rate with its range in small type: 38% (34 to 42). */
export function Rate({ rate, low, high }: { rate: number | null | undefined; low?: number | null; high?: number | null }) {
  if (rate === null || rate === undefined) return <span className="faint">None</span>;
  return (
    <span className="rate">{pct(rate)}{low !== undefined && low !== null && high !== undefined && high !== null
      ? <small> ({Math.round(low * 100)} to {Math.round(high * 100)})</small> : null}</span>
  );
}

const VERDICT_GLYPH: Record<string, Glyph> = { clear_higher: "ok", clear_lower: "stop", not_clear: "none", too_few: "wait", explained_by_size: "half" };
export const VERDICT_WORD: Record<string, string> = {
  clear_higher: "Clearly higher", clear_lower: "Clearly lower", not_clear: "Not clear", too_few: "Too few to tell",
  explained_by_size: "Explained by size",
};
export function Verdict({ v }: { v: string }) {
  return <Status kind={VERDICT_GLYPH[v] || "none"}>{VERDICT_WORD[v] || v}</Status>;
}

/** The tier mix of a group of companies: one bar, a part per tier, each labelled with its count. */
export function TierMix({ a, b, c, x, nj }: { a: number; b: number; c: number; x: number; nj: number }) {
  const total = a + b + c + x + nj || 1;
  const parts: [string, number, string][] = [["A", a, "t-a"], ["B", b, "t-b"], ["C", c, "t-c"], ["X", x, "t-x"], ["NJ", nj, "t-nj"]];
  return (
    <span className="tiermix" role="img" aria-label={parts.map(([k, v]) => `${k === "NJ" ? "Not judged" : "Tier " + k} ${v}`).join(", ")}>
      <span className="tm-bar">{parts.map(([k, v, cls]) => (v ? <i key={k} className={cls} style={{ width: `${(100 * v) / total}%` }} /> : null))}</span>
      <span className="tm-key">{parts.filter(([, v]) => v).map(([k, v]) => <span key={k}><b>{k === "NJ" ? "Not judged" : k}</b>{v.toLocaleString("en-US")}</span>)}</span>
    </span>
  );
}

export function Tier({ tier, judged = true }: { tier: string; judged?: boolean | null }) {
  if (judged === false) return <Status kind="none">Not judged</Status>;
  return <span className={`tier tier-${tier.toLowerCase()}`}>{tier}</span>;
}

/** Used of allowed, as a bar with the numbers on it: "88 of 100 hours". Over 100% the bar runs past a tick at the
 *  allowance and the word Over says so, in ink, not in a status colour. */
export function Hours({ used, of }: { used: number; of: number }) {
  const over = used > of + 0.05;
  const scale = Math.max(of, used, 1);
  const w = used / scale;
  return (
    <span className={`hours${over ? " over" : ""}`}>
      <span className="track"><i style={{ width: `${(w * 100).toFixed(1)}%` }} />
        {over ? <b className="hours-tick" style={{ left: `${((of / scale) * 100).toFixed(1)}%` }} /> : null}</span>
      <span className="val">{over ? <strong>Over </strong> : null}{Math.round(used)} of {Math.round(of)} hours</span>
    </span>
  );
}

export function Field({ k, children }: { k: string; children: ReactNode }) {
  return <><dt>{k}</dt><dd>{children}</dd></>;
}

export const SEG_LABEL = (s: string | null | undefined, labels?: Record<string, string>) => (s && labels?.[s]) || s || "";

// ---------------------------------------------------------------- the signature: ranges as intervals

/** One scale for every win rate on every screen, so the same rate sits in the same place everywhere. */
export const RATE_MAX = 0.6;

/** A rate drawn as an interval on a 0 to `max` scale: the band from low to high, a tick at the point, a hollow ring
 *  at the comparison. The number is written beside it; the band's ends are written under it when asked. */
export function RangeLine({ rate, low, high, other, max = RATE_MAX, label, ends }: { rate: number | null | undefined; low?: number | null;
  high?: number | null; other?: number | null; max?: number; label?: string; ends?: boolean }) {
  if (rate === null || rate === undefined) return <span className="faint">None</span>;
  const x = (v: number) => `${Math.max(0, Math.min(100, (100 * v) / max))}%`;
  const lo = low ?? rate;
  const hi = high ?? rate;
  return (
    <span className={`range${ends ? " with-ends" : ""}`} role="img" aria-label={`${label ?? ""}${pct(rate)}, ${pct(lo)} to ${pct(hi)}${other !== null && other !== undefined ? `, others ${pct(other)}` : ""}`}>
      <span className="range-val">{pct(rate)}</span>
      <span className="range-line" aria-hidden="true">
        <i className="range-band" style={{ left: x(lo), width: `calc(${x(hi)} - ${x(lo)})` }} />
        {other !== null && other !== undefined ? <i className="range-other" style={{ left: x(other) }} /> : null}
        <i className="range-point" style={{ left: x(rate) }} />
        {ends ? <><small className="range-end" style={{ left: x(lo) }}>{pct(lo)}</small><small className="range-end hi" style={{ left: x(hi) }}>{pct(hi)}</small></> : null}
      </span>
    </span>
  );
}

const logPos = (v: number, lo: number, hi: number) => {
  const a = Math.log10(Math.max(v, lo)), b = Math.log10(lo), c = Math.log10(hi);
  return Math.max(0, Math.min(100, (100 * (a - b)) / (c - b)));
};

/** The floor and ceiling of a log money scale for a set of ranges: a little under the smallest low end above zero. */
export function moneyScale(values: (number | undefined)[]): [number, number] {
  const pos = values.filter((v): v is number => !!v && v > 0);
  const ceil = Math.max(...pos, 1);
  const floor = Math.max(Math.min(...pos, ceil) / 2, 1);
  return [floor, ceil];
}

/** TAM, SAM and SOM drawn on one log money scale, each a band from its low to its high, with its range written.
 *  A range of zero is the word None, with no mark. */
export function Nest({ rows, floor, ceil }: { rows: [string, number | undefined, number | undefined][]; floor: number; ceil: number }) {
  return (
    <span className="nest">
      {rows.map(([k, lo, hi]) => lo === undefined || hi === undefined ? null : (
        <span key={k} className="nest-row">
          <b>{k}</b>
          <span className="range-line" aria-hidden="true">
            {hi > 0 ? <i className="range-band" style={{ left: `${logPos(Math.max(lo, floor), floor, ceil)}%`, width: `${Math.max(1.5, logPos(hi, floor, ceil) - logPos(Math.max(lo, floor), floor, ceil))}%` }} /> : null}
          </span>
          <span className="range-val">{hi > 0 ? moneyRange(lo, hi) : "None"}</span>
        </span>
      ))}
    </span>
  );
}

/** The market as a field: one tile per segment, drawn exactly as wide as its reachable market (SAM, high end).
 *  Segments too small to draw are gathered into one tile that says so; a segment with none is left out. Each tile
 *  writes its share at tier A, which also sets its shade. */
export function MarketField({ tiles, onPick, smaller }: { tiles: { key: string; label: string; weight: number; aShare: number; value: string; muted?: boolean }[];
  onPick: (k: string) => void; smaller: string }) {
  const live = tiles.filter((t) => t.weight > 0);
  const total = live.reduce((s, t) => s + t.weight, 0) || 1;
  const big = live.filter((t) => t.weight / total >= 0.04);
  const small = live.filter((t) => t.weight / total < 0.04);
  return (
    <div className="field" role="list" aria-label="SAM by segment">
      {big.map((t, i) => (
        <button key={t.key} role="listitem" type="button" onClick={() => onPick(t.key)} title={`${t.label}, ${t.value}`}
          className={`tile${t.muted ? " muted" : ""}${t.weight / total < 0.08 ? " narrow" : ""}`}
          style={{ flex: `${t.weight / total} 1 0`, ["--tone" as any]: t.muted ? 0 : Math.round(8 + 34 * t.aShare), animationDelay: `${i * 40}ms` }}>
          <span className="tile-name">{t.label}</span>
          <span className="tile-val">{t.value}</span>
          {!t.muted ? <span className="tile-a">A {Math.round(100 * t.aShare)}%</span> : null}
        </button>
      ))}
      {small.length ? (
        <span role="listitem" className="tile smaller" style={{ flex: `${small.reduce((s, t) => s + t.weight, 0) / total} 1 0` }}
          title={small.map((t) => `${t.label}, ${t.value}`).join("; ")}>
          <span className="tile-name">{smaller}</span>
          <span className="tile-val">{small.length}</span>
        </span>
      ) : null}
    </div>
  );
}
