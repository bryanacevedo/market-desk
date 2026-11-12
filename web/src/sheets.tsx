import { useEffect, useRef, type ReactNode } from "react";
import {
  ArrowLeft, ArrowsLeftRight, BookOpen, Buildings, ChartPieSlice, Database, Flask, Lightbulb, ListChecks, Scales, UserCircle, X,
} from "@phosphor-icons/react";
import { api } from "./api";
import { Logo } from "./marks";
import { Bar, Empty, Failed, Fig, Loading, Section, Status, day, money, n0, navigate, pct, useBusy, useData } from "./lib";
import { Hours, Rate, Tier, TierMix, Verdict, moneyRange } from "./parts";

// ---------------------------------------------------------------- the sheet frame (Account Desk's, with this desk's kinds)

export function openSheet(kind: string, id: number | string) {
  const cur = new URLSearchParams(window.location.search).get("sheet");
  const u = new URL(window.location.href);
  u.searchParams.set("sheet", `${kind}:${id}`);
  if (cur && cur !== `${kind}:${id}`) u.searchParams.set("from", cur); else u.searchParams.delete("from");
  navigate(u.pathname + "?" + u.searchParams.toString());
}

export function closeSheet() {
  const u = new URL(window.location.href);
  u.searchParams.delete("sheet");
  u.searchParams.delete("from");
  navigate(u.pathname + (u.searchParams.toString() ? "?" + u.searchParams.toString() : ""));
}

const KIND: Record<string, { label: string; icon: typeof X }> = {
  segment: { label: "Segment", icon: ChartPieSlice }, finding: { label: "Finding", icon: Scales },
  company: { label: "Company", icon: Buildings }, person: { label: "Person", icon: UserCircle },
  version: { label: "Profile version", icon: ListChecks }, move: { label: "Plan move", icon: ArrowsLeftRight },
  test: { label: "Test", icon: Flask }, proposal: { label: "Proposal", icon: Lightbulb },
  book: { label: "Book", icon: BookOpen }, source: { label: "Source", icon: Database },
};

// The sheet's title names the thing, so the header carries only the kind; `crumb` is kept for the call sites' clarity.
function Frame({ kind, children, foot }: { kind: string; crumb?: ReactNode; children: ReactNode; foot?: ReactNode }) {
  const k = KIND[kind];
  const KIcon = k.icon;
  const from = new URLSearchParams(window.location.search).get("from");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeSheet(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus?.({ focusVisible: false } as FocusOptions); };
  }, []);
  const back = () => {
    if (!from) return;
    const u = new URL(window.location.href);
    u.searchParams.set("sheet", from);
    u.searchParams.delete("from");
    navigate(u.pathname + "?" + u.searchParams.toString());
  };
  return (
    <>
      <div className="scrim" onClick={closeSheet} aria-hidden="true" />
      <aside className={`sheet kind-${kind}`} role="dialog" aria-modal="true" aria-label={k.label} tabIndex={-1} ref={ref}>
        <div className="sheet-top">
          {from ? <button className="iconbtn" onClick={back} aria-label="Back"><ArrowLeft size={18} /></button> : null}
          <div className="sheet-kind"><span className="kind-mark" aria-hidden="true"><KIcon size={15} weight="bold" /></span>{k.label}</div>
          <span className="grow" />
          <button className="iconbtn" onClick={closeSheet} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="sheet-body">{children}</div>
        {foot ? <div className="sheet-foot">{foot}</div> : null}
      </aside>
    </>
  );
}

export function SheetHost() {
  const params = new URLSearchParams(window.location.search);
  const sheet = params.get("sheet");
  if (!sheet) return null;
  const i = sheet.indexOf(":");
  const kind = sheet.slice(0, i);
  const id = sheet.slice(i + 1);
  const P: Record<string, (p: { id: string }) => JSX.Element> = {
    segment: SegmentSheet, finding: FindingSheet, company: CompanySheet, person: PersonSheet, version: VersionSheet,
    move: MoveSheet, test: TestSheet, proposal: ProposalSheet, book: BookSheet, source: SourceSheet,
  };
  const C = P[kind];
  return C ? <C key={sheet} id={id} /> : null;
}

function Wrap({ kind, path, children }: { kind: string; path: string; children: (d: any) => ReactNode }) {
  const { data, error, reload } = useData<any>(path);
  if (error) return <Frame kind={kind}><Failed error={error} retry={reload} /></Frame>;
  if (!data) return <Frame kind={kind}><Loading rows={5} /></Frame>;
  return <>{children(data)}</>;
}

