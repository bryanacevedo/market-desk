import { ArrowsLeftRight, DownloadSimple } from "@phosphor-icons/react";
import { api } from "../api";
import { Empty, Failed, Fig, Loading, Section, day, money, n0, useBusy, useData } from "../lib";
import { openSheet } from "../sheets";

export const DEST: Record<string, string> = { account_desk: "Account Desk", events_desk: "Events Desk" };

export function Handoffs() {
  const { data, error, reload } = useData<any>("/api/handoffs");
  const me = useData<any>("/api/me").data;
  const [busy, run] = useBusy();
  if (error) return <div className="page"><Failed error={error} retry={reload} /></div>;
  if (!data) return <div className="page"><div className="head"><h1>Handoffs</h1></div><Loading /></div>;
  const revops = me?.user.role === "revops";
  const cols = "minmax(0,1.2fr) 70px 70px 70px 80px 80px minmax(0,1fr)";
  return (
    <div className="page">
      <div className="head">
        <h1>Handoffs</h1>
        {revops ? (
          <div className="actions">
            <button className="btn line" disabled={busy} onClick={() => run(() => api("/api/books", { method: "POST", body: { destination: "events_desk" } }), "Events Desk document written.")}>New Events Desk document</button>
            <button className="btn" disabled={busy} onClick={() => run(() => api("/api/books", { method: "POST", body: { destination: "account_desk" } }), "Account Desk book written.")}>New Account Desk book</button>
          </div>
        ) : null}
      </div>
      {["account_desk", "events_desk"].map((d) => {
        const books = data.books.filter((b: any) => b.destination === d);
        return (
          <Section key={d} title={DEST[d]} icon={ArrowsLeftRight}>
            {books.length ? (
              <div className="ledger">
                <div className="row head" style={{ gridTemplateColumns: cols }}><span>Version</span><span className="num">Rows</span><span className="num">Added</span><span className="num">Removed</span><span className="num">Tier moved</span><span className="num">Owner moved</span><span>Files</span></div>
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
            {d === "account_desk" && books[0] ? (
              <div className="figs" style={{ marginTop: 8 }}>
                <Fig value={n0(books[books.length - 1].results.accounts)} label="Accounts read back" />
                <Fig value={n0(books[books.length - 1].results.meetings)} label="Meetings" />
                <Fig value={n0(books[books.length - 1].results.opportunities)} label="Opportunities" />
                {me?.money ? <Fig value={money(books[books.length - 1].results.pipeline_cents)} label="Pipeline" /> : null}
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
              <div className="row head" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}><span>Rule Account Desk cannot read</span><span>Why</span></div>
              {p.dropped_rules.map((d: any) => (
                <div key={d.key} className="row" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}><span className="t">{d.rule}</span><span className="mute">{d.why}</span></div>
              ))}
            </div>
          ) : <Empty title="Every rule travels" />}
        </Section>
      ))}
    </div>
  );
}
