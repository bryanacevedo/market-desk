import { MapTrifold, UsersThree } from "@phosphor-icons/react";
import { api } from "../api";
import { Empty, Failed, Fig, Loading, Section, Seg, Status, day, money, n0, navigate, useBusy, useData, usePath, withParam, T, Tip } from "../lib";
import { CapacityRange, PlanShift } from "../parts";
import { openSheet } from "../sheets";

export function Territories() {
  const [, params] = usePath();
  const tab = params.get("tab") === "capacity" ? "capacity" : "plan";
  const planParam = params.get("plan");
  const { data, error, reload } = useData<any>(`/api/territories${planParam ? `?plan=${planParam}` : ""}`);
  const me = useData<any>("/api/me").data;
  const activeData = useData<any>("/api/territories").data;
  const [busy, run] = useBusy();
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Territories</h1></div><Loading /></div>;
  const plan = data.plan;
  if (!plan) return <div className="page"><div className="head"><h1>Territories</h1></div><Empty title="No plan yet" /></div>;
  const canActivate = plan.status === "draft" && me?.user.role === "manager" && me?.user.id !== plan.author_id;
  const activateButton = <div className="actions">
            <button className="btn" disabled={busy || !canActivate}
              title={canActivate ? undefined : "A manager other than the author activates it"}
              onClick={() => run(() => api(`/api/plans/${plan.id}/activate`, { method: "POST" }), "Activated. Owners moved.")}>Activate</button>
  </div>;
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
          canActivate ? activateButton : <span className="small mute">Waiting for a manager to activate</span>
        ) : <span className="mute small">Active since {day(plan.activated_at)}, by {plan.activated_by}</span>}
      </div>
      {tab === "plan" ? <PlanView data={data} active={plan.status === "draft" && activeData?.plan?.id !== plan.id ? activeData : null} money={!!me?.money} /> : <CapacityView data={data} />}
    </div>
  );
}

const ab = (p: any) => p.accounts_by_tier.A + p.accounts_by_tier.B;
const hoursMax = (people: any[]) => Math.max(1, ...people.map((p: any) => Math.max(Number(p.hours_required), Number(p.selling_hours_month || p.hours_available))));

