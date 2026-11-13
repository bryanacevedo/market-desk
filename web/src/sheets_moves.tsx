import { useEffect, useState } from "react";
import { X } from "@phosphor-icons/react";
import { api } from "./api";
import { Empty, Fig, Section, Status, day, n0, navigate, toast, useBusy, useData, T } from "./lib";
import { Tier } from "./parts";
import { Frame, Title, Wrap, closeSheet, openSheet } from "./sheets";

/** Confirm sheets. Each one says, in counts, what pressing the button changes, and says plainly what cannot be pulled back. */

const people = (rows: any[]) => (
  <div className="ledger">
    <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) 80px 80px" }}><T>Person</T><T num>Gains</T><T num>Losses</T></div>
    {rows.map((g: any) => (
      <div key={g.name} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 80px 80px" }}>
        <span>{g.name}</span><span className="num" data-label="Gains">{n0(g.gains)}</span><span className="num" data-label="Losses">{n0(g.losses)}</span>
      </div>
    ))}
  </div>
);

const tierMoves = (rows: any[]) => rows.length ? (
  <div className="ledger">
    <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) 80px" }}><T>Tier change</T><T num>Companies</T></div>
    {rows.map((m: any) => (
      <div key={m.from + m.to} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 80px" }}><span>{m.from} to {m.to}</span><span className="num" data-label="Companies">{n0(m.count)}</span></div>
    ))}
  </div>
) : null;

function Foot({ busy, label, ok, onGo }: { busy: boolean; label: string; ok: boolean; onGo: () => void }) {
  return <>
    <button className="btn quiet" onClick={closeSheet}>Cancel</button>
    <button className="btn" disabled={busy || !ok} onClick={onGo}>{label}</button>
  </>;
}

export function ActivateSheet({ id }: { id: string }) {
  const [busy, run] = useBusy();
  return (
    <Wrap kind="activate" path={`/api/plans/${id}/activate-preview`}>{(p) => (
      <Frame kind="activate" foot={<Foot busy={busy} label="Activate" ok={p.can_activate}
        onGo={() => run(async () => { await api(`/api/plans/${p.id}/activate`, { method: "POST" }); closeSheet(); }, "Activated. Owners moved.")} />}>
        <Title sub={p.replaces ? `Replaces ${p.replaces}` : undefined}>Activate {p.name}</Title>
        {p.blocked ? <Status kind="stop">{p.blocked}</Status> : null}
        <div className="figs">
          <Fig sm value={n0(p.owner_changes)} label="Accounts change owner" />
          <Fig sm value={n0(p.crossing)} label="Open deals leave their owner" />
          <Fig sm value={p.crm ? n0(p.batches) : "None"} label="Requests to CRM Desk" />
        </div>
        {p.crm ? <div className="small">CRM Desk keeps what it takes. Rolling back sends the earlier plan over it, and owners pinned there stay as they are.</div>
          : <div className="small">No CRM is set, so nothing is sent.</div>}
        {p.effective_on > p.today ? <div className="small">The plan starts {day(p.effective_on)}. Owners change in this desk now.</div> : null}
        {p.people.length ? <Section title="Who gains and loses">{people(p.people)}</Section> : null}
      </Frame>
    )}</Wrap>
  );
}

export function PublishSheet({ id }: { id: string }) {
  const [busy, run] = useBusy();
  return (
    <Wrap kind="publish" path={`/api/profile/versions/${id}/publish-preview`}>{(p) => (
      <Frame kind="publish" foot={<Foot busy={busy} label="Publish" ok={p.can_publish}
        onGo={() => run(async () => { await api(`/api/profile/versions/${p.id}/publish`, { method: "POST" }); closeSheet(); }, "Published. Every company is being rescored.")} />}>
        <Title sub={`Replaces version ${p.replaces}`}>Publish version {p.number}</Title>
        {!p.can_publish ? <Status kind="stop">{p.status === "draft" ? "A manager other than the author publishes it" : "Only a draft can be published"}</Status> : null}
        <div className="figs">
          <Fig sm value={n0(p.rule_changes)} label="Rules changed" />
          <Fig sm value={n0(p.companies)} label="Companies rescored" />
          <Fig sm value={n0(p.tier_moves)} label="Change tier" />
          <Fig sm value="0" label="Accounts change owner" />
        </div>
        {tierMoves(p.moves)}
        {p.crm ? <div className="small">Nothing goes to CRM Desk now. The new tiers go with the next plan you activate.</div> : null}
      </Frame>
    )}</Wrap>
  );
}

