// Variables
const API_URL = "https://status.proyectos.cristiancode.dev/api/snapshot";
const BG_DARK = new Color("#0a0a0f");
const BG_SURFACE = new Color("#14141e");
const BG_SURFACE2 = new Color("#1c1c2a");
const ACCENT = new Color("#ffac02");
const ACCENT_DIM = new Color("#b87a00");
const GREEN = new Color("#22c55e");
const RED = new Color("#ef4444");
const BLUE = new Color("#3b82f6");
const YELLOW = new Color("#eab308");
const TEXT = new Color("#e2e2ea");
const TEXT_DIM = new Color("#8888a0");
const TEXT_MUTED = new Color("#55556a");
const BORDER = new Color("#ffffff", 0.06);

// ── Fetch data ──
async function fetchData() {
  const req = new Request(API_URL);
  req.timeoutInterval = 8;
  const data = await req.loadJSON();
  return data;
}

// ── Helpers ──
function fmtUptime(secs) {
  if (!secs) return "—";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h > 48) return `${Math.floor(h/24)}d ${h%24}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function statusDot(w, color) {
  const dot = w.addText("●");
  dot.font = Font.boldSystemFont(10);
  dot.textColor = color;
  return dot;
}

function addRow(w, label, value, valueColor) {
  const row = w.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  row.addSpacer(4);
  const lbl = row.addText(label);
  lbl.font = Font.mediumSystemFont(10);
  lbl.textColor = TEXT_DIM;
  row.addSpacer(null);
  if (value !== undefined && value !== null) {
    const val = row.addText(String(value));
    val.font = Font.boldSystemFont(12);
    val.textColor = valueColor || TEXT;
  }
  row.addSpacer(4);
  return row;
}

function addDivider(w) {
  const d = w.addStack();
  d.layoutHorizontally();
  d.addSpacer(4);
  const line = d.addText("─".repeat(30));
  line.font = Font.regularSystemFont(6);
  line.textColor = BORDER;
  d.addSpacer(4);
}

function bar(w, label, pct, color) {
  const row = w.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  row.addSpacer(4);
  const lbl = row.addText(label);
  lbl.font = Font.mediumSystemFont(9);
  lbl.textColor = TEXT_DIM;
  row.addSpacer(4);
  const barBg = row.addStack();
  barBg.layoutHorizontally();
  barBg.size = new Size(0, 6);
  barBg.cornerRadius = 3;
  barBg.backgroundColor = BG_SURFACE2;
  barBg.addSpacer(null);
  const barFill = barBg.addStack();
  barFill.size = new Size(0, 6);
  barFill.cornerRadius = 3;
  barFill.backgroundColor = color;
  const pctStr = Math.round(pct) + "%";
  barFill.addText(" ".repeat(Math.max(1, Math.floor(pct / 10))));
  barBg.addSpacer(1);
  const pctLbl = row.addText(pctStr);
  pctLbl.font = Font.boldSystemFont(9);
  pctLbl.textColor = TEXT;
  row.addSpacer(4);
  return row;
}

// ── Build small widget ──
function buildSmall(data) {
  const w = new ListWidget();
  w.backgroundColor = BG_DARK;

  // Top bar
  const top = w.addStack();
  top.layoutHorizontally();
  top.centerAlignContent();
  top.addSpacer(4);
  const title = top.addText("⚡ Status");
  title.font = Font.boldSystemFont(11);
  title.textColor = ACCENT;
  top.addSpacer(null);
  const gw = data.gateway || {};
  const gwState = gw.state === "running" ? GREEN : RED;
  statusDot(top, gwState);
  top.addSpacer(4);

  w.addSpacer(6);

  // Sessions
  const sessions = data.sessions || [];
  addRow(w, "Sessions", sessions.length, ACCENT);

  w.addSpacer(2);

  // Agents
  const roots = (data.agent_tree || {}).roots || [];
  addRow(w, "Agents", roots.length, BLUE);

  w.addSpacer(2);

  // Socats
  const socats = data.socats || {};
  const allUp = socats.all_up !== false;
  addRow(w, "Socats", allUp ? "✓ OK" : "⚠ DOWN", allUp ? GREEN : RED);

  w.addSpacer(2);

  // System load
  const sys = data.system || {};
  addRow(w, "Load", sys.load_1m != null ? String(sys.load_1m) : "—", TEXT);

  w.addSpacer(null);

  // Time
  const dt = data.datetime ? new Date(data.datetime) : new Date();
  const ts = w.addText(formatTime(dt));
  ts.font = Font.regularSystemFont(8);
  ts.textColor = TEXT_MUTED;
  ts.centerAlignText();

  return w;
}

// ── Build medium widget ──
function buildMedium(data) {
  const w = new ListWidget();
  w.backgroundColor = BG_DARK;

  // Header
  const top = w.addStack();
  top.layoutHorizontally();
  top.centerAlignContent();
  top.addSpacer(8);
  const title = top.addText("⚡ Hermes Status");
  title.font = Font.boldSystemFont(14);
  title.textColor = ACCENT;
  top.addSpacer(null);
  const gw = data.gateway || {};
  const gwState = gw.state === "running" ? GREEN : RED;
  const dot = statusDot(top, gwState);
  const gwLabel = top.addText(" " + (gw.state || "?"));
  gwLabel.font = Font.mediumSystemFont(10);
  gwLabel.textColor = TEXT_DIM;
  top.addSpacer(8);

  w.addSpacer(4);
  addDivider(w);
  w.addSpacer(4);

  // Two columns
  const cols = w.addStack();
  cols.layoutHorizontally();

  // Left column
  const left = cols.addStack();
  left.layoutVertically();
  const sessions = data.sessions || [];
  addRow(left, "Sessions", sessions.length, ACCENT);
  left.addSpacer(2);
  const roots = (data.agent_tree || {}).roots || [];
  addRow(left, "Agents", roots.length, BLUE);
  left.addSpacer(2);
  const procs = data.processes || [];
  addRow(left, "Processes", procs.length, TEXT);

  cols.addSpacer(8);

  // Right column
  const right = cols.addStack();
  right.layoutVertically();
  const socats = data.socats || {};
  const allUp = socats.all_up !== false;
  addRow(right, "Socats", allUp ? "✓ All OK" : "⚠ DOWN", allUp ? GREEN : RED);
  right.addSpacer(2);
  const sys = data.system || {};
  addRow(right, "Load", sys.load_1m != null ? String(sys.load_1m) : "—", TEXT);
  right.addSpacer(2);
  const workers = data.workers || [];
  addRow(right, "Workers", workers.length, TEXT);

  w.addSpacer(4);
  addDivider(w);
  w.addSpacer(4);

  // Memory bar
  const mem = sys.memory || {};
  if (mem.total_kb && mem.available_kb) {
    const usedPct = (1 - mem.available_kb / mem.total_kb) * 100;
    bar(w, "MEM", usedPct, usedPct > 80 ? RED : GREEN);
  }

  w.addSpacer(4);

  // Platforms
  const platforms = (data.gateway || {}).platforms || {};
  if (Object.keys(platforms).length > 0) {
    const platRow = w.addStack();
    platRow.layoutHorizontally();
    platRow.addSpacer(8);
    Object.entries(platforms).forEach(([name, p]) => {
      const ok = p.state === "connected";
      const chip = platRow.addStack();
      chip.layoutHorizontally();
      chip.centerAlignContent();
      chip.backgroundColor = BG_SURFACE2;
      chip.cornerRadius = 4;
      chip.addSpacer(4);
      const d = statusDot(chip, ok ? GREEN : RED);
      d.font = Font.boldSystemFont(7);
      const lbl = chip.addText(" " + name);
      lbl.font = Font.mediumSystemFont(8);
      lbl.textColor = TEXT_DIM;
      chip.addSpacer(4);
      platRow.addSpacer(4);
    });
    platRow.addSpacer(8);
  }

  w.addSpacer(null);

  const dt = data.datetime ? new Date(data.datetime) : new Date();
  const ts = w.addText(formatTime(dt));
  ts.font = Font.regularSystemFont(8);
  ts.textColor = TEXT_MUTED;
  ts.centerAlignText();

  return w;
}

// ── Build large widget ──
function buildLarge(data) {
  const w = new ListWidget();
  w.backgroundColor = BG_DARK;
  w.setPadding(12, 12, 8, 12);

  // Header
  const top = w.addStack();
  top.layoutHorizontally();
  top.centerAlignContent();
  const title = top.addText("⚡ Hermes Real-Time Dashboard");
  title.font = Font.boldSystemFont(15);
  title.textColor = ACCENT;
  top.addSpacer(null);
  const gw = data.gateway || {};
  statusDot(top, gw.state === "running" ? GREEN : RED);
  top.addSpacer(4);

  w.addSpacer(6);
  addDivider(w);
  w.addSpacer(6);

  // ── KWIC row ──
  const kwic = w.addStack();
  kwic.layoutHorizontally();
  kwic.addSpacer(4);

  const sessions = data.sessions || [];
  const roots = (data.agent_tree || {}).roots || [];
  const procs = data.processes || [];
  const workers = data.workers || [];
  const socats = data.socats || {};
  const allUp = socats.all_up !== false;
  const sys = data.system || {};
  const cronFiles = data.cron_files || {};

  const metrics = [
    ["Sessions", sessions.length, ACCENT],
    ["Agents", roots.length, BLUE],
    ["Procs", procs.length, TEXT],
    ["Workers", workers.length, TEXT_DIM],
    ["Socats", allUp ? "OK" : "DOWN", allUp ? GREEN : RED],
    ["Cron", Object.keys(cronFiles).length, YELLOW],
  ];

  metrics.forEach(([lbl, val, color], i) => {
    const m = kwic.addStack();
    m.layoutVertically();
    m.centerAlignContent();
    m.backgroundColor = BG_SURFACE;
    m.cornerRadius = 6;
    m.setPadding(6, 8, 6, 8);
    const v = m.addText(String(val));
    v.font = Font.boldSystemFont(16);
    v.textColor = color;
    v.centerAlignText();
    const l = m.addText(lbl);
    l.font = Font.mediumSystemFont(8);
    l.textColor = TEXT_MUTED;
    l.centerAlignText();
    if (i < metrics.length - 1) kwic.addSpacer(4);
  });
  kwic.addSpacer(4);

  w.addSpacer(8);

  // ── System details ──
  const sysRow = w.addStack();
  sysRow.layoutHorizontally();
  sysRow.addSpacer(4);
  if (sys.load_1m != null) addRow(sysRow, "Load", `${sys.load_1m} / ${sys.load_5m || "?"} / ${sys.load_15m || "?"}`, TEXT);
  sysRow.addSpacer(null);
  const mem = sys.memory || {};
  if (mem.total_kb && mem.available_kb) {
    const usedPct = Math.round((1 - mem.available_kb / mem.total_kb) * 100);
    addRow(sysRow, "MEM", usedPct + "%", usedPct > 80 ? RED : GREEN);
  }
  sysRow.addSpacer(4);

  w.addSpacer(2);
  const uptimeRow = w.addStack();
  uptimeRow.layoutHorizontally();
  uptimeRow.addSpacer(4);
  addRow(uptimeRow, "Uptime", fmtUptime(sys.uptime_seconds), TEXT);
  uptimeRow.addSpacer(null);
  addRow(uptimeRow, "Procs", String(sys.process_count || "?"), TEXT);
  uptimeRow.addSpacer(4);

  // Memory bar
  w.addSpacer(2);
  if (mem.total_kb && mem.available_kb) {
    const usedPct = (1 - mem.available_kb / mem.total_kb) * 100;
    bar(w, "MEM", usedPct, usedPct > 80 ? RED : GREEN);
  }

  w.addSpacer(6);
  addDivider(w);
  w.addSpacer(6);

  // ── Latest sessions ──
  if (sessions.length > 0) {
    const sessTitle = w.addText("Recent Sessions");
    sessTitle.font = Font.boldSystemFont(10);
    sessTitle.textColor = TEXT_MUTED;
    sessTitle.addSpacer(2);

    sessions.slice(0, 4).forEach((s, i) => {
      const row = w.addStack();
      row.layoutHorizontally();
      row.addSpacer(4);
      const dot = row.addText("●");
      dot.font = Font.boldSystemFont(6);
      dot.textColor = GREEN;
      row.addSpacer(4);
      const title = row.addText(String(s.title || s.id?.slice(0, 20) || "Session").slice(0, 28));
      title.font = Font.mediumSystemFont(9);
      title.textColor = TEXT;
      title.lineLimit = 1;
      row.addSpacer(null);
      const src = row.addText(String(s.source || "?"));
      src.font = Font.regularSystemFont(8);
      src.textColor = TEXT_DIM;
      row.addSpacer(4);
      if (i < sessions.length - 1 && i < 3) w.addSpacer(1);
    });
  }

  // ── Platforms ──
  const platforms = (data.gateway || {}).platforms || {};
  if (Object.keys(platforms).length > 0) {
    w.addSpacer(4);
    const platTitle = w.addText("Platforms");
    platTitle.font = Font.boldSystemFont(10);
    platTitle.textColor = TEXT_MUTED;

    const platRow = w.addStack();
    platRow.layoutHorizontally();
    platRow.addSpacer(4);
    Object.entries(platforms).forEach(([name, p]) => {
      const ok = p.state === "connected";
      const chip = platRow.addStack();
      chip.layoutHorizontally();
      chip.centerAlignContent();
      chip.backgroundColor = BG_SURFACE2;
      chip.cornerRadius = 4;
      chip.setPadding(3, 6, 3, 6);
      statusDot(chip, ok ? GREEN : RED);
      const lbl = chip.addText(" " + name);
      lbl.font = Font.mediumSystemFont(9);
      lbl.textColor = ok ? TEXT : RED;
      platRow.addSpacer(4);
    });
    platRow.addSpacer(4);
  }

  w.addSpacer(null);

  const dt = data.datetime ? new Date(data.datetime) : new Date();
  const ts = w.addText(formatTime(dt));
  ts.font = Font.regularSystemFont(8);
  ts.textColor = TEXT_MUTED;
  ts.centerAlignText();

  return w;
}

function formatTime(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// ── Main ──
const widget = new ListWidget();
widget.backgroundColor = BG_DARK;

// Show loading
const loadTxt = widget.addText("Loading...");
loadTxt.font = Font.mediumSystemFont(12);
loadTxt.textColor = TEXT_DIM;
loadTxt.centerAlignText();

try {
  const data = await fetchData();
  const size = config.widgetFamily || "medium";
  let result;
  if (size === "small") {
    result = buildSmall(data);
  } else if (size === "medium") {
    result = buildMedium(data);
  } else {
    result = buildLarge(data);
  }

  // Copy result to widget
  widget.setPadding(0, 0, 0, 0);
  const bgUrl = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPj/HwADBwIAMCbHYQAAAABJRU5ErkJggg==";
  widget.backgroundImage = await (new Request(bgUrl)).loadImage();
  widget.addStack().addWidget(result);

} catch (e) {
  widget.setPadding(12, 12, 12, 12);
  const errTitle = widget.addText("⚠️ Error");
  errTitle.font = Font.boldSystemFont(13);
  errTitle.textColor = RED;
  errTitle.centerAlignText();
  widget.addSpacer(4);
  const errMsg = widget.addText(e.message || "Connection failed");
  errMsg.font = Font.mediumSystemFont(10);
  errMsg.textColor = TEXT_DIM;
  errMsg.centerAlignText();
  widget.addSpacer(4);
  const retry = widget.addText("Tap to retry");
  retry.font = Font.regularSystemFont(9);
  retry.textColor = TEXT_MUTED;
  retry.centerAlignText();

  if (config.runsInWidget) {
    const refresh = widget.addText("Refreshes every 5 min");
    refresh.font = Font.regularSystemFont(8);
    refresh.textColor = TEXT_MUTED;
    refresh.centerAlignText();
  }
}

// Refresh interval
if (config.runsInWidget) {
  widget.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);
}

// Set widget
Script.setWidget(widget);
Script.complete();