const Title = ({ children, sub }: { children: ReactNode; sub?: ReactNode }) => (
  <div className="who"><div><div className="sheet-title">{children}</div>{sub ? <div className="mute small">{sub}</div> : null}</div></div>
);

// ---------------------------------------------------------------- Segment

const QUOTE_KIND: Record<string, string> = { reason_to_buy: "Why", objection: "Objection", competitor: "Competitor" };

function SegmentSheet({ id }: { id: string }) {
  return (
    <Wrap kind="segment" path={`/api/segments/${id}`}>{(d) => {
      const z = d.sizing;
      const f = d.finding;
      return (
        <Frame kind="segment" crumb={d.label}>
          <Title sub={d.definition.join(", ")}>{d.label}</Title>
          {z ? (
            <div className="figs">
              <Fig sm value={n0(z.universe_count)} label="Companies" />
              <Fig sm value={n0(z.fit_a + z.fit_b)} label="Tier A or B" />
              <Fig sm value={n0(z.sam_count)} label="Reachable" />
              {f ? <Fig sm value={pct(f.rate)} label="Win rate" /> : null}
            </div>
          ) : null}
          {z ? <Section title="Tiers"><TierMix a={z.fit_a} b={z.fit_b} c={z.fit_c} x={z.fit_x} nj={z.not_judged} /></Section> : null}
          <Section title="Why they buy">
            {d.story?.status === "ok" ? (
              <div className="story">{d.story.sentences.map((s: any, i: number) => <p key={i}>{s.text}</p>)}</div>
            ) : d.story ? <Status kind="none">Withheld</Status> : null}
            <div className="quotes">{d.quotes.slice(0, 4).map((q: any) => (
              <div key={q.id} className="said-q"><span className="said-kind">{QUOTE_KIND[q.kind]}</span><div className="quote small">{q.text}</div></div>
            ))}</div>
          </Section>
          {d.roles.length ? (
            <Section title="Roles on won deals">
              <div className="ledger">
                <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) 70px 70px" }}><span>Role</span><span className="num">On deal</span><span className="num">Signed</span></div>
                {d.roles.map((r: any) => <div key={r.persona} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 70px 70px" }}><span>{r.persona}</span><span className="num">{pct(r.share)}</span><span className="num">{pct(r.signer)}</span></div>)}
              </div>
            </Section>
          ) : null}
          {d.losses?.length ? (
            <Section title="Why it was lost">
              <div className="bars">{d.losses.map((l: any) => <Bar key={l.code} label={l.code.replace(/_/g, " ").replace(/^\w/, (c: string) => c.toUpperCase())} value={l.share} of={1} shown={pct(l.share)} />)}</div>
            </Section>
          ) : null}
          {z && z.tam_low !== undefined ? (
            <Section title="Sizing">
              <dl className="kv">
                <dt>TAM</dt><dd>{moneyRange(z.tam_low, z.tam_high)}</dd>
                <dt>SAM</dt><dd>{moneyRange(z.sam_low, z.sam_high)}</dd>
                <dt>SOM, 12 months</dt><dd>{moneyRange(z.som_low, z.som_high)}</dd>
                <dt>Deal size</dt><dd>{money(z.acv_basis.p25)} to {money(z.acv_basis.p75)}{z.acv_basis.from === "overall" ? <span className="mute">, all segments</span> : null}</dd>
                <dt>Win rate range for sizing</dt><dd>{pct(z.win_rate_basis.low)} to {pct(z.win_rate_basis.high)}</dd>
                <dt>Worked accounts that became deals</dt><dd>{pct(z.capacity_basis.opp_low)} to {pct(z.capacity_basis.opp_high)}</dd>
                <dt>Accounts the plan can work</dt><dd>{n0(z.capacity_basis.capacity_accounts)}</dd>
              </dl>
            </Section>
          ) : null}
          {d.coverage.length ? (
            <Section title="Data coverage">
              <div className="bars">{d.coverage.map((c: any) => <Bar key={c.field} label={c.field === "pricing_model" ? "Pricing model" : c.field === "tech" ? "Technology" : "Industry"} value={c.filled} of={1} shown={pct(c.filled)} />)}</div>
            </Section>
          ) : null}
          {d.tests.length ? (
            <Section title="Tests">
              <div className="ledger">{d.tests.map((t: any) => (
                <button key={t.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }} onClick={() => openSheet("test", t.id)}>
                  <span className="cell-main"><span className="t">Segment test</span><span className="s">{day(t.started_on)} to {day(t.ends_on)}</span></span><Status kind={t.status === "running" ? "go" : "ok"}>{t.status === "running" ? "Running" : "Read"}</Status>
                </button>
              ))}</div>
            </Section>
          ) : null}
          <div className="actions"><button className="btn sm" onClick={() => { closeSheet(); navigate(`/accounts?segment=${d.key}`); }}>Accounts in this segment</button></div>
        </Frame>
      );
    }}</Wrap>
  );
}

