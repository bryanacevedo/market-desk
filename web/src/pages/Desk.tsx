import { useState } from "react";
import { GearSix, UsersThree } from "@phosphor-icons/react";
import { api } from "../api";
import { Failed, Loading, Section, Status, ago, day, money, pct, useBusy, useData } from "../lib";
import { openSheet } from "../sheets";

export const KIND_WORD: Record<string, string> = {
  firmographic: "Company data", technographic: "Technology", registry: "Registry", public_counts: "Public counts",
  crm: "CRM", desk_results: "Desk results", coverage: "Contact finder", model: "AI",
};

export function Sources() {
  const { data, error, reload } = useData<any>("/api/sources");
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Sources</h1></div><Loading /></div>;
  const cols = "minmax(0,1.3fr) 120px 150px minmax(0,1.2fr) 90px";
  return (
    <div className="page">
      <div className="head"><h1>Sources</h1></div>
      <div className="ledger">
        <div className="row head" style={{ gridTemplateColumns: cols }}><span>Source</span><span>Kind</span><span>Last run</span><span>Fields filled</span><span className="num">This month</span></div>
        {data.rows.map((s: any) => (
          <button key={s.key} className="row" style={{ gridTemplateColumns: cols }} onClick={() => openSheet("source", s.key)}>
            <span className="cell-main"><span className="t">{s.label}</span><span className="s">{s.adapter === "sim" ? "Simulated" : "Live"}{s.no_redistribution ? ", stays out of books" : ""}</span></span>
            <span className="mute">{KIND_WORD[s.kind]}</span>
            <Status kind={s.stale ? "hold" : "ok"}>{s.stale ? "Missed its run" : ago(s.last_run)}</Status>
            <span className="cell-main">{s.fill.slice(0, 2).map((f: any) => <span key={f.field} className="s">{f.field} <b className="strong">{pct(f.share)}</b></span>)}</span>
            <span className="num">{s.paid ? money(s.spend_cents) : "Free"}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

const SETTING: Record<string, string> = {
  evidence_window_months: "Window, months", min_opps: "Fewest deals to judge", min_wins: "Fewest wins to judge",
  family_alpha: "Bar for a clear result", shrink_k: "Weight given to the overall win rate, in deals",
  hours_per_tier: "Hours a month per account", balance_band: "Allowed gap from average", hours_test_account: "Hours a month per test account", held_back_share: "Share held back in a test",
  drop_rule_min_opps: "Deals before a rule is proposed for removal", opp_rate_default: "Share of worked accounts that become deals, before any results",
  account_cycle_months: "Months an account is worked",
};

export function Settings() {
  const { data, error, reload } = useData<any>("/api/settings");
  const [busy, run] = useBusy();
  const [edit, setEdit] = useState<Record<string, string>>({});
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Settings</h1></div><Loading /></div>;
  const show = (v: any) => (typeof v === "object" ? Object.entries(v).map(([k, x]) => `${k} ${x}`).join(", ") : String(v));
  return (
    <div className="page">
      <div className="head"><h1>Settings</h1></div>
      <Section title="Assumptions and thresholds" icon={GearSix}>
        <div className="ledger">
          {data.settings.map((s: any) => (
            <div key={s.key} className="row" style={{ gridTemplateColumns: "minmax(0,1.6fr) 180px 150px" }}>
              <span className="cell-main" title={s.note}><span className="t">{SETTING[s.key] || s.key}</span>{s.note.startsWith("Our assumption") ? <span className="s">Our assumption</span> : null}</span>
              {typeof s.value === "number" ? (
                <input className="input" aria-label={s.key} value={edit[s.key] ?? String(s.value)} onChange={(e) => setEdit({ ...edit, [s.key]: e.target.value })} />
              ) : <span>{show(s.value)}</span>}
              {typeof s.value === "number" ? (
                <button className="btn line sm" disabled={busy || edit[s.key] === undefined || Number.isNaN(Number(edit[s.key]))}
                  onClick={() => run(() => api(`/api/settings/${s.key}`, { method: "POST", body: { value: Number(edit[s.key]) } }), "Saved.")}>Save</button>
              ) : <span />}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Team" icon={UsersThree}>
        <div className="ledger">
          {data.team.map((u: any) => (
            <button key={u.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 90px 120px 110px" }} onClick={() => openSheet("person", u.id)}>
              <span className="t">{u.name}</span><span className="mute">{u.role === "revops" ? "RevOps" : u.role === "ae" ? "AE" : u.role === "sdr" ? "SDR" : "Manager"}</span>
              <span className="mute">{day(u.started_on)}</span><span className="num">{u.selling_hours_month} h</span>
            </button>
          ))}
        </div>
      </Section>
    </div>
  );
}
