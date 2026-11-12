import { useState } from "react";
import { GearSix, UsersThree } from "@phosphor-icons/react";
import { api } from "../api";
import { Failed, Loading, Section, Status, ago, day, money, pct, useBusy, useData, T } from "../lib";
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
        <div className="row head" style={{ gridTemplateColumns: cols }}><T>Source</T><T>Kind</T><T>Last run</T><T>Fields filled</T><T num>This month</T></div>
        {data.rows.map((s: any) => (
          <button key={s.key} className="row" style={{ gridTemplateColumns: cols }} onClick={() => openSheet("source", s.key)}>
            <span className="cell-main"><span className="t">{s.label}</span><span className="s">{s.adapter === "sim" ? "Simulated data" : "Live"}{s.no_redistribution ? "; its licence keeps it out of files we send" : ""}</span></span>
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
  family_alpha: "False-alarm risk allowed", shrink_k: "Win rate smoothing, deals",
  hours_per_tier: "Hours a month per account", balance_band: "Allowed gap from average", hours_test_account: "Hours a month per test account", held_back_share: "Share held back in a test",
  drop_rule_min_opps: "Deals before a rule is proposed for removal", opp_rate_default: "Starting deal rate",
  account_cycle_months: "Months an account is worked",
};

// Settings held as shares are shown and typed as percentages.
const PCT = new Set(["balance_band", "family_alpha", "held_back_share", "opp_rate_default"]);

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
              <span className="cell-main" title={s.note}><span className="t"><T>{SETTING[s.key] || s.key}</T></span>{s.note.startsWith("Our assumption") ? <span className="s">Our assumption</span> : null}</span>
              {typeof s.value === "number" ? (
                <span className="with-unit"><input className="input" aria-label={SETTING[s.key] || s.key} value={edit[s.key] ?? String(PCT.has(s.key) ? Math.round(s.value * 1000) / 10 : s.value)} onChange={(e) => setEdit({ ...edit, [s.key]: e.target.value })} />{PCT.has(s.key) ? <span className="mute">%</span> : null}</span>
              ) : <span>{show(s.value)}</span>}
              {typeof s.value === "number" ? (
                <button className="btn line sm" disabled={busy || edit[s.key] === undefined || Number.isNaN(Number(edit[s.key]))}
                  onClick={() => run(() => api(`/api/settings/${s.key}`, { method: "POST", body: { value: PCT.has(s.key) ? Number(edit[s.key]) / 100 : Number(edit[s.key]) } }), "Saved.")}>Save</button>
              ) : <span />}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Team" icon={UsersThree}>
        <div className="ledger">
          {data.team.map((u: any) => (
            <button key={u.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 90px 120px 110px" }} onClick={() => openSheet("person", u.id)}>
              <span className="t">{u.name}</span><span className="mute">{({ revops: "RevOps", manager: "Manager", gtm: "GTM leader", sdr: "SDR", ae: "AE" } as Record<string, string>)[u.role]}</span>
              <span className="mute">{new Date(u.started_on) > new Date() ? "Starts " : "Since "}{day(u.started_on)}</span><span className="num">{u.selling_hours_month} h</span>
            </button>
          ))}
        </div>
      </Section>
    </div>
  );
}
