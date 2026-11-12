import type { ReactNode } from "react";
import { Status, money, pct, type Glyph } from "./lib";

// Parts this desk adds to Account Desk's shared set, in the same language: a rate with its range, a verdict, a tier,
// the tier mix of a group. Listed for Bryan in PROJECT-STATUS as new kinds of element.

/** A range of money, written once: "$1.2M to $3.4M". */
/** A money range in one unit, the high end's: "$1k to $12k", "Under $1k to $3.1M", never "$1,408 to $12k". */
export const moneyRange = (lo: number | null | undefined, hi: number | null | undefined) => {
  if (lo === null || lo === undefined) return "";
  const h = (hi || 0) / 100, l = lo / 100;
  const low = h >= 1_000_000 && l < 1_000_000 && l >= 1000 ? `$${Math.round(l / 1000)}k`
    : h >= 10_000 && l < 10_000 ? (l < 500 ? "Under $1k" : `$${Math.round(l / 1000)}k`) : money(lo);
  return low === money(hi) ? low : `${low} to ${money(hi)}`;
};

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
      <span className="val">{Math.round(used)} of {Math.round(of)} hours{over ? <strong> (over)</strong> : null}</span>
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
    <span className={`range${ends ? " with-ends" : ""}`} role="img" aria-label={`${label ?? ""}${pct(rate)}, ${pct(lo)} to ${pct(hi)}${other !== null && other !== undefined ? `, the rest ${pct(other)}` : ""}`}>
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
          <span className="range-val">{hi > 0 ? moneyRange(lo, hi) : k === "SOM" ? "No capacity" : "None"}</span>
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
  const shares = big.filter((t) => !t.muted).map((t) => t.aShare);
  const lo = Math.min(...shares, 1), hi = Math.max(...shares, 0);
  const tone = (a: number) => Math.round(12 + 46 * (hi > lo ? (a - lo) / (hi - lo) : 0.5));
  return (
    <div className="field" role="list" aria-label="SAM by segment">
      {big.map((t, i) => (
        <button key={t.key} role="listitem" type="button" onClick={() => onPick(t.key)} title={`${t.label}, ${t.value}`}
          className={`tile${t.muted ? " muted" : ""}${t.weight / total < 0.08 ? " narrow" : ""}`}
          style={{ flex: `${t.weight / total} 1 0`, ["--tone" as any]: t.muted ? 0 : tone(t.aShare), animationDelay: `${i * 40}ms` }}>
          <span className="tile-name">{t.weight / total < 0.08 ? t.label.split(", ").map((w, k) => <span key={k} style={{ display: "block" }}>{w}</span>) : t.label}</span>
          <span className="tile-val">{t.value}</span>
          {!t.muted ? <span className="tile-a">A {Math.round(100 * t.aShare)}%</span> : null}
        </button>
      ))}
      {small.length ? (
        <span role="listitem" className="tile smaller" style={{ flex: `${small.reduce((s, t) => s + t.weight, 0) / total} 1 0` }}
          title={`${smaller}: ${small.map((t) => `${t.label}, ${t.value}`).join("; ")}`}>
          <span className="tile-name">+{small.length}</span>
        </span>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- capacity, plan changes and fit, drawn as intervals

/** A person's month as a range: the band is the hours they hold today, the dashed stretch the hours still to come
 *  while they ramp, the ink tick the hours their book needs. A tick past the band is over. One scale for the team. */
export function CapacityRange({ needed, held, full, max }: { needed: number; held: number; full: number; max: number }) {
  const x = (v: number) => `${Math.max(0, Math.min(100, (100 * v) / Math.max(max, 1)))}%`;
  const over = needed > held + 0.05;
  const ramping = full - held > 0.5;
  return (
    <span className={`cap${over ? " over" : ""}`} role="img"
      aria-label={`Needs ${Math.round(needed)} hours, holds ${Math.round(held)}${ramping ? `, ${Math.round(full)} at full ramp` : ""}`}>
      <span className="range-line" aria-hidden="true">
        <i className="range-band" style={{ left: 0, width: x(held) }} />
        {ramping ? <i className="cap-ramp" style={{ left: x(held), width: `calc(${x(full)} - ${x(held)})` }} /> : null}
        <i className="range-point" style={{ left: x(needed) }} />
      </span>
      <span className="cap-val">{Math.round(needed)} of {Math.round(held)} h{over ? <strong> over</strong> : null}
        {ramping ? <small>{Math.round(full)} h at full ramp</small> : null}</span>
    </span>
  );
}

/** One person's book in the active plan (ring) and in the draft (tick), on one scale, with the change written. */
export function PlanShift({ was, now, max }: { was: number | null; now: number; max: number }) {
  const x = (v: number) => `${Math.max(0, Math.min(100, (100 * v) / Math.max(max, 1)))}%`;
  const d = was === null ? null : now - was;
  return (
    <span className="shift" role="img" aria-label={was === null ? `${now} in the draft, new to the plan` : `${was} now, ${now} in the draft`}>
      <span className="range-line" aria-hidden="true">
        {was !== null ? <i className="shift-span" style={{ left: x(Math.min(was, now)), width: x(Math.abs(now - was)) }} /> : null}
        {was !== null ? <i className="range-other" style={{ left: x(was) }} /> : null}
        <i className="range-point" style={{ left: x(now) }} />
      </span>
      <span className="shift-val">{now.toLocaleString("en-US")}
        <small>{d === null ? "new" : d === 0 ? "same" : `${d > 0 ? "+" : "−"}${Math.abs(d).toLocaleString("en-US")}`}</small></span>
    </span>
  );
}

/** Where an account's score sits against the tier lines: C, then B from the B line, then A from the A line. */
export function FitBand({ score, a, b }: { score: number | null | undefined; a: number; b: number }) {
  if (score === null || score === undefined) return <span className="faint small">Not judged</span>;
  return (
    <span className="fitband" role="img" aria-label={`Score ${score}; tier B from ${b}, tier A from ${a}`}>
      <span className="fit-line" aria-hidden="true">
        <i className="fit-zone b" style={{ left: `${b}%`, width: `${a - b}%` }} />
        <i className="fit-zone a" style={{ left: `${a}%`, width: `${100 - a}%` }} />
        <i className="range-point" style={{ left: `${Math.max(0, Math.min(100, score))}%` }} />
      </span>
      <span className="fit-val">{score}</span>
    </span>
  );
}

const wilson = (k: number, n: number): [number, number] => {
  if (!n) return [0, 0];
  const z = 1.96, p = k / n, d = 1 + (z * z) / n, c = p + (z * z) / (2 * n), m = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return [Math.max(0, (c - m) / d), Math.min(1, (c + m) / d)];
};

/** A test's two meeting rates on one track, each with its likely range: worked in ochre, held back in steel. */
export function Pair({ r, max = 0.3 }: { r: any; max?: number }) {
  const x = (v: number) => `${Math.max(0, Math.min(100, (100 * v) / max))}%`;
  const [wl, wh] = wilson(r.treated.meetings, r.treated.accounts);
  const [hl, hh] = wilson(r.holdout.meetings, r.holdout.accounts);
  return (
    <span className="pair" role="img" aria-label={`Worked ${pct(r.treated.rate)}, held back ${pct(r.holdout.rate)}`}>
      <span className="range-val">{pct(r.treated.rate)}<small>held back {pct(r.holdout.rate)}</small></span>
      <span className="range-line" aria-hidden="true">
        {r.holdout.accounts ? <i className="pair-band-held" style={{ left: x(hl), width: `calc(${x(hh)} - ${x(hl)})` }} /> : null}
        {r.treated.accounts ? <i className="range-band" style={{ left: x(wl), width: `calc(${x(wh)} - ${x(wl)})` }} /> : null}
        {r.holdout.accounts ? <i className="pair-held" style={{ left: x(r.holdout.rate) }} /> : null}
        <i className="range-point" style={{ left: x(r.treated.rate) }} />
      </span>
    </span>
  );
}