function PlanView({ data, active, money: showMoney }: { data: any; active: any; money: boolean }) {
  const plan = data.plan;
  const draft = !!active;
  const was = new Map<number, number>((active?.people || []).map((p: any) => [p.user_id, ab(p)]));
  const owned = data.people.reduce((s: number, p: any) => s + ab(p), 0);
  const ownedWas = active ? active.people.reduce((s: number, p: any) => s + ab(p), 0) : null;
  const shiftMax = Math.max(1, ...data.people.map(ab), ...[...was.values()]);
  const hmax = hoursMax(data.people);
  const vs = (now: number, then: number | null | undefined) => (then === null || then === undefined ? undefined : `${n0(then)} now, ${now - then >= 0 ? "+" : "−"}${n0(Math.abs(now - then))}`);
  const cols = (draft ? "minmax(0,1.1fr) minmax(0,1fr) minmax(150px,1fr) minmax(190px,1.2fr)" : "minmax(0,1.1fr) minmax(0,1.1fr) 58px 58px minmax(190px,1.2fr)") + (showMoney ? " 110px 110px" : "");
  return (
    <>
      <div className="figs">
        <Fig value={n0(owned)} label="A and B owned" was={vs(owned, ownedWas)} />
        <Fig value={n0(data.gap.accounts)} label="A and B unassigned" was={vs(data.gap.accounts, active?.gap.accounts)} />
        <Fig value={n0(data.gap.people)} label="People needed" was={vs(data.gap.people, active?.gap.people)} />
        <Fig value={`${n0(data.a_capacity.held)} of ${n0(data.a_capacity.tier_a)}`} label="Tier A worked" was={active ? `${n0(active.a_capacity.held)} now` : undefined} />
      </div>
      {plan.status === "draft" && data.changes ? (
        <div className="halo"><Section title="What changes" count={data.changes.changes}>
          {data.changes.crossing ? <Status kind="stop">{`${n0(data.changes.crossing)} open deals would leave their owner`}</Status> : null}
          <div className="ledger">
            <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) 80px 80px 80px" }}><T>Person</T><T num>Gains</T><T num>Losses</T><T num>Net</T></div>
            {data.changes.people.map((g: any) => (
              <div key={g.name} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 80px 80px 80px" }}>
                <span>{g.name}</span><span className="num" data-label="Gains">{n0(g.gains)}</span><span className="num" data-label="Losses">{n0(g.losses)}</span>
                <span className="num" data-label="Net">{g.gains - g.losses > 0 ? "+" : ""}{n0(g.gains - g.losses)}</span>
              </div>
            ))}
          </div>
        </Section></div>
      ) : null}
      <Section title="People" icon={UsersThree} right={<span className="small mute">Each rep's book goes to Account Desk</span>}>
        <div className="ledger">
          <div className="row head" style={{ gridTemplateColumns: cols }}><T>Person</T><T>Territory</T>{draft ? <T>A and B, ring: now</T> : <><T num>A</T><span className="num"><Tip tip="Tier B accounts in the person's book.">B</Tip></span></>}<T>Hours needed, of held</T>{showMoney ? <><T num>Expected value</T><T num>Average</T></> : null}</div>
          {data.people.map((p: any) => (
            <button key={p.user_id} className="row" style={{ gridTemplateColumns: cols }} onClick={() => openSheet("person", p.user_id)}>
              <span className="cell-main"><span className="t">{p.name}</span><span className="s">{p.role === "ae" ? "AE" : "SDR"}{p.effective_fte < 1 ? `, ramping` : ""}</span></span>
              <span className="clip mute">{p.territory}</span>
              {draft ? <span data-label="A and B, ring: now"><PlanShift was={was.has(p.user_id) ? was.get(p.user_id)! : null} now={ab(p)} max={shiftMax} /></span>
                : <><span className="num" data-label="Tier A">{n0(p.accounts_by_tier.A)}</span><span className="num" data-label="Tier B">{n0(p.accounts_by_tier.B)}</span></>}
              <span data-label="Hours needed, of held"><CapacityRange needed={Number(p.hours_required)} held={Number(p.hours_available)} full={Number(p.selling_hours_month || p.hours_available)} max={hmax} /></span>
              {showMoney ? <><span className="num" data-label="Expected value">{money(p.ev)}</span><span className="num mute" data-label="Territory average">{p.ev_mean ? money(p.ev_mean) : ""}</span></> : null}
            </button>
          ))}
        </div>
      </Section>
      <Section title="Territories" icon={MapTrifold}>
        <div className="ledger">
          <div className="row head" style={{ gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1fr) 80px 130px" }}><T>Territory</T><T>People</T><T num>A and B</T><span /></div>
          {data.territories.map((t: any) => (
            <div key={t.id} className="row" style={{ gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1fr) 80px 130px" }}>
              <span className="cell-main"><span className="t">{t.label}</span><span className="s">{t.segments.join(", ")}</span></span>
              <span className="clip">{t.people.map((p: any) => p.name).join(", ")}{t.ae ? <span className="mute">; AE {t.ae}</span> : null}</span>
              <span className="num" data-label="Accounts">{n0(t.accounts)}</span>
              {t.balance ? <Status kind={t.balance.balanced ? "ok" : "hold"}>{t.balance.balanced ? "Balanced" : t.balance.over_hours ? "Over capacity" : "Not balanced"}</Status> : <span />}
            </div>
          ))}
        </div>
      </Section>

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
  const hmax = hoursMax(data.people);
  return (
    <>
      <div className="figs">
        <Fig value={`${h.A}`} unit=" h" label="Hours a month, tier A" />
        <Fig value={`${h.B}`} unit=" h" label="Hours a month, tier B" />
        <Fig value={`${h.C}`} unit=" h" label="Hours a month, tier C" />
        <Fig value={n0(data.gap.hours)} unit=" h" label="Hours short" />
      </div>
      <Section title="Roster" icon={UsersThree}>
        <div className="ledger">
          <div className="row head" style={{ gridTemplateColumns: "minmax(0,1.1fr) 110px 70px minmax(220px,1.6fr)" }}><T>Person</T><T>Started</T><T num>Ramped</T><T>Hours needed, of held</T></div>
          {data.people.map((p: any) => (
            <button key={p.user_id} className="row" style={{ gridTemplateColumns: "minmax(0,1.1fr) 110px 70px minmax(220px,1.6fr)" }} onClick={() => openSheet("person", p.user_id)}>
              <span className="cell-main"><span className="t">{p.name}</span><span className="s">{p.role === "ae" ? "AE" : "SDR"}</span></span>
              <span className="mute" data-label="Started">{new Date(p.started_on).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}</span>
              <span className="num" data-label="Ramped">{Math.round(p.effective_fte * 100)}%</span>
              <span data-label="Hours needed, of held"><CapacityRange needed={Number(p.hours_required)} held={Number(p.hours_available)} full={Number(p.selling_hours_month || p.hours_available)} max={hmax} /></span>
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
