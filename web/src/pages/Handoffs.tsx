import { ArrowsLeftRight, DownloadSimple } from "@phosphor-icons/react";
import { api } from "../api";
import { Empty, Failed, Fig, Loading, Section, day, money, n0, useBusy, useData, T } from "../lib";
import { openSheet } from "../sheets";

export const DEST: Record<string, string> = { account_desk: "Account Desk", events_desk: "Events Desk" };

export function Handoffs() {
  const { data, error, reload } = useData<any>("/api/handoffs");
  const me = useData<any>("/api/me").data;
  const [busy, run] = useBusy();
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Handoffs</h1></div><Loading /></div>;
  const revops = me?.user.role === "revops";
  const cols = "minmax(0,1.2fr) 70px 70px 80px 90px 100px minmax(0,1fr)";
  return (
    <div className="page">
      <div className="head">
        <h1>Handoffs</h1>
        {revops ? (
          <div className="actions">
            <button className="btn line" disabled={busy} onClick={() => run(() => api("/api/books", { method: "POST", body: { destination: "events_desk" } }), "Events Desk file written.")}>New Events Desk file</button>
            <button className="btn line" disabled={busy} onClick={() => run(() => api("/api/books", { method: "POST", body: { destination: "account_desk" } }), "Account Desk file written.")}>New Account Desk file</button>
          </div>
        ) : null}
      </div>
      {["account_desk", "events_desk"].map((d) => {
        const books = data.books.filter((b: any) => b.destination === d);
        const back = books.find((b: any) => b.results.accounts);
        return (
          <Section key={d} title={DEST[d]} icon={ArrowsLeftRight}>
            {books.length ? (
              <div className="ledger">
                <div className="row head" style={{ gridTemplateColumns: cols }}><T>Version</T><T num>Rows</T><T num>Added</T><T num>Removed</T><T num>Tier moved</T><T num>Owner moved</T><T>Files</T></div>
                {books.map((b: any) => (
                  <div key={b.id} className="row" style={{ gridTemplateColumns: cols }}>
                    <button className="link-row cell-main" onClick={() => openSheet("book", b.id)}><span className="t">Version {b.version}</span><span className="s">{day(b.created_at)}, profile v{b.icp_number}</span></button>
                    <span className="num">{n0(b.rows)}</span><span className="num">{n0(b.diff.added)}</span><span className="num">{n0(b.diff.removed)}</span>
                    <span className="num">{n0(b.diff.tier_moved)}</span><span className="num">{n0(b.diff.owner_moved)}</span>
                    <span className="actions">{b.files.map((f: string) => <a key={f} className="btn quiet sm" href={`/api/books/${b.id}/files/${f}`} download><DownloadSimple size={14} />{f}</a>)}</span>
                  </div>
                ))}
              </div>
            ) : <Empty title="Nothing sent yet" />}
            {d === "account_desk" && books[0] && !back ? <div className="small mute" style={{ marginTop: 8 }}>No results back from Account Desk yet</div> : null}
            {d === "account_desk" && back ? (
              <div className="figs" style={{ marginTop: 8 }}>
                <Fig value={n0(back.results.accounts)} label={`Accounts worked, version ${back.version}`} />
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
      {data.previews.map((p: any) => (
        <Section key={p.id} title={`From draft v${p.version}`} right={<a className="btn quiet sm" href={`/api/handoffs/preview/${p.id}/icp.json`} download><DownloadSimple size={14} />icp.json</a>}>
          {p.dropped_rules.length ? (
            <div className="ledger">
              <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}><T>Not sent to Account Desk</T><T>Why</T></div>
              {p.dropped_rules.map((d: any) => (
                <div key={d.key} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}><span className="t">{d.rule}</span><span className="mute">{d.why}</span></div>
              ))}
            </div>
          ) : <Empty title="All rules sent" />}
        </Section>
      ))}
    </div>
  );
}