// ---------------------------------------------------------------- Finding

const LOSS: Record<string, string> = { price: "Price", timing: "Timing", no_decision: "No decision", competitor: "Competitor",
  missing_feature: "Missing feature", compliance: "Compliance", champion_left: "Champion left", bad_fit: "Bad fit", other: "Other" };

function FindingSheet({ id }: { id: string }) {
  return (
    <Wrap kind="finding" path={`/api/findings/${id}`}>{(f) => (
      <Frame kind="finding" crumb={f.trait_label}>
        <Title sub={f.trait_label}>{f.value}</Title>
        <Verdict v={f.verdict} />
        {f.trait === "segment" && f.segment_key ? <div className="actions"><button className="btn line sm" onClick={() => openSheet("segment", f.segment_key)}>Open the segment</button></div> : null}
        <div className="figs">
          <Fig sm value={n0(f.opps)} label="Deals" />
          <Fig sm value={pct(f.rate)} label="Win rate" />
          <Fig sm value={pct(f.rest_rate)} label="Others" />
          {f.cycle ? <Fig sm value={`${Math.round(f.cycle.median)}`} unit=" days" label="Won-deal cycle" /> : null}
        </div>
        <dl className="kv">
          <dt>Win rate range</dt><dd><Rate rate={f.rate} low={f.low} high={f.high} /></dd>
          <dt>Others</dt><dd>{n0(f.rest_opps)} deals</dd>
          {f.cycle ? <><dt>Cycle range</dt><dd>{Math.round(f.cycle.low)} to {Math.round(f.cycle.high)} days</dd></> : null}
          {f.acv_median !== undefined && f.acv_median !== null ? <><dt>Deal size</dt><dd>{money(f.acv_median)} ({money(f.acv_p25)} to {money(f.acv_p75)})</dd></> : null}
          {f.churn !== null ? <><dt>Left within a year</dt><dd>{pct(f.churn)} of {n0(f.churn_n)}</dd></> : null}
        </dl>
        <Section title="By company size">
          <div className="ledger">
            <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) 70px 80px 80px" }}><span>Employees</span><span className="num">Deals</span><span className="num">Win rate</span><span className="num">The rest</span></div>
            {f.strata.map((s: any) => (
              <div key={s.size_band} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 70px 80px 80px" }}>
                <span>{s.size_band}</span><span className="num">{n0(s.opps)}</span>
                <span className="num">{s.opps ? pct(s.wins / s.opps) : ""}</span><span className="num">{s.rest_opps ? pct(s.rest_wins / s.rest_opps) : ""}</span>
              </div>
            ))}
          </div>
        </Section>
        {f.losses.length ? (
          <Section title="Why it was lost">
            <div className="bars">{f.losses.map((l: any) => <Bar key={l.code} label={LOSS[l.code]} value={l.share} of={1} shown={pct(l.share)} />)}</div>
          </Section>
        ) : null}
        <Section title="The deals" count={f.deal_count}>
          <div className="ledger scrolly">
            {f.deals.slice(0, 100).map((d: any) => (
              <button key={d.id} className="row" style={{ gridTemplateColumns: "24px minmax(0,1fr) 90px 80px" }} onClick={() => openSheet("company", d.company)}>
                <Logo domain={d.primary_domain} name={d.name} size={24} />
                <span className="cell-main"><span className="t">{d.name}</span><span className="s">{day(d.closed_at)}{d.loss_code ? `, ${LOSS[d.loss_code].toLowerCase()}` : ""}</span></span>
                <Status kind={d.outcome === "won" ? "ok" : "off"}>{d.outcome === "won" ? "Won" : "Lost"}</Status>
                <span className="num">{money(d.amount_cents)}</span>
              </button>
            ))}
          </div>
        </Section>
      </Frame>
    )}</Wrap>
  );
}

