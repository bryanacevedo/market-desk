import { useEffect, type ReactNode } from "react";
import {
  ArrowsLeftRight, CaretRight, ChartPieSlice, Database, DotsThree, Flask, GearSix, Lightbulb, ListChecks, MapTrifold,
  Scales, Target,
} from "@phosphor-icons/react";
import { setActingAs } from "./api";
import { Failed, Toaster, changed, navigate, setNow, useData, usePath } from "./lib";
import { SheetHost } from "./sheets";
import { Market } from "./pages/Market";
import { Evidence } from "./pages/Evidence";
import { Profile } from "./pages/Profile";
import { Accounts } from "./pages/Accounts";
import { Territories } from "./pages/Territories";
import { Tests } from "./pages/Tests";
import { Changes } from "./pages/Changes";
import { Handoffs } from "./pages/Handoffs";
import { Settings, Sources } from "./pages/Desk";

export type Me = { user: { id: number; name: string; role: string }; users: { id: number; name: string; role: string }[];
  counts: Record<string, number>; money: boolean; now: string; simulated: boolean; public_demo: boolean; seller: string };

type Route = { path: string; label: string; icon: ReactNode; page: () => JSX.Element; roles: string[]; count?: string; group?: string; bar?: boolean };
const LEAD = ["revops", "manager", "gtm"];
const ROUTES: Route[] = [
  { path: "/", label: "Market", icon: <ChartPieSlice size={18} />, page: Market, roles: LEAD, bar: true },
  { path: "/accounts", label: "Accounts", icon: <Target size={18} />, page: Accounts, roles: LEAD, bar: true },
  { path: "/changes", label: "Changes", icon: <Lightbulb size={18} />, page: Changes, roles: LEAD, count: "changes", bar: true },
  { path: "/evidence", label: "Evidence", icon: <Scales size={18} />, page: Evidence, roles: LEAD, group: "ICP" },
  { path: "/profile", label: "ICP", icon: <ListChecks size={18} />, page: Profile, roles: LEAD, count: "icp" },
  { path: "/tests", label: "Tests", icon: <Flask size={18} />, page: Tests, roles: LEAD },
  { path: "/territories", label: "Territories", icon: <MapTrifold size={18} />, page: Territories, roles: LEAD, group: "Coverage", count: "plans" },
  { path: "/handoffs", label: "Handoffs", icon: <ArrowsLeftRight size={18} />, page: Handoffs, roles: LEAD },
  { path: "/sources", label: "Sources", icon: <Database size={18} />, page: Sources, roles: ["revops"], group: "Admin" },
  { path: "/settings", label: "Settings", icon: <GearSix size={18} />, page: Settings, roles: ["revops"] },
];

const ROLE: Record<string, string> = { revops: "RevOps", manager: "Manager", gtm: "GTM leader" };

