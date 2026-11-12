import { MapTrifold, UsersThree } from "@phosphor-icons/react";
import { api } from "../api";
import { Empty, Failed, Fig, Loading, Section, Seg, Status, day, money, n0, navigate, useBusy, useData, usePath, withParam } from "../lib";
import { Hours } from "../parts";
import { openSheet } from "../sheets";

export function Territories() {
  const [, params] = usePath();
  const tab = params.get("tab") === "capacity" ? "capacity" : "plan";
  const planParam = params.get("plan");
  const { data, error, reload } = useData<any>(`/api/territories${planParam ? `?plan=${planParam}` : ""}`);
  const me = useData<any>("/api/me").data;
  const [busy, run] = useBusy();
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Territories</h1></div><Loading /></div>;
  const plan = data.plan;
  if (!plan) return <div className="page"><div className="head"><h1>Territories</h1></div><Empty title="No plan yet" /></div>;
  const canActivate = plan.status === "draft" && me?.user.role === "manager" && me?.user.id !== plan.author_id;
  return (
    <div className="page">
      <div className="head">
        <h1>Territories</h1>
        <Seg label="View" value={tab} options={[["plan", "Plan"], ["capacity", "Capacity"]]} onChange={(v) => navigate(withParam("tab", v === "plan" ? null : v), true)} />
      </div>
      <div className="toolbar">
        <Seg label="Plan" value={String(plan.id)} options={data.plans.filter((p: any) => p.status !== "retired").map((p: any) => [String(p.id), `${p.name}${p.status === "draft" ? ", draft" : ""}`])}
          onChange={(v) => navigate(withParam("plan", v), true)} />
        {plan.status === "draft" ? (
          <div className="actions">
            <button className="btn" disabled={busy || !canActivate}
              title={canActivate ? undefined : "A manager other than the author activates it"}
              onClick={() => run(() => api(`/api/plans/${plan.id}/activate`, { method: "POST" }), "Activated. Owners moved.")}>Activate</button>
          </div>
        ) : <span className="mute small">Active since {day(plan.activated_at)}, by {plan.activated_by}</span>}
      </div>
      {tab === "plan" ? <PlanView data={data} money={!!me?.money} /> : <CapacityView data={data} />}
    </div>
  );
}