// ---------------------------------------------------------------- Company

const PRICING: Record<string, string> = { usage: "Usage-based", seat: "Per seat", transaction: "Per transaction", mixed: "Mixed", unknown: "Unknown" };
const SOURCE_WORD: Record<string, string> = { firmographics: "Company data vendor", technographics: "Technology vendor", funding_db: "Funding database", model: "AI, from the description", crm: "CRM" };
const FIELD: Record<string, string> = { industry: "Industry", employees: "Employees", revenue_band: "Revenue", pricing_model: "Pricing model", tech: "Technology" };

function CompanySheet({ id }: { id: string }) {
  return (
    <Wrap kind="company" path={`/api/companies/${id}`}>{(c) => {
      const f = c.fit;
      return (
        <Frame kind="company" crumb={c.name}>
          <div className="who"><Logo domain={c.domain} name={c.name} size={44} /><div><div className="sheet-title">{c.name}</div><div className="mute small">{c.domain}, {c.country}</div></div></div>
          {f ? (
            <div className="figs">
              <Fig sm value={f.judged ? f.tier : "Not judged"} label={`Tier, v${f.version}`} />
              {f.judged && f.score !== null ? <Fig sm value={f.score} label="Score" /> : null}
              <Fig sm value={pct(f.scored_out_of)} label="Of the profile known" />
            </div>
          ) : null}
          {f ? (
            <Section title="Fit">
              {f.excluded ? <div className="notice">{f.excluded}</div> : null}
              <div className="ledger">
                <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) 90px 50px" }}><span>Rule</span><span /><span className="num">Points</span></div>
                {(f.breakdown.factors || []).map((x: any, i: number) => (
                  <div key={i} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 90px 50px" }}>
                    <span>{x.label}</span>
                    <span className="mute">{x.matched === null ? "Unknown" : x.matched ? (x.weight < 0 ? "Penalty" : "Matches") : "Misses"}</span>
                    <span className="num">{x.contribution ? Math.round(x.contribution) : ""}</span>
                  </div>
                ))}
                {(f.breakdown.not_applied || []).map((x: any, i: number) => (
                  <div key={`na${i}`} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}><span>{x.reason}</span><span className="mute">Not applied: read by AI</span></div>
                ))}
              </div>
              <div className="small mute">{f.segment_label}</div>
            </Section>
          ) : null}
          {c.owner ? (
            <Section title="Owner">
              <dl className="kv"><dt>Owner</dt><dd>{c.owner.id ? <button className="link" onClick={() => openSheet("person", c.owner.id)}>{c.owner.name}</button> : "Unassigned"}</dd>
                <dt>Why</dt><dd>{({ rule: "Territory rule", existing_owner: "Customer", open_deal: "Open deal", balance_move: "Moved to balance", manual: "Moved by hand" } as any)[c.owner.reason] || c.owner.reason}</dd>
                {c.owner.note ? <><dt>Note</dt><dd>{c.owner.note}</dd></> : null}
                {c.owner.moved_from ? <><dt>From</dt><dd>{c.owner.moved_from}</dd></> : null}</dl>
            </Section>
          ) : null}
          <Section title="Fields">
            <div className="ledger">
              {c.fields.map((x: any, i: number) => (
                <div key={i} className="row" style={{ gridTemplateColumns: "110px minmax(0,1fr) minmax(0,1fr)" }}>
                  <span className="mute">{FIELD[x.field] || x.field}</span>
                  <span className="clip">{Array.isArray(x.value) ? x.value.join(", ") || "None" : typeof x.value === "number" ? x.value.toLocaleString("en-US") : PRICING[x.value] || String(x.value)}</span>
                  <span className="cell-main"><span className="s">{SOURCE_WORD[x.source] || x.source_label}, {day(x.observed_at)}</span>{x.quote ? <span className="s">{x.quote}</span> : null}</span>
                </div>
              ))}
            </div>
          </Section>
          {c.history.length ? (
            <Section title="Tier by version">
              <div className="ledger">{c.history.map((h: any) => (
                <div key={h.number} className="row" style={{ gridTemplateColumns: "60px minmax(0,1fr) 60px" }}><span>v{h.number}</span><Tier tier={h.tier} judged={h.judged} /><span className="num">{h.score ?? ""}</span></div>
              ))}</div>
            </Section>
          ) : null}
          {c.deals.length ? (
            <Section title="Deals">
              <div className="ledger">{c.deals.map((d: any) => (
                <div key={d.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 90px 80px" }}>
                  <span className="cell-main"><span className="t">{d.kind === "new" ? "New business" : "Expansion"}</span><span className="s">{day(d.created_at)}{d.closed_at ? ` to ${day(d.closed_at)}` : ""}</span></span>
                  <Status kind={d.outcome === "won" ? "ok" : d.outcome === "open" ? "wait" : "off"}>{d.outcome === "won" ? "Won" : d.outcome === "open" ? d.stage : "Lost"}</Status>
                  <span className="num">{money(d.amount_cents)}</span>
                </div>
              ))}</div>
            </Section>
          ) : null}
          {c.results.length ? (
            <Section title="From the desks">
              <div className="ledger">{c.results.map((r: any) => (
                <div key={r.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 80px 90px" }}>
                  <span className="cell-main"><span className="t">{r.destination === "events_desk" ? "Events Desk" : r.held_back ? "Held back" : "Account Desk"}</span><span className="s">{day(r.period_start)} to {day(r.period_end)}</span></span>
                  <span className="num" data-label="Meetings">{r.meetings}</span><span className="num" data-label="Deals opened">{r.opportunities}</span>
                </div>
              ))}</div>
            </Section>
          ) : null}
          {c.tests.length ? (
            <Section title="Tests">
              <div className="ledger">{c.tests.map((t: any) => (
                <button key={t.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }} onClick={() => openSheet("test", t.id)}>
                  <span>{t.segment_label}</span><Status kind={t.grp === "held_back" ? "none" : "ok"}>{t.grp === "held_back" ? "Held back" : "Worked"}</Status>
                </button>
              ))}</div>
            </Section>
          ) : null}
          {c.description ? <Section title="Description"><div className="small">{c.description}</div></Section> : null}
        </Frame>
      );
    }}</Wrap>
  );
}