export function RollbackSheet({ id }: { id: string }) {
  const [busy, run] = useBusy();
  const icp = id === "icp";
  return (
    <Wrap kind="rollback" path={icp ? "/api/profile/rollback-preview" : "/api/plans/rollback-preview"}>{(p) => !p.available ? (
      <Frame kind="rollback"><Empty title="Nothing to roll back to" /></Frame>
    ) : (
      <Frame kind="rollback" foot={<Foot busy={busy} label="Roll back" ok={p.can_roll_back}
        onGo={() => run(async () => { await api(icp ? "/api/profile/rollback" : "/api/plans/rollback", { method: "POST" }); closeSheet(); },
          icp ? "Rolled back. Every company is rescored." : "Rolled back. Owners restored.")} />}>
        <Title sub={icp ? `Replaces version ${p.from}` : `Replaces ${p.from}`}>
          Go back to {icp ? `version ${p.to}` : p.to}</Title>
        {!p.can_roll_back ? <Status kind="stop">A manager rolls back</Status> : null}
        {icp ? (
          <>
            <div className="figs">
              <Fig sm value={n0(p.companies)} label="Companies rescored" />
              <Fig sm value={n0(p.tier_moves)} label="Change tier" />
            </div>
            {tierMoves(p.moves)}
            {p.crm ? <div className="small">Nothing goes to CRM Desk now. The tiers go with the next plan you activate.</div> : null}
          </>
        ) : (
          <>
            <div className="figs">
              <Fig sm value={n0(p.owner_changes)} label="Accounts change owner" />
              {p.crm ? <>
                <Fig sm value={n0(p.sent_batches)} label="Requests already sent" />
                <Fig sm value={n0(p.waiting_batches)} label="Requests cancelled" />
                <Fig sm value={n0(p.batches)} label="Requests to send" />
              </> : null}
            </div>
            {p.crm ? <div className="small">What CRM Desk already took stays there until the earlier plan is sent over it. Owners pinned there stay as they are.</div>
              : <div className="small">No CRM is set, so nothing is sent.</div>}
          </>
        )}
      </Frame>
    )}</Wrap>
  );
}

// ---------------------------------------------------------------- Move proposals

export function TransferSheet({ id }: { id: string }) {
  return id.startsWith("new") ? <NewTransfer first={id.startsWith("new-") ? Number(id.slice(4)) : null} /> : <TransferView id={id} />;
}