function PlanView({ data, money: showMoney }: { data: any; money: boolean }) {
  const plan = data.plan;
  const cols = "minmax(0,1.1fr) minmax(0,1.1fr) 58px 58px minmax(160px,1.1fr)" + (showMoney ? " 110px 110px" : "");
  return (
    <>
      <div className="figs">
        <Fig value={n0(data.people.reduce((s: number, p: any) => s + p.accounts_by_tier.A + p.accounts_by_tier.B, 0))} label="A and B owned" />
        <Fig value={n0(data.gap.accounts)} label="A and B unassigned" />
        <Fig value={n0(data.gap.people)} label="People needed" />
        <Fig value={`${n0(data.a_capacity.held)} of ${n0(data.a_capacity.tier_a)}`} label="Tier A worked" />
      </div>
      <Section title="People" icon={UsersThree}>
        <div className="ledger">
          <div className="row head" style={{ gridTemplateColumns: cols }}><span>Person</span><span>Territory</span><span className="num">A</span><span className="num">B</span><span>Hours a month</span>{showMoney ? <><span className="num">Expected value</span><span className="num">Territory mean</span></> : null}</div>
          {data.people.map((p: any) => (
            <button key={p.user_id} className="row" style={{ gridTemplateColumns: cols }} onClick={() => openSheet("person", p.user_id)}>
              <span className="cell-main"><span className="t">{p.name}</span><span className="s">{p.role === "ae" ? "AE" : "SDR"}{p.effective_fte < 1 ? `, ramping` : ""}</span></span>
              <span className="clip mute">{p.territory}</span>
              <span className="num" data-label="Tier A">{n0(p.accounts_by_tier.A)}</span><span className="num" data-label="Tier B">{n0(p.accounts_by_tier.B)}</span>
              <Hours used={p.hours_required} of={p.hours_available} />
              {showMoney ? <><span className="num" data-label="Expected value">{money(p.ev)}</span><span className="num mute" data-label="Territory mean">{p.ev_mean ? money(p.ev_mean) : ""}</span></> : null}
            </button>
          ))}
        </div>
      </Section>
      <Section title="Territories" icon={MapTrifold}>
        <div className="ledger">
          {data.territories.map((t: any) => (
            <div key={t.id} className="row" style={{ gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1fr) 80px 130px" }}>
              <span className="cell-main"><span className="t">{t.label}</span><span className="s">{t.segments.join(", ")}</span></span>
              <span className="clip">{t.people.map((p: any) => p.name).join(", ")}{t.ae ? <span className="mute">, with {t.ae}</span> : null}</span>
              <span className="num" data-label="Accounts">{n0(t.accounts)}</span>
              {t.balance ? <Status kind={t.balance.balanced ? "ok" : "hold"}>{t.balance.balanced ? "Balanced" : "Not balanced"}</Status> : <span />}
            </div>
          ))}
        </div>
      </Section>
      {plan.status === "draft" && data.changes ? (
        <Section title="What changes" count={data.changes.changes}>
          {data.changes.crossing ? <Status kind="stop">{`${n0(data.changes.crossing)} open deals would leave their owner`}</Status> : null}
          <div className="ledger">
            <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) 80px 80px 80px" }}><span>Person</span><span className="num">Gains</span><span className="num">Losses</span><span className="num">Net</span></div>
            {data.changes.people.map((g: any) => (
              <div key={g.name} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 80px 80px 80px" }}>
                <span>{g.name}</span><span className="num" data-label="Gains">{n0(g.gains)}</span><span className="num" data-label="Losses">{n0(g.losses)}</span>
                <span className="num" data-label="Net">{g.gains - g.losses > 0 ? "+" : ""}{n0(g.gains - g.losses)}</span>
              </div>
            ))}
          </div>
        </Section>
      ) : null}
      {data.manual.length ? (
        <Section title="Moved by hand" count={data.manual.length}>
          <div className="ledger">
            {data.manual.map((m: any) => (
              <button key={m.company} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1.6fr)" }} onClick={() => openSheet("move", `${plan.id}-${m.company}`)}>
                <span className="cell-main"><span className="t">{m.name}</span><span className="s">{m.moved_from} to {m.owner}</span></span>
                <span className="said-quote">{m.note}</span>
              </button>
            ))}
          </div>
        </Section>
      ) : null}
    </>
  );
}

function CapacityView({ data }: { data: any }) {
  const h = data.hours_per_tier;
  return (
    <>
      <div className="figs">
        <Fig value={`${h.A}`} unit=" h" label="Tier A, a month" />
        <Fig value={`${h.B}`} unit=" h" label="Tier B, a month" />
        <Fig value={`${h.C}`} unit=" h" label="Tier C, a month" />
        <Fig value={n0(data.gap.hours)} unit=" h" label="Hours short" />
      </div>
      <Section title="Roster" icon={UsersThree}>
        <div className="ledger">
          <div className="row head" style={{ gridTemplateColumns: "minmax(0,1.2fr) 110px 80px 70px minmax(160px,1.2fr)" }}><span>Person</span><span>Started</span><span className="num">Ramp</span><span className="num">Effective</span><span>Hours a month</span></div>
          {data.people.map((p: any) => (
            <button key={p.user_id} className="row" style={{ gridTemplateColumns: "minmax(0,1.2fr) 110px 80px 70px minmax(160px,1.2fr)" }} onClick={() => openSheet("person", p.user_id)}>
              <span className="t">{p.name}</span><span className="mute">{day(p.started_on)}</span>
              <span className="num">{p.ramp_months} months</span><span className="num">{Math.round(p.effective_fte * 100)}%</span>
              <Hours used={p.hours_required} of={p.hours_available} />
            </button>
          ))}
        </div>
      </Section>
      <Section title="Hiring gap">
        <div className="figs">
          <Fig value={n0(data.gap.by_tier.A || 0)} label="Tier A unassigned" />
          <Fig value={n0(data.gap.by_tier.B || 0)} label="Tier B unassigned" />
          <Fig value={n0(data.gap.people)} label="People needed" />
        </div>
      </Section>
    </>
  );
}