// ---------------------------------------------------------------- Person

function PersonSheet({ id }: { id: string }) {
  return (
    <Wrap kind="person" path={`/api/people/${id}`}>{(p) => (
      <Frame kind="person" crumb={p.name}>
        <Title sub={`${p.role === "ae" ? "AE" : p.role === "sdr" ? "SDR" : p.role === "revops" ? "RevOps" : "Manager"}, since ${day(p.started_on)}`}>{p.name}</Title>
        {p.capacity ? (
          <>
            <div className="figs">
              <Fig sm value={n0(p.capacity.by_tier.A)} label="Tier A" />
              <Fig sm value={n0(p.capacity.by_tier.B)} label="Tier B" />
              <Fig sm value={`${Math.round(p.capacity.fte * 100)}%`} label="Ramped" />
              {p.capacity.ev !== undefined ? <Fig sm value={money(p.capacity.ev)} label="Expected value" /> : null}
            </div>
            <Hours used={p.capacity.hours_required} of={p.capacity.hours_available} />
          </>
        ) : null}
        <Section title="Book" count={p.book.length}>
          {p.book.length ? (
            <div className="ledger scrolly">{p.book.map((b: any) => (
              <button key={b.id} className="row" style={{ gridTemplateColumns: "24px minmax(0,1fr) 40px" }} onClick={() => openSheet("company", b.id)}>
                <Logo domain={b.primary_domain} name={b.name} size={24} /><span className="cell-main"><span className="t">{b.name}</span><span className="s">{b.segment_label}</span></span><Tier tier={b.tier} />
              </button>
            ))}</div>
          ) : <Empty title="No accounts" />}
        </Section>
      </Frame>
    )}</Wrap>
  );
}

// ---------------------------------------------------------------- Profile version

