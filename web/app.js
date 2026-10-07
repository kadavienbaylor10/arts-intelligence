/* Charlie dashboard: Opportunities + Sources, reading and writing your Supabase database. */
(function () {
  const CFG = window.CHARLIE_CONFIG || {};
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const MARKETS = ["Dallas–Fort Worth", "New York City", "Los Angeles", "Chicago", "Houston", "Washington, DC", "Philadelphia", "Miami", "Atlanta", "Phoenix", "San Francisco Bay Area", "Seattle", "Denver", "Austin", "Raleigh–Durham", "Nashville", "Orlando", "San Antonio", "Las Vegas", "New Orleans"];
  const STATES = ["AZ", "CA", "CO", "DC", "FL", "GA", "IL", "LA", "NC", "NV", "NY", "PA", "TN", "TX", "WA"];
  const STATUSES = [["new", "Not reviewed", "--s-new"], ["interested", "Interested", "--s-interested"], ["applying", "Applying", "--s-applying"],
    ["submitted", "Submitted", "--s-submitted"], ["awarded", "Awarded", "--s-awarded"], ["declined", "Declined", "--s-declined"], ["notselected", "Not selected", "--s-notselected"]];
  const STATUS = Object.fromEntries(STATUSES.map(s => [s[0], s]));
  const LABEL_TO_STATUS = Object.fromEntries(STATUSES.map(s => [s[1].toLowerCase(), s[0]]));

  if (!CFG.SUPABASE_URL || CFG.SUPABASE_URL.includes("YOUR-PROJECT") || !window.supabase) {
    document.body.innerHTML = `<div class="signin"><h1>Charlie</h1><p class="summary">Setup isn't finished: add your Supabase project URL and public key to <b>web/config.js</b> in GitHub, then reload.</p></div>`;
    return;
  }
  const sb = window.supabase.createClient(CFG.SUPABASE_URL, CFG.SUPABASE_ANON_KEY);

  let opps = [], sources = [], statePlaces = {};
  const f = { q: "", city: "", elig: "ind", origin: "", sort: "deadline", showdone: false, statuses: new Set() };
  const sf = { q: "", view: "active", state: "", fail: false };

  // ---------- dates ----------
  const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
  const parseDate = s => { if (!/^\d{4}-\d{2}-\d{2}/.test(s || "")) return null; const [y, m, d] = s.slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); };
  const daysUntil = d => Math.round((d - today()) / 86400000);
  const fmt = d => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
  function localDate(ts, tz) {
    if (!ts) return null;
    try {
      const p = new Intl.DateTimeFormat("en-CA", { timeZone: tz || "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(ts));
      return parseDate(p);
    } catch (e) { return parseDate(String(ts)); }
  }
  const deadlineOf = o => parseDate(o.my_deadline) || localDate(o.sys_deadline, o.local_timezone);
  const openOf = o => parseDate(o.my_open_date);
  const statusOf = o => (STATUS[o.my_status] ? o.my_status : "new");
  const isClosed = o => { const d = deadlineOf(o); return d ? daysUntil(d) < 0 : false; };
  const linkOf = o => o.my_link || o.source_url || "";

  let syncTimer;
  function setSync(msg) { $("#sync").textContent = msg; clearTimeout(syncTimer); syncTimer = setTimeout(() => { $("#sync").textContent = ""; }, 4000); }

  // ---------- auth ----------
  async function showForSession(session) {
    $("#signin").hidden = !!session;
    $("#app").hidden = !session;
    if (session) await loadAll();
  }
  $("#signinBtn").addEventListener("click", async () => {
    const msg = $("#signinMsg"); msg.className = "msg"; msg.textContent = "Signing in…";
    const { error } = await sb.auth.signInWithPassword({ email: $("#email").value.trim(), password: $("#password").value });
       if (error) { msg.className = "msg err"; msg.textContent = "Sign-in failed: " + (error.message || "unknown error"); }
    else msg.textContent = "";
  });
  $("#password").addEventListener("keydown", e => { if (e.key === "Enter") $("#signinBtn").click(); });
  $("#signout").addEventListener("click", () => sb.auth.signOut());
  sb.auth.onAuthStateChange((_evt, session) => showForSession(session));
  sb.auth.getSession().then(({ data }) => showForSession(data.session));

  // ---------- data ----------
  async function loadAll() {
    const [o, s, p] = await Promise.all([
      sb.from("v_dash_opps").select("*"),
      sb.from("v_dash_sources").select("*"),
      sb.from("places").select("id,state_code,place_kind"),
    ]);
    if (o.error || s.error) { $("#summary").textContent = "Couldn't load your data. Reload the page; if it keeps happening, check the setup steps."; return; }
    opps = o.data || []; sources = s.data || [];
    statePlaces = {}; (p.data || []).filter(x => x.place_kind === "state").forEach(x => { statePlaces[x.state_code] = x.id; });
    if (!opps.length && !sources.length) {
      $("#summary").textContent = "You're signed in, but this email isn't on Charlie's access list yet. Add it with the app_admins step in the setup guide.";
      return;
    }
    render(); renderSources();
  }
  async function updateOpp(id, patch) {
    const o = opps.find(x => x.id === id); Object.assign(o, patch);
    render();
    const { error } = await sb.from("opportunities").update({ ...patch, my_updated_at: new Date().toISOString() }).eq("id", id);
    setSync(error ? "Couldn't save that change. Check your connection and try again." : "Saved.");
  }
  async function updateSource(id, patch) {
    const s = sources.find(x => x.id === id); Object.assign(s, patch);
    renderSources();
    const { error } = await sb.from("sources").update(patch).eq("id", id);
    setSync(error ? "Couldn't save that change. Check your connection and try again." : "Saved.");
  }

  // ---------- opportunities ----------
  function visible() {
    const q = f.q.trim().toLowerCase();
    return opps.filter(o => {
      if (o.in_scope === false) return false;
      const st = statusOf(o);
      if (f.city && o.market !== f.city) return false;
      if (f.origin && o.origin !== f.origin) return false;
      if (f.elig === "ind" && o.eligibility === "org") return false;
      if (f.elig === "org" && o.eligibility !== "org") return false;
      if (f.statuses.size && !f.statuses.has(st)) return false;
      if (!f.showdone && !f.statuses.size && (st === "declined" || st === "notselected" || (isClosed(o) && st === "new"))) return false;
      if (["EXPIRED", "CANCELED"].includes(o.validity) && o.origin === "scan" && !f.showdone) return false;
      if (q && !`${o.name} ${o.market || ""} ${o.my_notes || ""} ${o.supports_text || ""} ${o.issuer || ""}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }
  const sortKey = o => { const d = deadlineOf(o); if (!d) return 5e5; const n = daysUntil(d); return n < 0 ? 1e6 - n : n; };
  const byDeadline = (a, b) => sortKey(a) - sortKey(b) || String(a.market).localeCompare(String(b.market)) || a.name.localeCompare(b.name);

  function verifyTag(o) {
    if (o.origin === "catalog") return o.checked_official ? `<span class="tag">Checked</span>` : `<span class="tag verify">Unverified</span>`;
    if (o.validity === "ACTIVE") return `<span class="tag">Confirmed open</span>`;
    if (o.validity === "UPCOMING") return `<span class="tag">Expected / not open yet</span>`;
    return `<span class="tag verify">Verify details</span>`;
  }
  function amountText(o) {
    if (o.amount_text) return o.amount_text;
    if (o.funding_max) return (o.funding_min ? `$${Number(o.funding_min).toLocaleString()}–` : "Up to ") + `$${Number(o.funding_max).toLocaleString()}`;
    return "";
  }
  function rowHTML(o) {
    const st = statusOf(o), sc = STATUS[st], dl = deadlineOf(o), op = openOf(o);
    let when, count = "", urgent = false;
    if (dl) {
      const n = daysUntil(dl); when = fmt(dl);
      if (n < 0) count = "Closed"; else if (n === 0) { count = "Due today"; urgent = true; }
      else { count = n === 1 ? "Due tomorrow" : `in ${n} days`; urgent = n <= 14 && !["submitted", "declined", "awarded", "notselected"].includes(st); }
    } else if (op && daysUntil(op) >= 0) { when = "Opens " + fmt(op); count = `in ${daysUntil(op)} days`; }
    else { when = "No date"; count = "Add when announced"; }
    const link = linkOf(o);
    const linkHTML = link ? `<a href="${esc(link)}" target="_blank" rel="noopener">Open link</a>`
      : `<a class="search" href="https://www.google.com/search?q=${encodeURIComponent(o.name + " " + (o.market || "") + " artist grant")}" target="_blank" rel="noopener">Search</a>`;
    const opts = STATUSES.map(s => `<option value="${s[0]}"${s[0] === st ? " selected" : ""}>${s[1]}</option>`).join("");
    const meta = [amountText(o), o.supports_text || o.issuer].filter(Boolean).map(x => `<span>${esc(x)}</span>`).join("");
    const elig = o.eligibility === "org" ? `<span class="tag org">Orgs only</span>` : o.eligibility === "both" ? `<span class="tag">Individuals &amp; orgs</span>` : o.eligibility === "ind" ? `<span class="tag">Individuals</span>` : "";
    const dim = st === "declined" || st === "notselected" || (dl && daysUntil(dl) < 0 && st === "new");
    return `<article class="row${dim ? " dim" : ""}" style="--c: var(${sc[2]})" id="row-${o.id}" data-id="${o.id}">
      <div class="when"><div class="d">${esc(when)}</div><div class="c${urgent ? " urgent" : ""}">${esc(count)}</div></div>
      <div class="what">
        <h3>${esc(o.name)}</h3>
        <div class="meta">${meta}</div>
        <div style="margin-top:6px">${elig}${o.type_label ? `<span class="tag">${esc(o.type_label)}</span>` : ""}${f.sort === "deadline" && o.market ? `<span class="tag">${esc(o.market)}</span>` : ""}<span class="tag${o.origin === "scan" ? " scan" : ""}">${o.origin === "scan" ? "Found by scan" : "From your list"}</span>${verifyTag(o)}</div>
        ${o.description ? `<div class="meta" style="margin-top:6px">${esc(String(o.description).slice(0, 280))}</div>` : ""}
        ${o.my_notes ? `<div class="note">${esc(o.my_notes)}</div>` : ""}
      </div>
      <div class="acts">
        <select data-act="status" aria-label="Status for ${esc(o.name)}">${opts}</select>
        <div class="links">${linkHTML}<button type="button" data-act="toggle" aria-expanded="false">Details</button></div>
      </div>
      <details class="edit"><summary>Details</summary>
        <div class="form">
          <label>Opens<input type="date" data-f="my_open_date" value="${esc(o.my_open_date || "")}"></label>
          <label>Deadline<input type="date" data-f="my_deadline" value="${esc(o.my_deadline || "")}"></label>
          <label class="wide">Link<input type="url" data-f="my_link" value="${esc(o.my_link || "")}" placeholder="${esc(o.source_url || "https://")}"></label>
          <label class="wide">Notes<textarea data-f="my_notes" placeholder="Requirements, contacts, ideas">${esc(o.my_notes || "")}</textarea></label>
          <label class="check"><input type="checkbox" data-f="checked_official"${o.checked_official ? " checked" : ""}> Checked on official page</label>
          ${o.origin === "scan" && o.sys_deadline && !o.my_deadline ? `<p class="hint">Deadline from the scan (${esc(o.deadline_confidence || "")}). Entering your own date overrides it.</p>` : ""}
        </div>
      </details>
    </article>`;
  }
  function render() {
    const list = visible();
    const live = opps.filter(o => o.in_scope !== false && o.eligibility !== "org");
    const soon = live.filter(o => { const d = deadlineOf(o); return d && daysUntil(d) >= 0 && daysUntil(d) <= 30 && !["declined", "submitted", "awarded", "notselected"].includes(statusOf(o)); }).length;
    const applying = opps.filter(o => statusOf(o) === "applying").length, submitted = opps.filter(o => statusOf(o) === "submitted").length;
    const fresh = opps.filter(o => o.origin === "scan" && o.in_scope !== false && o.discovered_at && (Date.now() - new Date(o.discovered_at)) < 7 * 864e5).length;
    $("#summary").innerHTML = `<b>${soon}</b> deadline${soon === 1 ? "" : "s"} in the next 30 days. You're applying to <b>${applying}</b> and have submitted <b>${submitted}</b>. The scan found <b>${fresh}</b> new in the past week.`;
    const counts = {}; opps.filter(o => o.in_scope !== false).forEach(o => { const s = statusOf(o); counts[s] = (counts[s] || 0) + 1; });
    $("#chips").innerHTML = STATUSES.map(s => `<button type="button" class="chip" style="--c: var(${s[2]})" data-status="${s[0]}" aria-pressed="${f.statuses.has(s[0])}"><i></i>${s[1]} ${counts[s[0]] || 0}</button>`).join("");
    const main = $("#list");
    const openIds = new Set([...main.querySelectorAll("details.edit[open]")].map(d => d.closest(".row").dataset.id));
    if (!list.length) main.innerHTML = `<div class="empty">Nothing matches these filters. Clear the search or status filters, or switch "Who can apply" to Everyone.</div>`;
    else if (f.sort === "city") {
      const order = [...MARKETS, ...new Set(list.map(o => o.market || "Statewide / national").filter(c => !MARKETS.includes(c)))];
      main.innerHTML = order.map(c => {
        const rows = list.filter(o => (o.market || "Statewide / national") === c).sort(byDeadline);
        return rows.length ? `<section class="city"><h2>${esc(c)} <small>${rows.length} shown</small></h2>${rows.map(rowHTML).join("")}</section>` : "";
      }).join("");
    } else main.innerHTML = `<section class="city">${list.slice().sort(byDeadline).map(rowHTML).join("")}</section>`;
    openIds.forEach(id => { const r = document.getElementById("row-" + id); if (r) r.querySelector("details").open = true; });
    renderTimeline(list);
  }
  function renderTimeline(list) {
    const start = today(), end = new Date(start); end.setDate(end.getDate() + 120);
    const pct = d => ((d - start) / (end - start)) * 100;
    let html = `<div class="tl-bar"></div>`;
    const m = new Date(start.getFullYear(), start.getMonth() + 1, 1);
    while (m < end) { if (pct(m) < 96) html += `<div class="tl-month" style="left:${pct(m)}%">${m.toLocaleDateString("en-US", { month: "short" })}</div>`; m.setMonth(m.getMonth() + 1); }
    html += `<div class="tl-today" style="left:0%"><span>Today</span></div>`;
    const dated = list.map(o => ({ o, d: deadlineOf(o) })).filter(x => x.d && x.d >= start && x.d <= end).sort((a, b) => a.d - b.d);
    const used = {};
    dated.forEach(({ o, d }) => {
      const k = Math.round(pct(d) / 2.2); used[k] = (used[k] || 0) + 1;
      const cls = used[k] === 2 ? " stack" : used[k] >= 3 ? " stack2" : "";
      html += `<button type="button" class="tl-dot${cls}" style="left:${pct(d)}%; --c: var(${STATUS[statusOf(o)][2]})" data-jump="${o.id}" title="${esc(o.name)}, ${esc(fmt(d))}" aria-label="${esc(o.name)}, due ${esc(fmt(d))}"></button>`;
    });
    $("#tl-track").innerHTML = html; $("#tl-empty").hidden = dated.length > 0; $("#tl-range").textContent = `${fmt(start)} to ${fmt(end)}`;
  }

  $("#city").innerHTML += MARKETS.map(c => `<option>${esc(c)}</option>`).join("");
  [["#q", "input", "q"], ["#city", "change", "city"], ["#elig", "change", "elig"], ["#origin", "change", "origin"], ["#sort", "change", "sort"]]
    .forEach(([sel, ev, key]) => $(sel).addEventListener(ev, e => { f[key] = e.target.value; render(); }));
  $("#showdone").addEventListener("change", e => { f.showdone = e.target.checked; render(); });
  $("#chips").addEventListener("click", e => { const b = e.target.closest("[data-status]"); if (!b) return; const s = b.dataset.status; f.statuses.has(s) ? f.statuses.delete(s) : f.statuses.add(s); render(); });
  $("#tl-track").addEventListener("click", e => { const b = e.target.closest("[data-jump]"); if (!b) return; const r = document.getElementById("row-" + b.dataset.jump); if (r) { r.scrollIntoView({ block: "center" }); r.querySelector("select").focus({ preventScroll: true }); } });
  $("#list").addEventListener("change", e => {
    const row = e.target.closest(".row"); if (!row) return; const id = Number(row.dataset.id);
    if (e.target.dataset.act === "status") return updateOpp(id, { my_status: e.target.value });
    const k = e.target.dataset.f; if (!k || k === "my_notes") return;
    if (k === "checked_official") return updateOpp(id, { checked_official: e.target.checked });
    if (k === "my_link") { const v = e.target.value.trim(); if (v && !/^https?:\/\//i.test(v)) { e.target.setCustomValidity("Start the link with https://"); e.target.reportValidity(); return; } e.target.setCustomValidity(""); return updateOpp(id, { my_link: v || null }); }
    return updateOpp(id, { [k]: e.target.value || null });
  });
  const noteTimers = {};
  $("#list").addEventListener("input", e => {
    if (e.target.dataset.f !== "my_notes") return;
    const id = Number(e.target.closest(".row").dataset.id); const val = e.target.value;
    clearTimeout(noteTimers[id]);
    noteTimers[id] = setTimeout(async () => {
      const o = opps.find(x => x.id === id); o.my_notes = val;
      const { error } = await sb.from("opportunities").update({ my_notes: val || null, my_updated_at: new Date().toISOString() }).eq("id", id);
      setSync(error ? "Couldn't save your note. Check your connection." : "Note saved.");
    }, 900);
  });
  $("#list").addEventListener("click", e => {
    const t = e.target.closest('[data-act="toggle"]'); if (!t) return;
    const d = t.closest(".row").querySelector("details"); d.open = !d.open; t.setAttribute("aria-expanded", String(d.open));
  });

  // ---------- CSV export / import ----------
  function csvCell(v) { return `"${String(v ?? "").replace(/"/g, '""')}"`; }
  $("#exportBtn").addEventListener("click", () => {
    const cols = ["market", "name", "amount", "supports", "type", "open", "deadline", "status", "link", "notes", "checked", "source"];
    const lines = [cols.join(",")].concat(opps.filter(o => o.in_scope !== false).map(o => [o.market, o.name, amountText(o), o.supports_text || o.issuer, o.type_label,
      o.my_open_date || "", deadlineOf(o) ? deadlineOf(o).toISOString().slice(0, 10) : "", STATUS[statusOf(o)][1], linkOf(o), o.my_notes, o.checked_official ? "yes" : "", o.origin === "scan" ? "scan" : "your list"].map(csvCell).join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "charlie-opportunities.csv"; a.click(); URL.revokeObjectURL(a.href);
  });
  function parseCSV(text) {
    const rows = []; let row = [], cell = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) { if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') q = false; else cell += c; }
      else if (c === '"') q = true; else if (c === ",") { row.push(cell); cell = ""; }
      else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
      else cell += c;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows.filter(r => r.some(x => x !== ""));
  }
  const norm = s => String(s || "").toLowerCase().replace(/[–—]/g, "-").replace(/\s+/g, " ").trim();
  $("#importBtn").addEventListener("click", () => $("#importFile").click());
  $("#importFile").addEventListener("change", async e => {
    const file = e.target.files[0]; if (!file) return; const msg = $("#importMsg");
    const rows = parseCSV(await file.text()); e.target.value = "";
    if (rows.length < 2) { msg.textContent = "That file has no rows to import."; return; }
    const head = rows[0].map(norm), idx = k => head.indexOf(k);
    const iCity = idx("city") >= 0 ? idx("city") : idx("market"), iName = idx("name");
    if (iName < 0) { msg.textContent = "That doesn't look like a Charlie export: there's no name column."; return; }
    let updated = 0, unmatched = 0;
    msg.textContent = "Importing…";
    for (const r of rows.slice(1)) {
      const o = opps.find(x => norm(x.name) === norm(r[iName]) && (iCity < 0 || norm(x.market) === norm(r[iCity])));
      if (!o) { unmatched++; continue; }
      const patch = {};
      const st = LABEL_TO_STATUS[norm(r[idx("status")])]; if (st && st !== o.my_status) patch.my_status = st;
      const notes = idx("notes") >= 0 ? r[idx("notes")] : ""; if (notes && notes !== o.my_notes) patch.my_notes = notes;
      const link = idx("link") >= 0 ? r[idx("link")].trim() : ""; if (link && link !== o.source_url && link !== o.my_link && /^https?:\/\//.test(link)) patch.my_link = link;
      for (const [col, key] of [["open", "my_open_date"], ["deadline", "my_deadline"]]) { const v = idx(col) >= 0 ? r[idx(col)] : ""; if (/^\d{4}-\d{2}-\d{2}$/.test(v) && v !== o[key]) patch[key] = v; }
      const chk = idx("checked") >= 0 ? norm(r[idx("checked")]) : ""; if (["true", "yes"].includes(chk) && !o.checked_official) patch.checked_official = true;
      if (!Object.keys(patch).length) continue;
      const { error } = await sb.from("opportunities").update({ ...patch, my_updated_at: new Date().toISOString() }).eq("id", o.id);
      if (!error) { Object.assign(o, patch); updated++; }
    }
    render();
    msg.textContent = `Imported changes for ${updated} opportunit${updated === 1 ? "y" : "ies"}.` + (unmatched ? ` ${unmatched} row${unmatched === 1 ? " didn't match anything and was" : "s didn't match anything and were"} skipped.` : "");
  });

  // ---------- sources ----------
  $("#sstate").innerHTML += STATES.map(s => `<option>${s}</option>`).join("");
  $("#s-state").innerHTML = `<option value="">National / regional</option>` + STATES.map(s => `<option>${s}</option>`).join("");
  const sview = s => s.fetch_method === "MANUAL" ? "manual" : !s.active && String(s.discovered_via || "").startsWith("link_from_source") && !s.last_fetched_at ? "suggested" : s.active ? "active" : "off";
  function renderSources() {
    const q = sf.q.trim().toLowerCase();
    const rows = sources.filter(s => {
      if (sf.view && sview(s) !== sf.view) return false;
      if (sf.state === "none" && s.state_code) return false;
      if (sf.state && sf.state !== "none" && s.state_code !== sf.state) return false;
      if (sf.fail && !s.last_error) return false;
      if (q && !`${s.name} ${s.url} ${s.state_code || ""}`.toLowerCase().includes(q)) return false;
      return true;
    }).sort((a, b) => String(a.state_code || "").localeCompare(String(b.state_code || "")) || a.name.localeCompare(b.name));
    const color = s => s.last_error ? "var(--s-notselected)" : sview(s) === "active" ? "var(--s-applying)" : "var(--s-new)";
    $("#slist").innerHTML = rows.length ? rows.map(s => {
      const v = sview(s);
      return `<article class="srow" style="--c:${color(s)}" data-sid="${s.id}">
        <div>
          <h3>${esc(s.name)}</h3>
          <div class="meta"><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></div>
          <div class="meta">${esc(s.state_code || "National / regional")}, checked every ${esc(s.check_days || 7)} days, ${s.last_fetched_at ? "last checked " + esc(new Date(s.last_fetched_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })) : "not checked yet"}</div>
          ${s.last_error ? `<div class="meta err">Last error: ${esc(String(s.last_error).slice(0, 160))}</div>` : ""}
          ${s.tos_notes ? `<div class="meta">${esc(s.tos_notes)}</div>` : ""}
        </div>
        <div class="ctrl">
          ${v === "suggested" ? `<button class="btn" type="button" data-s="approve">Approve</button><button class="linkbtn" type="button" data-s="dismiss">Dismiss</button>`
            : v === "manual" ? `<button class="linkbtn" type="button" data-s="unmanual">Scan it daily again</button>`
            : `<label class="toggle"><input type="checkbox" data-s="active"${s.active ? " checked" : ""}> Scan daily</label><button class="linkbtn" type="button" data-s="manual">Check by email instead</button>`}
          <button class="linkbtn" type="button" data-s="edit">Edit</button>
        </div>
        <details><summary>Edit</summary><div class="form">
          <label class="wide">Name<input data-sf="name" value="${esc(s.name)}"></label>
          <label class="wide">Web address<input data-sf="url" type="url" value="${esc(s.url)}"></label>
          <label>Check every (days)<input data-sf="check_days" type="number" min="1" max="60" value="${esc(s.check_days || 7)}"></label>
        </div></details>
      </article>`;
    }).join("") : `<div class="empty">No sources match these filters.</div>`;
  }
  [["#sq", "input", "q"], ["#sview", "change", "view"], ["#sstate", "change", "state"]].forEach(([sel, ev, key]) => $(sel).addEventListener(ev, e => { sf[key] = e.target.value; renderSources(); }));
  $("#sfail").addEventListener("change", e => { sf.fail = e.target.checked; renderSources(); });
  $("#slist").addEventListener("click", e => {
    const b = e.target.closest("[data-s]"); if (!b || b.dataset.s === "active") return;
    const id = Number(b.closest(".srow").dataset.sid), act = b.dataset.s;
    if (act === "approve") return updateSource(id, { active: true, discovered_via: "approved_suggestion" });
    if (act === "dismiss") return updateSource(id, { discovered_via: "dismissed_suggestion" });
    if (act === "manual") return updateSource(id, { fetch_method: "MANUAL" });
    if (act === "unmanual") return updateSource(id, { fetch_method: "HTML", active: true, consecutive_failures: 0, last_error: null, last_fetched_at: null });
    if (act === "edit") { const d = b.closest(".srow").querySelector("details"); d.open = !d.open; }
  });
  $("#slist").addEventListener("change", e => {
    const row = e.target.closest(".srow"); if (!row) return; const id = Number(row.dataset.sid);
    if (e.target.dataset.s === "active") return updateSource(id, { active: e.target.checked, ...(e.target.checked ? { consecutive_failures: 0 } : {}) });
    const k = e.target.dataset.sf; if (!k) return;
    if (k === "url") { const v = e.target.value.trim(); if (!/^https?:\/\//i.test(v)) { e.target.setCustomValidity("Start the address with https://"); e.target.reportValidity(); return; } e.target.setCustomValidity(""); return updateSource(id, { url: v, last_fetched_at: null, last_error: null, consecutive_failures: 0 }); }
    if (k === "name") return updateSource(id, { name: e.target.value.trim() });
    if (k === "check_days") { const n = Math.max(1, Math.min(60, Number(e.target.value) || 7)); sources.find(x => x.id === id).check_days = n; return sb.from("sources").update({ check_every: `${n} days` }).eq("id", id).then(({ error }) => setSync(error ? "Couldn't save that change." : "Saved.")); }
  });
  const sdlg = $("#srcDlg");
  $("#addSourceBtn").addEventListener("click", () => { sdlg.showModal(); $("#s-name").focus(); });
  $("#srcCancel").addEventListener("click", () => sdlg.close());
  $("#srcSave").addEventListener("click", async () => {
    const name = $("#s-name").value.trim(), url = $("#s-url").value.trim();
    if (!name) { $("#s-name").setCustomValidity("Give the source a name"); $("#s-name").reportValidity(); return; }
    $("#s-name").setCustomValidity("");
    if (!/^https?:\/\//i.test(url)) { $("#s-url").setCustomValidity("Start the address with https://"); $("#s-url").reportValidity(); return; }
    $("#s-url").setCustomValidity("");
    const cat = $("#s-cat").value, st = $("#s-state").value, days = Math.max(1, Math.min(60, Number($("#s-days").value) || 7));
    const row = { name, url, category: cat, tier: cat === "AGGREGATOR" ? "P3_SECONDARY_DB" : "P1_OFFICIAL", fetch_method: "HTML",
                  check_every: `${days} days`, place_id: st ? (statePlaces[st] || null) : null, discovered_via: "added_by_you", active: true };
    const { data, error } = await sb.from("sources").insert(row).select("id");
    if (error) { setSync(/duplicate|unique/i.test(error.message || "") ? "That web address is already a source." : "Couldn't add the source. Try again."); return; }
    sources.push({ ...row, id: data && data[0] ? data[0].id : Date.now(), state_code: st || null, check_days: days });
    sdlg.close(); sdlg.querySelectorAll("input").forEach(i => { if (i.type !== "number") i.value = ""; });
    renderSources(); setSync("Source added. The next daily scan will check it.");
  });

  // ---------- tabs ----------
  function showTab(name) { for (const t of ["opps", "sources"]) { $("#tab-" + t).hidden = t !== name; $("#t-" + t).setAttribute("aria-selected", String(t === name)); } }
  $("#t-opps").addEventListener("click", () => showTab("opps"));
  $("#t-sources").addEventListener("click", () => showTab("sources"));
})();