function NewTransfer({ first }: { first: number | null }) {
  const opts = useData<any>("/api/move-proposals/options").data;
  const [busy, run] = useBusy();
  const [picked, setPicked] = useState<any[]>([]);
  const [to, setTo] = useState("");
  const [terr, setTerr] = useState("");
  const [on, setOn] = useState("");
  const [reason, setReason] = useState("");
  const [q, setQ] = useState("");
  const [found, setFound] = useState<any[]>([]);
  useEffect(() => {
    if (first) api<any>(`/api/move-proposals/candidates?only=${first}`).then((r) => setPicked(r.accounts)).catch(() => undefined);
  }, [first]);
  useEffect(() => {
    if (q.trim().length < 2) { setFound([]); return; }
    let live = true;
    api<any>(`/api/move-proposals/candidates?q=${encodeURIComponent(q.trim())}`).then((r) => { if (live) setFound(r.accounts); }).catch(() => undefined);
    return () => { live = false; };
  }, [q]);
  if (!opts) return <Frame kind="transfer"><Empty title="Loading" /></Frame>;
  const add = (rows: any[]) => setPicked((x) => [...x, ...rows.filter((r) => !x.some((y) => y.id === r.id))].slice(0, 200));
  const toId = Number(to);
  const takers = opts.territories.filter((t: any) => t.people.includes(toId));
  const date = on || opts.today;
  const clash = picked.filter((a) => a.owner_id === toId).length;
  const ok = !!to && !!reason.trim() && reason.trim().length >= 3 && picked.length > 0 && !clash && date >= opts.today;
  const submit = () => run(async () => {
    const r = await api<any>("/api/move-proposals", { method: "POST", body: { companies: picked.map((a) => a.id), to: toId, territory: terr || null, reason, effective_on: date } });
    openSheet("transfer", r.id);
  }, "Proposed.");
  return (
    <Frame kind="transfer" foot={<Foot busy={busy} label="Propose" ok={ok} onGo={submit} />}>
      <Title>Propose a move</Title>
      <label className="form-field"><span className="small mute">Move to</span>
        <select className="select" value={to} onChange={(e) => { setTo(e.target.value); setTerr(""); }}>
          <option value="">Choose a person</option>
          {["ae", "sdr"].map((r) => <optgroup key={r} label={r === "ae" ? "AEs" : "SDRs"}>
            {opts.people.filter((p: any) => p.role === r).map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </optgroup>)}
        </select>
      </label>
      {takers.length ? <label className="form-field"><span className="small mute">Territory</span>
        <select className="select" value={terr} onChange={(e) => setTerr(e.target.value)}>
          <option value="">Keep each account's territory</option>
          {takers.map((t: any) => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
      </label> : null}
      <label className="form-field"><span className="small mute">Effective</span>
        <input className="input" type="date" min={opts.today} value={date} onChange={(e) => setOn(e.target.value)} />
      </label>
      <label className="form-field"><span className="small mute">Reason</span>
        <textarea className="input" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <Section title="Accounts" count={picked.length}>
        <div className="actions">
          <input className="input" style={{ flex: "1 1 180px" }} placeholder="Find by name or domain" aria-label="Find an account" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="select" aria-label="Add everything one person owns" value="" onChange={(e) => {
            if (e.target.value) api<any>(`/api/move-proposals/candidates?owner=${e.target.value}`).then((r) => add(r.accounts)).catch(() => toast("That did not go through."));
          }}>
            <option value="">Add all of one person's</option>
            {opts.people.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        {found.length ? <div className="ledger">
          {found.map((a: any) => (
            <button key={a.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 40px minmax(0,0.7fr)" }} onClick={() => { add([a]); setQ(""); }}>
              <span className="cell-main"><span className="t">{a.name}</span><span className="s">{a.primary_domain}</span></span><Tier tier={a.tier} /><span className="clip mute">{a.owner || "Unassigned"}</span>
            </button>
          ))}
        </div> : null}
        {picked.length ? <div className="ledger scrolly">
          {picked.map((a: any) => (
            <div key={a.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 40px minmax(0,0.7fr) 36px" }}>
              <span className="cell-main"><span className="t">{a.name}</span><span className="s">{a.primary_domain}</span></span><Tier tier={a.tier} />
              <span className="clip mute">{a.owner || "Unassigned"}</span>
              <button className="iconbtn" aria-label={`Remove ${a.name}`} onClick={() => setPicked((x) => x.filter((y) => y.id !== a.id))}><X size={16} /></button>
            </div>
          ))}
        </div> : <Empty title="No accounts chosen" />}
        {clash ? <Status kind="stop">{`${n0(clash)} already belong to this person`}</Status> : null}
      </Section>
    </Frame>
  );
}

function TransferView({ id }: { id: string }) {
  const [busy, run] = useBusy();
  const [rejecting, setRejecting] = useState(false);
  const [why, setWhy] = useState("");
  return (
    <Wrap kind="transfer" path={`/api/move-proposals/${id}`}>{(p) => (
      <Frame kind="transfer" foot={p.status === "open" && p.can_decide ? (rejecting ? <>
        <input className="input" style={{ flex: 1, minWidth: 160 }} placeholder="Why reject?" aria-label="Reason" autoFocus value={why} onChange={(e) => setWhy(e.target.value)} />
        <button className="btn quiet" onClick={() => setRejecting(false)}>Cancel</button>
        <button className="btn line" disabled={busy || why.trim().length < 3}
          onClick={() => run(async () => { await api(`/api/move-proposals/${p.id}/reject`, { method: "POST", body: { reason: why } }); }, "Rejected.")}>Reject</button>
      </> : <>
        <button className="btn line" disabled={busy} onClick={() => setRejecting(true)}>Reject</button>
        <button className="btn" disabled={busy}
          onClick={() => run(async () => { const r = await api<any>(`/api/move-proposals/${p.id}/approve`, { method: "POST" }); navigate(`/territories?plan=${r.plan}`); }, "Approved. A draft plan is ready to activate.")}>Approve</button>
      </>) : p.plan ? <button className="btn" onClick={() => navigate(`/territories?plan=${p.plan}`)}>Open the plan</button> : undefined}>
        <Title sub={`${p.proposed_by}, ${day(p.proposed_at)}`}>{n0(p.count)} account{p.count === 1 ? "" : "s"} to {p.to_owner}</Title>
        <Status kind={p.status === "open" ? "wait" : p.status === "approved" ? "ok" : "off"}>{p.status === "open" ? "Open" : p.status === "approved" ? "Approved" : "Rejected"}</Status>
        <dl className="kv">
          <dt><T>Effective</T></dt><dd>{day(p.effective_on)}</dd>
          {p.to_territory ? <><dt><T>Territory</T></dt><dd>{p.to_territory}</dd></> : null}
          <dt><T>Reason</T></dt><dd>{p.reason}</dd>
          {p.decided_by ? <><dt><T>{p.status === "approved" ? "Approved by" : "Rejected by"}</T></dt><dd>{p.decided_by}, {day(p.decided_at)}</dd></> : null}
          {p.decision_note ? <><dt><T>Why</T></dt><dd>{p.decision_note}</dd></> : null}
          {p.plan_name ? <><dt><T>Plan</T></dt><dd>{p.plan_name}</dd></> : null}
        </dl>
        <Section title="Accounts" count={p.count}>
          <div className="ledger scrolly">
            {p.accounts.map((a: any) => (
              <button key={a.id} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) 40px minmax(0,0.7fr)" }} onClick={() => openSheet("company", a.id)}>
                <span className="cell-main"><span className="t">{a.name}</span><span className="s">{a.primary_domain}</span></span><Tier tier={a.tier} /><span className="clip mute">{a.from_owner || "Unassigned"}</span>
              </button>
            ))}
          </div>
        </Section>
      </Frame>
    )}</Wrap>
  );
}

/** Who changed what and when, newest first. */
export function History({ rows, figure }: { rows: any[]; figure?: string }) {
  return (
    <div className="ledger">
      {rows.map((h: any, i: number) => (
        <div key={i} className="row" style={{ gridTemplateColumns: figure ? "110px minmax(0,1.4fr) minmax(0,0.8fr) 110px" : "110px minmax(0,1.4fr) minmax(0,0.8fr)" }}>
          <span className="mute" data-label="When">{day(h.at)}</span><span className="cell-main"><span className="t">{h.what}</span></span><span className="clip" data-label="By">{h.who}</span>
          {figure ? <span className="num" data-label={figure}>{h.figure !== undefined && h.figure !== null ? n0(h.figure) : ""}</span> : null}
        </div>
      ))}
    </div>
  );
}