function VersionSheet({ id }: { id: string }) {
  const [busy, run] = useBusy();
  return (
    <Wrap kind="version" path={`/api/profile/versions/${id}`}>{(v) => (
      <Frame kind="version" crumb={`Version ${v.number}`}
        foot={v.status === "draft" ? <>
          <button className="btn" disabled={busy || !v.can_publish} title={v.can_publish ? undefined : "A manager other than the author publishes"} onClick={() => run(() => api(`/api/profile/versions/${v.id}/publish`, { method: "POST" }), "Published.")}>Publish</button>
        </> : undefined}>
        <Title sub={`${v.author}, ${day(v.created_at)}${v.publisher ? `. Published by ${v.publisher}, ${day(v.published_at)}` : ""}`}>Version {v.number}</Title>
        <Status kind={v.status === "published" ? "ok" : v.status === "draft" ? "wait" : "off"}>{v.status === "published" ? "Published" : v.status === "draft" ? "Draft" : "Retired"}</Status>
        <div className="small">{v.note}</div>
        {v.diff.length ? (
          <Section title="Against the version before">
            <div className="ledger">{v.diff.map((d: any, i: number) => (
              <div key={i} className="row" style={{ gridTemplateColumns: "90px minmax(0,1fr)" }}><span className="mute">{d.change}</span><span className="cell-main"><span className="t">{d.rule}</span>{d.was ? <span className="s">Was {d.was}</span> : null}</span></div>
            ))}</div>
          </Section>
        ) : null}
        <Section title="Rules">
          <div className="ledger">{v.rules.map((r: any) => (
            <button key={r.kind + r.key} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 44px 150px" }} disabled={!r.finding} onClick={() => r.finding && openSheet("finding", r.finding.id)}>
              <span className="cell-main"><span className="t">{r.label}</span><span className="s">{r.kind === "factors" ? "Adds" : r.kind === "penalties" ? "Takes away" : "Never a fit"}{!r.travels ? ", stays here" : ""}</span></span>
              <span className="num">{r.weight === null || r.weight === undefined ? "" : r.kind === "penalties" ? `−${r.weight}` : r.weight}</span>{r.finding ? <Verdict v={r.finding.verdict} /> : <Status kind="none">Hypothesis</Status>}
            </button>
          ))}</div>
        </Section>
        {v.dropped.length ? (
          <Section title="Account Desk cannot read">
            <div className="ledger">{v.dropped.map((d: any) => <div key={d.key} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}><span>{d.rule}</span><span className="mute">{d.why}</span></div>)}</div>
          </Section>
        ) : null}
      </Frame>
    )}</Wrap>
  );
}

// ---------------------------------------------------------------- Plan move

function MoveSheet({ id }: { id: string }) {
  const [plan, company] = id.split("-");
  return (
    <Wrap kind="move" path={`/api/moves/${plan}/${company}`}>{(m) => (
      <Frame kind="move" crumb={m.plan_name}>
        <Title sub={m.plan_name}>{m.name}</Title>
        <dl className="kv">
          <dt>From</dt><dd>{m.moved_from_name || "Unassigned"}</dd>
          <dt>To</dt><dd>{m.owner_name}</dd>
          <dt>Territory</dt><dd>{m.territory_label}</dd>
          <dt>By</dt><dd>{m.by_name}, {day(m.created_at)}</dd>
        </dl>
        {m.note ? <div className="quote ours">{m.note}</div> : null}
        <div className="actions"><button className="btn line sm" onClick={() => openSheet("company", m.company)}>Open the company</button></div>
      </Frame>
    )}</Wrap>
  );
}

// ---------------------------------------------------------------- Test

