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
      <span className="tm-key">{parts.filter(([, v]) => v).map(([k, v]) => <span key={k}><b>{k}</b>{v.toLocaleString("en-US")}</span>)}</span>
    </span>
  );
}

export function Tier({ tier, judged = true }: { tier: string; judged?: boolean | null }) {
  if (judged === false) return <Status kind="none">Not judged</Status>;
  return <span className={`tier tier-${tier.toLowerCase()}`}>{tier}</span>;
}

/** Used of allowed, as a bar with the numbers on it: "88 of 100 hours". */
export function Hours({ used, of }: { used: number; of: number }) {
  const over = used > of + 0.05;
  const w = of > 0 ? Math.min(1, used / of) : used > 0 ? 1 : 0;
  return (
    <span className={`hours${over ? " over" : ""}`}>
      <span className="track"><i style={{ width: `${(w * 100).toFixed(1)}%` }} /></span>
      <span className="val">{Math.round(used)} of {Math.round(of)} hours</span>
    </span>
  );
}

export function Field({ k, children }: { k: string; children: ReactNode }) {
  return <><dt>{k}</dt><dd>{children}</dd></>;
}

export const SEG_LABEL = (s: string | null | undefined, labels?: Record<string, string>) => (s && labels?.[s]) || s || "";
