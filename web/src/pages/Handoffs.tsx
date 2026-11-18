import { ArrowsLeftRight, DownloadSimple } from "@phosphor-icons/react";
import { api } from "../api";
import { Empty, Failed, Fig, Loading, Section, day, deliveryLine, deskName, money, n0, say, Status, changed, useBusy, useData, writeHint, T } from "../lib";
import { openSheet } from "../sheets";

export const DEST: Record<string, string> = { account_desk: "Account Desk", events_desk: "Events Desk" };

export function Handoffs() {
  const { data, error, reload } = useData<any>("/api/handoffs");
  const me = useData<any>("/api/me").data;
  const [busy, run] = useBusy();
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Handoffs</h1></div><Loading /></div>;
  const revops = me?.user.role === "revops";
  const behind: string[] = data.behind?.destinations || [];
  // Decision 67: after a publish the files are behind; RevOps (the only role that makes files) makes both here, one after the other.
  const makeBoth = () => run(async () => {
    await api("/api/books", { method: "POST", body: { destination: "account_desk" } });
    try { await api("/api/books", { method: "POST", body: { destination: "events_desk" } }); }
    catch (e: any) { changed(); throw new Error(`The file for ${deskName("account_desk")} was written. The file for ${deskName("events_desk")} was not: ${e.message}`); }
  }, "Both files written. Download and pass them on from here.");
  const cols = "minmax(0,1.2fr) 70px 70px 80px 90px 100px minmax(0,1fr)";
  const crmCols = "minmax(0,1.2fr) minmax(0,1fr) minmax(0,1fr)";
  return (
    <div className="page">
      <div className="head">
        <div><h1>Handoffs</h1><div className="sub">The files this desk makes for your other tools, and what came back from them.</div></div>
        {revops && data.next ? <span className="small mute">New files use profile v{data.next.profile}{data.next.plan ? ` and ${data.next.plan}` : ""}</span> : null}
        {revops ? (
          <div className="actions">
            <button className="btn line" disabled={busy} title={writeHint()} onClick={() => run(() => api("/api/books", { method: "POST", body: { destination: "events_desk" } }), "The events file is written.")}>New file for {deskName("events_desk")}</button>
            <button className="btn line" disabled={busy} title={writeHint()} onClick={() => run(() => api("/api/books", { method: "POST", body: { destination: "account_desk" } }), "The outreach file is written.")}>New file for {deskName("account_desk")}</button>
          </div>
        ) : null}
      </div>
      {behind.length ? (
        <div className="notice waiting"><Status kind="wait">{`The files use a profile other than the published version ${data.behind.profile}`}</Status>
          {revops
            ? <button className="btn" disabled={busy} title={writeHint()} onClick={makeBoth}>Make both files now</button>
            : <span className="small mute">RevOps makes the new files. Nothing goes out by itself.</span>}
        </div>
      ) : null}
      {["account_desk", "events_desk"].map((d) => {
        const books = data.books.filter((b: any) => b.destination === d);
        const back = books.find((b: any) => b.results.accounts);
        return (
          <Section key={d} title={`Files for ${DEST[d]}`} icon={ArrowsLeftRight}>
            {books.length ? (
              <div className="ledger">
                <div className="row head" style={{ gridTemplateColumns: cols }}><T>Version</T><T num>Rows</T><T num>Added</T><T num>Removed</T><T num>Tier moved</T><T num>Owner moved</T><T>Files</T></div>
                {books.map((b: any) => (
                  <div key={b.id} className="row" style={{ gridTemplateColumns: cols }}>
                    <button className="link-row cell-main" onClick={() => openSheet("book", b.id)}><span className="t">Version {b.version}</span><span className="s">{day(b.created_at)}, profile v{b.icp_number}{b.created_by ? `, by ${b.created_by}` : ""}</span></button>
                    <span className="num">{d === "events_desk" ? <span className="mute">Document</span> : n0(b.rows)}</span><span className="num">{n0(b.diff.added)}</span><span className="num">{n0(b.diff.removed)}</span>
                    <span className="num">{n0(b.diff.tier_moved)}</span><span className="num">{n0(b.diff.owner_moved)}</span>
                    <span className="actions">{b.files.map((f: string) => <a key={f} className="btn quiet sm" href={`/api/books/${b.id}/files/${f}`} download><DownloadSimple size={14} />{f}</a>)}</span>
                  </div>
                ))}
              </div>
            ) : <Empty title="No file made yet" example={d === "account_desk" ? "Version 1, 14 Nov, profile v3, 1,300 rows, with accounts.csv and icp.json to download." : "Version 1, 14 Nov, profile v3, with icp.md to download."}>{d === "account_desk" ? "Each file lists the accounts the plan gives to people, with their tier and owner, for the outreach tool." : "Each file is the ICP as a document for the events tool."}</Empty>}
            {d === "account_desk" && books[0] && !back ? <div className="small mute" style={{ marginTop: 8 }}>{`No results back from ${deskName("account_desk")} yet`}</div> : null}
            {d === "account_desk" && back ? (
              <div className="figs" style={{ marginTop: 8 }}>
                <Fig value={n0(back.results.accounts)} label={`Accounts worked from version ${back.version}`} />
                <Fig value={n0(back.results.meetings)} label="Meetings" />
                <Fig value={n0(back.results.opportunities)} label="Opportunities" />
                {me?.money ? <Fig value={money(back.results.pipeline_cents)} label="Pipeline" /> : null}
              </div>
            ) : null}
            {d === "events_desk" ? (
              <div className="figs" style={{ marginTop: 8 }}>
                <Fig value={n0(data.events.accounts)} label="Accounts met at events" />
                <Fig value={n0(data.events.meetings)} label="Meetings" />
                <Fig value={n0(data.events.opportunities)} label="Opportunities" />
              </div>
            ) : null}
          </Section>
        );
      })}
      {data.crm ? (
        <Section title="CRM Desk" icon={ArrowsLeftRight}>
          <div className="figs">
            <Fig value={n0(data.crm.sent)} label={data.crm.last_sent_at ? `Accounts sent, ${day(data.crm.last_sent_at)}` : "Accounts sent"} />
            <Fig value={n0(data.crm.refusals.length)} label="Refused" />
            {data.crm.icp?.published ? <Fig value={n0(data.crm.icp.accounts_on_published)} label={`On profile version ${data.crm.icp.published}`} /> : null}
            {data.crm.queued ? <Fig value={n0(data.crm.queued)} label="Waiting to send" /> : null}
            {data.crm.errors.length ? <Fig value={n0(data.crm.errors.length)} label="Not taken" /> : null}
          </div>
          {data.crm.deliveries?.length ? (
            <div className="ledger" style={{ marginTop: 8 }}>
              <div className="row head" style={{ gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1.2fr)" }}><T>Sent</T><T>Where it stands</T></div>
              {data.crm.deliveries.map((d: any) => (
                <div key={d.ref} className="row" style={{ gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1.2fr)" }}>
                  <span className="t">{d.what}</span>
                  <span className="mute" data-label="Where it stands">{deliveryLine({ sent: d.sent, waiting: d.waiting, failed: d.failed, sent_at: d.sent_at, any: true })}{d.failed && d.error ? `: ${d.error}` : ""}</span>
                </div>
              ))}
            </div>
          ) : null}
          {data.crm.failed.length ? (
            <div className="notice" style={{ marginTop: 8 }}>{data.crm.failed.length === 1 ? "One send was" : `${data.crm.failed.length} sends were`} {say("refused by CRM Desk")}: {data.crm.failed[0].last_error}</div>
          ) : null}
          {data.crm.errors.length ? (
            <div className="ledger" style={{ marginTop: 8 }}>
              <div className="row head" style={{ gridTemplateColumns: crmCols }}><T>Account</T><T>Not taken</T><T>Why</T></div>
              {data.crm.errors.map((e: any) => (
                <div key={e.domain} className="row" style={{ gridTemplateColumns: crmCols }}>
                  {e.company ? <button className="link-row cell-main" onClick={() => openSheet("company", e.company)}><span className="t">{e.name}</span></button> : <span className="t">{e.name}</span>}
                  <span>All of it</span><span className="mute">{e.error}</span>
                </div>
              ))}
            </div>
          ) : null}
          {data.crm.refusals.length ? (
            <div className="ledger" style={{ marginTop: 8 }}>
              <div className="row head" style={{ gridTemplateColumns: crmCols }}><T>Account</T><T>Change</T><T>Why it was refused</T></div>
              {data.crm.refusals.map((r: any) => (
                <div key={`${r.domain}${r.field}`} className="row" style={{ gridTemplateColumns: crmCols }}>
                  {r.company ? <button className="link-row cell-main" onClick={() => openSheet("company", r.company)}><span className="t">{r.name}</span></button> : <span className="t">{r.name}</span>}
                  <span>{r.what} to {r.proposed_name}</span>
                  <span className="mute">{r.why}</span>
                </div>
              ))}
            </div>
          ) : null}
        </Section>
      ) : null}
      {data.previews.map((p: any) => (
        <Section key={p.id} title={`From draft v${p.version}`} right={<a className="btn quiet sm" href={`/api/handoffs/preview/${p.id}/icp.json`} download><DownloadSimple size={14} />icp.json</a>}>
          {p.dropped_rules.length ? (
            <div className="ledger">
              <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}><T>Not sent to Account Desk</T><T>Why</T></div>
              {p.dropped_rules.map((d: any) => (
                <div key={d.key} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}><span className="t">{d.rule}</span><span className="mute">{d.why}</span></div>
              ))}
            </div>
          ) : <Empty title="All rules sent">Every rule of this draft fits the outreach file. A rule it cannot carry would be listed here with the reason.</Empty>}
        </Section>
      ))}
    </div>
  );
}