function TestSheet({ id }: { id: string }) {
  const [busy, run] = useBusy();
  const me = useData<any>("/api/me").data;
  return (
    <Wrap kind="test" path={`/api/tests/${id}`}>{(t) => {
      const r = t.report;
      const lead = me && ["revops", "manager"].includes(me.user.role);
      return (
        <Frame kind="test" crumb={t.segment_label}
          foot={lead && t.status === "draft" && me.user.role === "revops" ? <button className="btn" disabled={busy} onClick={() => run(() => api(`/api/tests/${t.id}/start`, { method: "POST" }), "Started.")}>Start</button>
            : lead && (t.status === "running" || (t.status === "read" && !t.decision)) ? <>
              <button className="btn quiet" disabled={busy} onClick={() => run(() => api(`/api/tests/${t.id}/decide`, { method: "POST", body: { decision: "drop" } }), "Dropped.")}>Drop</button>
              <button className="btn line" disabled={busy} onClick={() => run(() => api(`/api/tests/${t.id}/decide`, { method: "POST", body: { decision: "extend" } }), "Extended by 60 days.")}>Extend</button>
              <button className="btn" disabled={busy || !r.clear} onClick={() => run(() => api(`/api/tests/${t.id}/decide`, { method: "POST", body: { decision: "expand" } }), "Expanded. A proposal is open on Changes.")}>Expand</button>
            </> : undefined}>
          <Title sub={t.started_on ? `${day(t.started_on)} to ${day(t.ends_on)}` : "Not started"}>{t.segment_label}</Title>
          <div className="small">{t.hypothesis}</div>
          <Section title="Meetings">
            <div className="lift">
              <div className="lift-pair">
                <div><b>{pct(r.treated.rate)}</b><span>Worked</span><span className="mute">{n0(r.treated.meetings)} of {n0(r.treated.accounts)}</span></div>
                <div><b>{pct(r.holdout.rate)}</b><span>Held back</span><span className="mute">{n0(r.holdout.meetings)} of {n0(r.holdout.accounts)}</span></div>
              </div>
              {r.enough ? <Status kind={r.clear ? "ok" : "none"}>{r.clear ? "Clear difference" : "No clear difference"}</Status>
                : <Status kind="wait">Needs more accounts</Status>}
              {r.enough && r.interval ? <span className="small">Difference: {Math.round(r.interval[0] * 100)} to {Math.round(r.interval[1] * 100)} points</span>
                : <span className="small">Needs {n0(r.still_needed.holdout + r.still_needed.treated)} more accounts</span>}
            </div>
          </Section>
          {t.decision ? <dl className="kv"><dt>Decision</dt><dd>{t.decision[0].toUpperCase() + t.decision.slice(1)}, {t.decided_by_name}</dd>{t.decision_note ? <><dt>Note</dt><dd>{t.decision_note}</dd></> : null}</dl> : null}
          {t.refused.length ? (
            <Section title="Refused from a book">
              <div className="ledger">{t.refused.map((x: any, i: number) => <div key={i} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}><span>{x.name}</span><span className="mute">{day(x.at)}</span></div>)}</div>
            </Section>
          ) : null}
          <Section title="Accounts" count={t.members}>
            <div className="ledger scrolly">{t.sample.map((m: any) => (
              <button key={m.id} className="row" style={{ gridTemplateColumns: "24px minmax(0,1fr) 100px 60px" }} onClick={() => openSheet("company", m.id)}>
                <Logo domain={m.primary_domain} name={m.name} size={24} /><span className="t clip">{m.name}</span>
                <Status kind={m.grp === "held_back" ? "none" : "ok"}>{m.grp === "held_back" ? "Held back" : "Worked"}</Status><span className="num">{m.meetings} met</span>
              </button>
            ))}</div>
          </Section>
        </Frame>
      );
    }}</Wrap>
  );
}

// ---------------------------------------------------------------- Proposal

const KIND_WORD: Record<string, string> = { add_rule: "Add a rule", drop_rule: "Drop a rule", penalty: "Add a penalty", add_exclude: "Exclude",
  reweight: "Reweight", segment_expand: "Expand a segment", segment_drop: "Drop a segment" };

function ProposalSheet({ id }: { id: string }) {
  const [busy, run] = useBusy();
  const me = useData<any>("/api/me").data;
  return (
    <Wrap kind="proposal" path={`/api/proposals/${id}`}>{(p) => (
      <Frame kind="proposal" crumb={KIND_WORD[p.kind]}
        foot={p.status === "open" && me?.user.role === "revops" ? (
          <button className="btn" disabled={busy} onClick={() => run(async () => { const r = await api<any>("/api/proposals/draft", { method: "POST", body: { ids: [p.id] } }); openSheet("version", r.version); }, "Draft made.")}>Make a draft</button>
        ) : undefined}>
        <Title sub={p.change.field_label}>{KIND_WORD[p.kind]}: {p.change.value_label}</Title>
        <Status kind={p.status === "open" ? "wait" : p.status === "dismissed" ? "off" : "ok"}>{p.status === "open" ? "Open" : p.status === "dismissed" ? "Dismissed" : "Made a draft"}</Status>
        {p.sentences ? <div className="prop-words">{p.sentences.map((s: any, i: number) => <p key={i}>{s.text}</p>)}</div> : <Status kind="none">Withheld</Status>}
        <Section title="Evidence">
          <div className="ledger">
            <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) 70px 90px 150px" }}><span /><span className="num">{p.test_ids.length ? "Accounts" : "Deals"}</span><span className="num">{p.test_ids.length ? "Meetings" : "Win rate"}</span><span>Verdict</span></div>
            {p.findings.map((f: any) => (
            <button key={f.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 70px 90px 150px" }}
              onClick={() => (p.finding_ids.length ? openSheet("finding", f.id) : openSheet("test", p.test_ids[0]))}>
              <span className="cell-main"><span className="t">{f.value}</span><span className="s">{f.trait}</span></span>
              <span className="num">{n0(f.opportunities)}</span><span className="num">{f.win_rate}</span><span>{f.verdict}</span>
            </button>
          ))}</div>
        </Section>
        {p.status === "dismissed" ? <dl className="kv"><dt>Dismissed by</dt><dd>{p.decided_by}</dd><dt>Why</dt><dd>{p.reason}</dd></dl> : null}
        {p.status === "drafted" ? <dl className="kv"><dt>Draft</dt><dd><button className="link" onClick={() => openSheet("version", p.draft_version)}>Version {p.draft_number}</button></dd><dt>By</dt><dd>{p.decided_by}</dd></dl> : null}
      </Frame>
    )}</Wrap>
  );
}

