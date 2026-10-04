/* Shared code for every page: navigation, theme, formatting, chart defaults, table views.
   Pages call App.chart(...) with a function that builds Plotly traces from the current
   colour tokens, so a theme change simply redraws every chart with the new tokens. */

const App = (() => {
  const PAGES = [
    ["index.html", "Overview"],
    ["labour.html", "Labour"],
    ["prices.html", "Prices"],
    ["housing.html", "Housing"],
    ["provinces.html", "Province compare"],
  ];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const registry = [];

  // ---------- tokens and formatting ----------
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const tok = () => ({
    ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), grid: css("--grid"),
    axis: css("--axis"), surface: css("--surface"), s1: css("--s1"), s2: css("--s2"), s3: css("--s3"),
    neutral: css("--neutral"), band: css("--band"), pos: css("--pos"), neg: css("--neg"),
    accent: css("--accent"),
  });
  const month = (ym) => (ym ? `${MONTHS[+ym.slice(5, 7) - 1]} ${ym.slice(0, 4)}` : "n/a");
  const num = (v, d = 1) => (v == null ? "n/a" : (+v).toLocaleString("en-CA", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const signed = (v, d = 1) => (v == null ? "n/a" : (v > 0 ? "+" : v < 0 ? "−" : "") + num(Math.abs(v), d));
  const dates = (arr) => arr.map((m) => m + "-01");

  async function json(name) {
    const res = await fetch(`data/${name}.json`, { cache: "no-cache" });
    if (!res.ok) throw new Error(`data/${name}.json: HTTP ${res.status}`);
    return res.json();
  }

  // ---------- chart defaults ----------
  const isObj = (o) => o && typeof o === "object" && !Array.isArray(o);
  function merge(a, b) {
    const out = { ...a };
    for (const [k, v] of Object.entries(b || {})) out[k] = isObj(v) && isObj(a[k]) ? merge(a[k], v) : v;
    return out;
  }

  function layout(extra) {
    const t = tok();
    const axis = {
      gridcolor: t.grid, linecolor: t.axis, zerolinecolor: t.axis, tickfont: { color: t.muted, size: 11 },
      title: { font: { color: t.muted, size: 11 } }, automargin: true,
    };
    return merge({
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', size: 12, color: t.ink2 },
      margin: { l: 8, r: 12, t: 8, b: 8 },
      xaxis: merge(axis, { showgrid: false, type: "date", hoverformat: "%b %Y", showline: true }),
      yaxis: merge(axis, { showgrid: true, zeroline: false }),
      hovermode: "x unified",
      hoverlabel: { bgcolor: t.surface, bordercolor: t.axis, font: { color: t.ink, size: 12 } },
      legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { color: t.ink2, size: 12 } },
      showlegend: false,
    }, extra);
  }
  const CONFIG = { displayModeBar: false, responsive: true };

  /* chart(id, build, table)
     build(t) returns {data, layout}; t holds the current colour tokens.
     table() returns {head: [...], rows: [[...], ...]} for the table view twin. */
  function chart(id, build, table) {
    const el = document.getElementById(id);
    const entry = { el, build, table };
    const existing = registry.find((r) => r.el === el);
    if (existing) Object.assign(existing, entry); else registry.push(entry);
    draw(entry);
  }

  function draw(entry) {
    const t = tok();
    const spec = entry.build(t);
    Plotly.react(entry.el, spec.data, layout(spec.layout), CONFIG);
    if (entry.table) renderTable(entry);
  }

  function renderTable(entry) {
    let details = entry.el.nextElementSibling;
    if (!details || !details.matches("details.data")) {
      details = document.createElement("details");
      details.className = "data";
      details.innerHTML = "<summary>Show data table</summary><div class='table-wrap'></div>";
      entry.el.after(details);
    }
    const { head, rows } = entry.table();
    details.querySelector(".table-wrap").innerHTML = tableHTML(head, rows);
  }

  function tableHTML(head, rows) {
    const esc = (s) => String(s ?? "n/a").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
    return `<table><thead><tr>${head.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead>` +
      `<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  const redrawAll = () => registry.forEach(draw);

  // ---------- sparkline (inline SVG, for stat tiles) ----------
  function sparkline(values, color) {
    const v = values.filter((x) => x != null);
    if (v.length < 2) return "";
    const min = Math.min(...v), max = Math.max(...v), span = max - min || 1;
    const pts = values.map((x, i) => x == null ? null :
      `${(i / (values.length - 1)) * 100},${36 - ((x - min) / span) * 32}`).filter(Boolean);
    const last = pts[pts.length - 1].split(",");
    return `<svg viewBox="-2 0 104 40" preserveAspectRatio="none" aria-hidden="true">
      <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="2"
        vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${last[0]}" cy="${last[1]}" r="2.5" fill="${color}" vector-effect="non-scaling-stroke"/></svg>`;
  }

  // ---------- theme ----------
  function storedTheme() { try { return localStorage.getItem("theme"); } catch { return null; } }
  function applyTheme(theme) {
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
    try { theme ? localStorage.setItem("theme", theme) : localStorage.removeItem("theme"); } catch { /* private mode */ }
    const btn = document.querySelector(".theme-btn");
    if (btn) btn.textContent = currentTheme() === "dark" ? "Light mode" : "Dark mode";
    redrawAll();
  }
  const currentTheme = () => document.documentElement.getAttribute("data-theme") ||
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

  // ---------- header and footer ----------
  function header() {
    const here = location.pathname.split("/").pop() || "index.html";
    const el = document.getElementById("top");
    el.className = "top";
    el.innerHTML = `<div class="top-inner">
      <a class="brand" href="index.html">
        <svg class="brand-mark" viewBox="0 0 22 22" aria-hidden="true"><rect width="22" height="22" rx="5" fill="var(--accent)"/>
          <path d="M5 15l4-4 3 3 5-6" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Canada Economy Intelligence</a>
      <nav class="nav" aria-label="Pages">${PAGES.map(([href, label]) =>
        `<a href="${href}"${href === here ? ' aria-current="page"' : ""}>${label}</a>`).join("")}</nav>
      <button class="theme-btn" type="button"></button></div>`;
    el.querySelector(".theme-btn").addEventListener("click", () =>
      applyTheme(currentTheme() === "dark" ? "light" : "dark"));
    applyTheme(storedTheme());
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redrawAll);
  }

  async function footer() {
    const el = document.getElementById("foot");
    try {
      const meta = await json("meta");
      const t = meta.tests;
      const ok = t.errors.length === 0;
      const colour = ok ? "var(--good)" : "var(--neg)";
      el.innerHTML = `
        <p class="health"><span class="dot" style="background:${colour}"></span>
          <span><b>${ok ? "All data tests passing" : "Data tests failing"}</b>: ${t.passed} passed,
          ${t.warnings.length} warnings, ${t.errors.length} errors. Built ${meta.built_at}.</span></p>
        <p>Source: Statistics Canada, ${meta.sources.map((s) =>
          `<a href="${s.url}">${s.label} (${s.table_code})</a>, to ${month(s.max_ref_date)}`).join("; ")}.
          Contains information licensed under the Open Government Licence: Canada.</p>
        <p>Every number is computed in SQL and checked against StatCan's official releases.
          <a href="${meta.repo}">Code, tests and method notes</a>.</p>`;
    } catch (err) {
      el.textContent = "Data status unavailable.";
    }
  }

  function geoSelect(id, geos, value, onChange) {
    const sel = document.getElementById(id);
    sel.innerHTML = geos.map((g) => `<option${g === value ? " selected" : ""}>${g}</option>`).join("");
    sel.addEventListener("change", () => onChange(sel.value));
  }

  function fail(err) {
    console.error(err);
    const main = document.querySelector("main");
    main.insertAdjacentHTML("afterbegin",
      `<p class="notice">The data for this page could not be loaded (${err.message}).</p>`);
  }

  function init() { header(); footer(); }

  return { init, json, chart, tok, month, num, signed, dates, sparkline, tableHTML, geoSelect, fail, layout };
})();
