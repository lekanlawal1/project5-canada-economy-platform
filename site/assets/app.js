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
      font: { family: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', size: 12, color: t.ink2 },
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
    // Short labels on phones so the button fits beside the brand.
    const short = matchMedia("(max-width: 560px)").matches;
    if (btn) btn.textContent = (currentTheme() === "dark" ? "Light" : "Dark") + (short ? "" : " mode");
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
        <span>Canada Economy<span class="brand-long"> Intelligence</span></span></a>
      <nav class="nav" aria-label="Pages">${PAGES.map(([href, label]) =>
        `<a href="${href}"${href === here ? ' aria-current="page"' : ""}>${label}</a>`).join("")}</nav>
      <a class="home-link" href="https://lekanlawal1.github.io/portfolio-site/#economy" title="Back to Lekan Lawal's portfolio">Lekan Lawal</a>
      <button class="theme-btn" type="button"></button></div>`;
    el.querySelector(".theme-btn").addEventListener("click", () =>
      applyTheme(currentTheme() === "dark" ? "light" : "dark"));
    applyTheme(storedTheme());
    // On phones the nav is a swipeable row: bring the current page's link into view.
    const active = el.querySelector('.nav a[aria-current="page"]');
    const nav = el.querySelector(".nav");
    if (active && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = active.offsetLeft - 16;
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

  // ---------- date range control ----------
  /* rangeControl(id, onChange) renders presets (1, 5, 10, 20 years, All) and a Custom range picked
     with Month and Year dropdowns (they behave the same on every browser, iPhone included).
     The choice is kept in the URL (?range=10 or ?from=2019-01&to=2021-12) so a view can be shared.
     Call setBounds(first, last) with the data's first and last month whenever the data changes. */
  const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December"];
  const PRESETS = [["1", "1 year"], ["5", "5 years"], ["10", "10 years"], ["20", "20 years"], ["all", "All"], ["custom", "Custom"]];
  const addYears = (ym, n) => `${+ym.slice(0, 4) + n}${ym.slice(4)}`;
  const clampYm = (ym, lo, hi) => (ym < lo ? lo : ym > hi ? hi : ym);

  function rangeControl(id, onChange) {
    const el = document.getElementById(id);
    const params = new URLSearchParams(location.search);
    const state = { preset: "5", from: params.get("from"), to: params.get("to"), first: null, last: null };
    if (state.from && state.to) state.preset = "custom";
    else if (PRESETS.some(([k]) => k === params.get("range"))) state.preset = params.get("range");

    el.innerHTML = `<span class="seg" role="group" aria-label="Period">${PRESETS.map(([k, label]) =>
        `<button type="button" data-preset="${k}">${label}</button>`).join("")}</span>
      <span class="custom-range" hidden>
        <span class="pick"><span class="pick-label">From</span>
          <select data-part="fm" aria-label="From month"></select><select data-part="fy" aria-label="From year"></select></span>
        <span class="pick"><span class="pick-label">To</span>
          <select data-part="tm" aria-label="To month"></select><select data-part="ty" aria-label="To year"></select></span>
      </span>
      <span class="range-note" aria-live="polite"></span>`;
    const sel = (part) => el.querySelector(`[data-part="${part}"]`);

    function current() {
      const { first, last } = state;
      if (state.preset === "all") return { from: first, to: last };
      if (state.preset === "custom") {
        let from = clampYm(state.from || addYears(last, -5), first, last);
        let to = clampYm(state.to || last, first, last);
        if (from > to) [from, to] = [to, from];  // "From" after "To": swap rather than show nothing
        return { from, to };
      }
      return { from: clampYm(addYears(last, -+state.preset), first, last), to: last };
    }

    function fillPickers(r) {
      const y0 = +state.first.slice(0, 4), y1 = +state.last.slice(0, 4);
      for (const [m, y, value] of [["fm", "fy", r.from], ["tm", "ty", r.to]]) {
        const year = +value.slice(0, 4);
        sel(y).innerHTML = Array.from({ length: y1 - y0 + 1 }, (_, i) => y1 - i)
          .map((yy) => `<option value="${yy}"${yy === year ? " selected" : ""}>${yy}</option>`).join("");
        sel(m).innerHTML = MONTH_NAMES.map((name, i) => {
          const ym = `${year}-${String(i + 1).padStart(2, "0")}`;
          const off = ym < state.first || ym > state.last;  // no data that month
          return `<option value="${i + 1}"${ym === value ? " selected" : ""}${off ? " disabled" : ""}>${name}</option>`;
        }).join("");
      }
    }

    function sync(notify = true) {
      const r = current();
      el.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.preset === state.preset));
      el.querySelector(".custom-range").hidden = state.preset !== "custom";
      fillPickers(r);
      el.querySelector(".range-note").textContent =
        `Showing ${month(r.from)} to ${month(r.to)}. Data available from ${month(state.first)}.`;
      const url = new URL(location.href);
      ["range", "from", "to"].forEach((k) => url.searchParams.delete(k));
      if (state.preset === "custom") { url.searchParams.set("from", r.from); url.searchParams.set("to", r.to); }
      else if (state.preset !== "5") url.searchParams.set("range", state.preset);
      history.replaceState(null, "", url);
      if (notify) onChange(r);
    }

    el.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.preset === "custom" && state.preset !== "custom") {
        const r = current();
        state.from = r.from; state.to = r.to;  // start Custom from what is on screen
      }
      state.preset = b.dataset.preset;
      sync();
    }));
    el.querySelectorAll("select").forEach((s) => s.addEventListener("change", () => {
      const ym = (m, y) => `${sel(y).value}-${String(sel(m).value).padStart(2, "0")}`;
      state.from = ym("fm", "fy");
      state.to = ym("tm", "ty");
      sync();
    }));

    return {
      get: current,
      setBounds(first, last) { state.first = first; state.last = last; sync(false); },
    };
  }

  function sliceRange(cols, r) {
    const keep = cols.month.map((m) => m >= r.from && m <= r.to);
    return Object.fromEntries(Object.entries(cols).map(([k, v]) => [k, v.filter((_, i) => keep[i])]));
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

  return { init, json, chart, tok, month, num, signed, dates, sparkline, tableHTML, geoSelect, fail, layout,
    rangeControl, sliceRange };
})();
