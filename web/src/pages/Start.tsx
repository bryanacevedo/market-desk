import type { MouseEvent } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import { Section, navigate, say, useData } from "../lib";
import { TIPS } from "../tips";

/** Where the buyer path ends: Bryan's decision (2026-11-17), a mailto with a subject so the message says which demo it came from. */
export const CONTACT_URL = "mailto:bryan@leandrive.io?subject=Market%20Desk%20demo";

export const VALUE_LINE = "Market Desk shows which companies are worth selling to, how big that market is, and who should work which accounts.";

/** The one best moment in the data and where to see it, from /api/start. */
export type Best = { id: number; label: string; trait: string; rate: number; rest_rate: number; opps: number } | null;

export const pc = (x: number) => `${Math.round(x * 100)}%`;
export const bestSentence = (b: NonNullable<Best>) => `${b.label} wins ${pc(b.rate)} of its deals; every other deal wins ${pc(b.rest_rate)}.`;

/** The first screen's value line and its one first step. */
export function FirstStep({ best }: { best: Best }) {
  return (
    <section className="first-step" aria-label="What this desk is for">
      <p className="value-line">{VALUE_LINE}</p>
      <div className="first-step-row">
        {best ? (
          <>
            <button className="btn" onClick={() => navigate(`/changes?sheet=finding:${best.id}`)}>See the clearest gap in the deals<ArrowRight size={16} aria-hidden="true" /></button>
            <span className="small mute">{bestSentence(best)}</span>
          </>
        ) : <button className="btn" onClick={() => navigate("/changes")}>See what the deals say</button>}
        <a className="link small" href="/start" onClick={(e) => { e.preventDefault(); navigate("/start"); }}>Take the tour</a>
      </div>
    </section>
  );
}

const TERMS: [string, string][] = [
  ["ICP", "ICP"], ["TAM, SAM, SOM", "TAM, SAM, SOM"], ["Tier", "Tier"], ["Reachable", "Reachable"], ["Held back", "Held back"],
  ["Band", "Band"], ["Hollow tick", "Hollow tick"], ["Hypothesis", "Hypothesis"], ["Make a draft", "Make a draft"], ["Roll back", "Roll back"],
  ["Territory rule", "Territory rule"], ["Unassigned: no capacity", "Unassigned: no capacity"], ["Handoffs", "Handoffs"], ["Acting as", "Acting as"],
];

export function Start() {
  const best = useData<{ best: Best }>("/api/start").data?.best ?? null;
  const go = (to: string) => (e: MouseEvent) => { e.preventDefault(); navigate(to); };
  const step = (to: string, name: string, what: string) => (
    <li><a href={to.split("?")[0]} onClick={go(to)}><b>{name}</b></a> {what}</li>
  );
  return (
    <div className="page start">
      <div className="head"><h1>Start here</h1></div>
      <p className="value-line">{VALUE_LINE}</p>
      <div className="paths">
        <Section title="If you are judging the work">
          <ol className="steps">
            {step("/", "Market", "gives the market as ranges, each with a low and a high estimate.")}
            {best ? step(`/changes?sheet=finding:${best.id}`, "The clearest gap", `is ${best.label}: it wins ${pc(best.rate)} of its deals, every other deal wins ${pc(best.rest_rate)}. The page says how sure it is.`) : step("/changes", "Changes", "lists what the deals suggest changing, with the evidence beside each.")}
            {step("/evidence", "Evidence", "shows every trait compared, including the ones with too few deals to tell.")}
            {step("/profile", "ICP", "changes only through a draft that a second person publishes.")}
            {step("/territories", "Territories", "shows who has the hours, and flags a tier A account nobody has hours for.")}
          </ol>
        </Section>
        <Section title="If you would use it">
          <ol className="steps">
            {step("/", "Market", "shows how big your market is and how much of it a plan can reach.")}
            {step("/evidence", "Evidence", "shows which kinds of company win more often than the rest.")}
            {step("/changes", "Changes", "turns what the evidence shows into a draft profile you can publish.")}
            {step("/territories", "Territories", "splits accounts between people by the hours they have.")}
            {step("/handoffs", "Handoffs", "makes the account files your outreach tool reads.")}
          </ol>
          <p className="next-step"><b>Next step.</b> <a className="link" href={CONTACT_URL}>Write to Bryan about your own data</a>.</p>
        </Section>
      </div>
      <Section title="Words used here">
        <dl className="glossary">
          {TERMS.map(([k, label]) => TIPS[k] ? <div key={k}><dt>{label}</dt><dd>{say(TIPS[k])}</dd></div> : null)}
        </dl>
      </Section>
    </div>
  );
}
