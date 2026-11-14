"""Telefon uchun chat sahifasi (APK ichida ko'rsatiladi, brauzerda ham ochiladi)."""

INDEX_HTML = r"""<!doctype html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>aget_ai</title>
<style>
  :root { --bg:#f4f6f9; --card:#fff; --text:#1d2330; --muted:#6b7385; --accent:#2563eb;
          --user:#2563eb; --userText:#fff; --border:#e2e6ee; --warn:#fff7e6; --warnBorder:#f0b429; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1218; --card:#1a1f29; --text:#e7eaf0; --muted:#8b93a7; --accent:#4f8cff;
            --user:#3b6fe0; --userText:#fff; --border:#2a3140; --warn:#2a2416; --warnBorder:#b8860b; }
  }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--text);
              font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  body { display:flex; flex-direction:column; }
  header { display:flex; align-items:center; gap:8px; padding:12px 16px; background:var(--card);
           border-bottom:1px solid var(--border); }
  header h1 { font-size:17px; margin:0; flex:1; }
  #dot { width:10px; height:10px; border-radius:50%; background:#aaa; }
  #dot.on { background:#22c55e; } #dot.off { background:#ef4444; }
  header button { background:none; border:1px solid var(--border); color:var(--text);
                  border-radius:8px; padding:6px 10px; font-size:14px; }
  #log { flex:1; overflow-y:auto; padding:12px 16px; display:flex; flex-direction:column; gap:10px; }
  .msg { max-width:88%; padding:10px 12px; border-radius:14px; white-space:pre-wrap; word-wrap:break-word; }
  .user { align-self:flex-end; background:var(--user); color:var(--userText); border-bottom-right-radius:4px; }
  .agent { align-self:flex-start; background:var(--card); border:1px solid var(--border); border-bottom-left-radius:4px; }
  .event { align-self:flex-start; color:var(--muted); font-size:13px; padding:0 4px; }
  .prompt { align-self:stretch; background:var(--warn); border:1px solid var(--warnBorder); }
  .prompt .row { display:flex; gap:8px; margin-top:10px; }
  .prompt button, #send { border:0; border-radius:10px; padding:10px 14px; font-size:15px;
                          background:var(--accent); color:#fff; }
  .prompt button.no { background:#6b7385; }
  .prompt input { flex:1; min-width:0; padding:10px; border-radius:10px; border:1px solid var(--border);
                  background:var(--card); color:var(--text); font-size:15px; }
  .done { opacity:.6; }
  footer { display:flex; gap:8px; padding:10px 12px calc(10px + env(safe-area-inset-bottom));
           background:var(--card); border-top:1px solid var(--border); }
  #text { flex:1; min-width:0; resize:none; max-height:120px; padding:10px 12px; border-radius:12px;
          border:1px solid var(--border); background:var(--bg); color:var(--text); font:inherit; }
  #send:disabled { opacity:.5; }
  #status { text-align:center; color:var(--muted); font-size:13px; padding:4px; }
  #login { padding:24px 16px; display:none; flex-direction:column; gap:10px; }
  #login input { padding:12px; border-radius:10px; border:1px solid var(--border); background:var(--card);
                 color:var(--text); font-size:16px; }
</style>
</head>
<body>
<header><span id="dot"></span><h1>aget_ai</h1><button id="newBtn">Yangi suhbat</button></header>
<div id="login">
  <b>Kompyuterdagi "Telefon" oynasidagi kodni kiriting:</b>
  <input id="code" placeholder="Masalan: 9F3A1C0B" autocapitalize="characters">
  <button id="loginBtn" style="padding:12px;border:0;border-radius:10px;background:var(--accent);color:#fff;font-size:16px">Ulanish</button>
</div>
<div id="log"></div>
<div id="status"></div>
<footer><textarea id="text" rows="1" placeholder="Topshiriq yozing..."></textarea><button id="send">➤</button></footer>
<script>
const qs = new URLSearchParams(location.search);
let token = qs.get("token") || "";
try { if (token) localStorage.setItem("token", token); else token = localStorage.getItem("token") || ""; } catch (e) {}
let after = 0, busy = false, online = false;
const $ = id => document.getElementById(id);
const log = $("log");

function api(path, body) {
  return fetch(path, {
    method: body ? "POST" : "GET",
    headers: {"X-Token": token, "Content-Type": "application/json"},
    body: body ? JSON.stringify(body) : undefined,
  }).then(async r => {
    if (r.status === 401) { showLogin(); throw new Error("401"); }
    return r.json();
  });
}

function add(cls, text) {
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

function addPrompt(ev) {
  const d = add("prompt", ev.type === "approve" ? "⚠️ Agent ruxsat so'rayapti:\n" + ev.text : "❓ " + ev.text);
  d.id = "p" + ev.id;
  const row = document.createElement("div");
  row.className = "row";
  if (ev.type === "approve") {
    const yes = document.createElement("button"); yes.textContent = "Ha, ruxsat";
    const no = document.createElement("button"); no.textContent = "Yo'q"; no.className = "no";
    yes.onclick = () => answer(ev.id, true); no.onclick = () => answer(ev.id, false);
    row.append(yes, no);
  } else {
    const inp = document.createElement("input"); inp.placeholder = "Javobingiz";
    const ok = document.createElement("button"); ok.textContent = "Yuborish";
    ok.onclick = () => answer(ev.id, inp.value);
    inp.onkeydown = e => { if (e.key === "Enter") ok.click(); };
    row.append(inp, ok);
  }
  d.appendChild(row);
}

function answer(id, value) {
  api("/api/answer", {id, value}).catch(() => {});
  const d = $("p" + id);
  if (d) { d.classList.add("done"); const r = d.querySelector(".row"); if (r) r.remove(); }
}

function render(ev) {
  if (ev.type === "user") add("user", ev.text);
  else if (ev.type === "agent") add("agent", ev.text);
  else if (ev.type === "event") add("event", ev.text);
  else if (ev.type === "approve" || ev.type === "ask") addPrompt(ev);
  else if (ev.type === "answered") {
    const d = $("p" + ev.ref);
    if (d) { d.classList.add("done"); const r = d.querySelector(".row"); if (r) r.remove(); }
  }
}

function setOnline(v) {
  online = v;
  $("dot").className = v ? "on" : "off";
  $("status").textContent = v ? (busy ? "⏳ Agent ishlayapti..." : "")
                              : "Kompyuter bilan aloqa yo'q. Kompyuter yoqilgan va aget_ai ochiqligini tekshiring.";
  $("send").disabled = !v || busy;
}

async function poll() {
  if (!token) { showLogin(); return; }
  try {
    const s = await api("/api/poll?after=" + after);
    for (const ev of s.events) { render(ev); after = Math.max(after, ev.id); }
    busy = s.busy;
    setOnline(true);
  } catch (e) {
    if (e.message !== "401") setOnline(false);
  }
  setTimeout(poll, busy ? 800 : 1500);
}

function send() {
  const t = $("text").value.trim();
  if (!t || busy || !online) return;
  $("text").value = "";
  busy = true; setOnline(true);
  api("/api/send", {text: t}).then(r => { if (r.error) add("event", "⚠️ " + r.error); })
    .catch(() => add("event", "⚠️ Yuborib bo'lmadi"));
}

function showLogin() {
  $("login").style.display = "flex";
  log.style.display = "none";
}

$("loginBtn").onclick = () => {
  token = $("code").value.trim().toUpperCase();
  try { localStorage.setItem("token", token); } catch (e) {}
  $("login").style.display = "none";
  log.style.display = "flex";
  poll();
};
$("send").onclick = send;
$("text").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
$("newBtn").onclick = () => {
  if (busy) return;
  api("/api/new", {}).then(() => { log.innerHTML = ""; }).catch(() => {});
};
poll();
</script>
</body>
</html>
"""
