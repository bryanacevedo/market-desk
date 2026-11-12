// Layout check 1b, ported from Events Desk's scripts/audit-layout.mjs: every row of figures has each label centred under
// its figure, all labels on one baseline, and equal space between figures. Paste into the browser console on any page;
// it returns a list of problems (empty when it passes).
(() => {
  const out = [];
  for (const row of document.querySelectorAll(".figs")) {
    const figs = [...row.querySelectorAll(":scope > .fig")].map((p) => ({ b: p.querySelector("b")?.getBoundingClientRect(), s: p.querySelector(":scope > span")?.getBoundingClientRect(), p: p.getBoundingClientRect() })).filter((f) => f.b && f.s);
    for (const f of figs) if (Math.abs((f.b.left + f.b.right) / 2 - (f.s.left + f.s.right) / 2) > 2 && Math.abs(f.b.left - f.s.left) > 2) out.push(`figure label not aligned with its figure (${Math.round(f.s.left)}px)`);
    const lines = new Map();
    for (const f of figs) { const key = [...lines.keys()].find((t) => Math.abs(t - f.p.bottom) < 30) ?? f.p.bottom; lines.set(key, [...(lines.get(key) ?? []), f]); }
    for (const line of lines.values()) if (line.length > 1 && Math.max(...line.map((f) => f.s.bottom)) - Math.min(...line.map((f) => f.s.bottom)) > 1) out.push("figure labels not on one baseline");
    const gaps = figs.slice(1).map((f, i) => (f.p.top === figs[i].p.top ? f.p.left - figs[i].p.right : null)).filter((g) => g !== null);
    if (gaps.length > 1 && Math.max(...gaps) - Math.min(...gaps) > 2) out.push(`uneven space between figures: ${gaps.map(Math.round).join(", ")}px`);
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 1) out.push(`page scrolls sideways by ${document.documentElement.scrollWidth - window.innerWidth}px`);
  return out;
})();