export function App() {
  const [path] = usePath();
  const { data: me, error: meError, reload } = useData<Me>("/api/me");
  useEffect(() => {
    // A first visit opens as RevOps, who sees the whole desk; the choice is kept after that.
    let chosen: string | null = null;
    try { chosen = localStorage.getItem("acting-as"); } catch { /* private mode */ }
    if (me && !chosen) {
      const revops = me.users.find((u) => u.role === "revops");
      if (revops && me.user.id !== revops.id) { setActingAs(revops.id); changed(); }
    }
  }, [me]);
  useEffect(() => { if (me?.now) setNow(me.now); }, [me?.now]);
  const routes = ROUTES.filter((r) => me && r.roles.includes(me.user.role));
  const bar = routes.filter((r) => r.bar);
  const rest = routes.filter((r) => !r.bar);
  const more: Route = { path: "/more", label: "More", icon: null, page: () => <More routes={rest} />, roles: [] };
  const route = path === "/more" ? more : routes.find((r) => r.path === path) || routes[0];
  useEffect(() => { if (route) document.title = `${route.label}, Market Desk`; }, [route?.label]);
  useEffect(() => {
    // A page this role does not have lands on the role's first page, once the role is settled.
    let chosen: string | null = null;
    try { chosen = localStorage.getItem("acting-as"); } catch { /* private mode */ }
    if (!chosen) return;
    if (me && route && path !== route.path && path !== "/more") navigate(route.path + window.location.search, true);
  }, [me, path, route]);
  if (meError && !me) return <div className="app"><main className="main"><div className="page"><Failed error={meError} retry={reload} /></div></main></div>;
  if (!route) return <Toaster />;
  const Page = route.page;
  const pick = (id: number) => { setActingAs(id); changed(); };
  return (
    <div className="app">
      <aside className="side">
        <div className="brand-block"><div className="brand"><Mark />Market Desk</div></div>
        <nav className="nav" aria-label="Main">
          {routes.map((r) => (
            <div key={r.path} style={{ display: "contents" }}>
              {r.group ? <div className="group">{r.group}</div> : null}
              <a href={r.path} aria-current={r.path === route.path ? "page" : undefined} onClick={(e) => { e.preventDefault(); navigate(r.path); }}>
                {r.icon}<span>{r.label}</span>
                {r.count && me?.counts[r.count] ? <span className="n" aria-label={`${me.counts[r.count]} open`}>{me.counts[r.count]}</span> : null}
              </a>
            </div>
          ))}
        </nav>
        <div className="grow" />
        <div className="side-foot">
          {me?.simulated ? <div className="clock"><span className="when">{new Date(me.now).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span><span className="note">Invented company, simulated sources.</span></div> : null}
          {me && me.users.length ? (
            <div className="acting">
              <label htmlFor="acting">Acting as</label>
              <select id="acting" className="select" value={me.user.id} onChange={(e) => pick(Number(e.target.value))}>
                {me.users.map((u) => <option key={u.id} value={u.id}>{u.name}, {ROLE[u.role]}</option>)}
              </select>
            </div>
          ) : null}
        </div>
      </aside>
      <main className="main">
        <div className="phone-bar">
          <span className="brand" style={{ margin: 0 }}><Mark />{route.label}</span>
          {me && me.users.length ? (
            <select className="select" style={{ width: 170, height: 40 }} value={me.user.id} aria-label="Acting as" onChange={(e) => pick(Number(e.target.value))}>
              {me.users.map((u) => <option key={u.id} value={u.id}>{u.name.split(" ")[0]}, {ROLE[u.role]}</option>)}
            </select>
          ) : null}
        </div>
        {me ? <div className="page-enter" key={`${route.path}:${me.user.id}`}><Page /></div> : null}
      </main>
      <nav className="phone-nav" aria-label="Main">
        {bar.map((r) => (
          <a key={r.path} href={r.path} aria-current={r.path === route.path ? "page" : undefined} onClick={(e) => { e.preventDefault(); navigate(r.path); }}>
            <span className="pn-icon">{r.icon}{r.count && me?.counts[r.count] ? <i className="pn-n">{me.counts[r.count]}</i> : null}</span><span>{r.label}</span>
          </a>
        ))}
        {rest.length ? (
          <a href="/more" aria-current={route.path === "/more" || rest.some((r) => r.path === route.path) ? "page" : undefined}
            onClick={(e) => { e.preventDefault(); navigate("/more"); }}><span className="pn-icon"><DotsThree size={18} weight="bold" /></span><span>More</span></a>
        ) : null}
      </nav>
      {me ? <SheetHost key={`${me.user.id}`} /> : null}
      <Toaster />
    </div>
  );
}

function More({ routes }: { routes: Route[] }) {
  return (
    <div className="page">
      <div className="head"><h1>More</h1></div>
      <div className="ledger">
        {routes.map((r) => (
          <a key={r.path} href={r.path} className="row" style={{ gridTemplateColumns: "24px minmax(0,1fr) auto" }}
            onClick={(e) => { e.preventDefault(); navigate(r.path); }}>
            <span className="mute">{r.icon}</span><span className="cell-main"><span className="t">{r.label}</span></span><CaretRight size={16} className="mute" />
          </a>
        ))}
      </div>
    </div>
  );
}

/** The Market Desk mark, in ochre: the market, the part we can reach, the part we can win, drawn as nested ranges. */
export function Mark() {
  return (
    <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#A2671F" />
      <path d="M7 25V12a5 5 0 0 1 5-5h13" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M12 25v-6a3 3 0 0 1 3-3h10" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeOpacity=".7" />
      <circle cx="21" cy="21.5" r="3" fill="#fff" />
    </svg>
  );
}