// ---------------------------------------------------------------- Book

function BookSheet({ id }: { id: string }) {
  return (
    <Wrap kind="book" path={`/api/books/${id}`}>{(b) => (
      <Frame kind="book" crumb={b.destination === "account_desk" ? "Account Desk" : "Events Desk"}>
        <Title sub={`${day(b.created_at)}, profile v${b.icp_number}, ${b.plan_name}`}>Version {b.version}</Title>
        <div className="figs">
          <Fig sm value={n0(b.rows)} label="Rows" />
          <Fig sm value={n0(b.diff.added)} label="Added" />
          <Fig sm value={n0(b.diff.removed)} label="Removed" />
          <Fig sm value={n0(b.diff.tier_moved)} label="Tier moved" />
        </div>
        <div className="actions">{b.files.map((f: any) => <a key={f.path} className="btn line sm" href={`/api/books/${b.id}/files/${f.path}`} download>{f.path}</a>)}</div>
        {b.dropped_rules.length ? (
          <Section title="Rules Account Desk cannot read"><div className="ledger">{b.dropped_rules.map((d: any) => <div key={d.key} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}><span>{d.rule}</span><span className="mute">{d.why}</span></div>)}</div></Section>
        ) : null}
        {b.markdown ? <Section title="icp.md"><pre className="md-pre">{b.markdown}</pre></Section> : null}
        {b.sample.length ? (
          <Section title="Rows" count={b.rows}>
            <div className="ledger scrolly">{b.sample.map((r: any) => (
              <button key={r.company} className="row" style={{ gridTemplateColumns: "24px minmax(0,1fr) 40px minmax(0,0.8fr)" }} onClick={() => openSheet("company", r.company)}>
                <Logo domain={r.primary_domain} name={r.name} size={24} /><span className="cell-main"><span className="t">{r.name}</span><span className="s">{r.segment_label}{r.test_member ? ", in a test" : ""}</span></span>
                <Tier tier={r.tier} /><span className="clip mute">{r.owner || "Unassigned"}</span>
              </button>
            ))}</div>
          </Section>
        ) : null}
      </Frame>
    )}</Wrap>
  );
}

// ---------------------------------------------------------------- Source

function SourceSheet({ id }: { id: string }) {
  return (
    <Wrap kind="source" path={`/api/sources/${id}`}>{(s) => (
      <Frame kind="source" crumb={s.label}>
        <Title sub={s.adapter === "sim" ? "Simulated" : "Live"}>{s.label}</Title>
        <dl className="kv">
          <dt>Runs every</dt><dd>{s.cadence_hours >= 48 ? `${Math.round(s.cadence_hours / 24)} days` : `${s.cadence_hours} hours`}</dd>
          <dt>Cost</dt><dd>{s.paid ? (s.price_cents_per_unit !== undefined ? <>{`$${(s.price_cents_per_unit / 100).toFixed(2)} a ${s.unit}`} <span className="mute">our assumption</span></> : "Paid") : "Free"}</dd>
          <dt>Licence</dt><dd>{s.licence_note}</dd>
          {s.no_redistribution ? <><dt>In books</dt><dd>Never: its values stay out of every file</dd></> : null}
        </dl>
        <Section title="Runs">
          <div className="ledger">{s.runs.map((r: any) => (
            <div key={r.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 90px 90px" }}><span>{day(r.started_at)}</span><span className="num">{n0(r.rows_read)} read</span><span className="num">{n0(r.rows_changed)} changed</span></div>
          ))}</div>
        </Section>
      </Frame>
    )}</Wrap>
  );
}
