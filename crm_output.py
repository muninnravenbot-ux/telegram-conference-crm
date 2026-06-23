"""Classification + output (CSV and a self-contained interactive HTML CRM).

The HTML is a complete little CRM app: a follow-up pipeline (dropdown per
contact), free-text notes, per-contact reminders with a "due" view and
calendar (.ics) export, and CSV export/import so your edits never get trapped
in one browser. Everything is stored in the browser's localStorage — no
backend, no network, the data never leaves the machine.
"""
from __future__ import annotations

import csv
import json
from datetime import date

STATUS_ORDER = {"NEW": 0, "REACTIVATED": 1, "ONGOING": 2}

# The on-disk CSV the tool writes. The last three columns are where YOUR edits
# (pipeline stage, notes, reminder) land — empty on first generation, filled by
# the HTML app's "Download CRM" export. Keeping them here means a tool-written
# CSV and an app-exported CSV share one schema, so import round-trips cleanly.
CSV_FIELDS = ["Name", "Username", "Telegram ID", "Type", "Status",
              "Msgs in window", "Their replies", "First contact",
              "Last contact before", "Dormant days", "Talked about (in window)",
              "Followed up?", "Telegram link", "Notes",
              "Stage", "My notes", "Reminder"]


def classify(first_ever: date, last_before, window_start: date, gap_days: int):
    if first_ever >= window_start:
        return "NEW", ""
    if last_before is None:
        return "ONGOING", ""
    gap = (window_start - last_before).days
    return ("REACTIVATED", gap) if gap >= gap_days else ("ONGOING", gap)


def _tg_link(username: str, user_id) -> str:
    if username:
        return "https://t.me/" + username.lstrip("@")
    if user_id != "" and user_id is not None:
        return f"tg://user?id={user_id}"
    return ""


def finalize(aggs: list[dict], start: date, gap_days: int) -> list[dict]:
    rows = []
    for a in aggs:
        status, gap = classify(a["first_ever"], a["last_before"], start, gap_days)
        if a["is_group"]:
            handle = ", ".join(a["members"][:a["group_size"]])
            typ = f"Group ({a['group_size']})"
        else:
            handle = a["username"]
            typ = "1:1"
        notes = []
        if not a["is_group"] and a["their_replies"] == 0:
            notes.append("Outbound only — no reply in window")
        if not a["is_group"] and not a["username"]:
            notes.append("no @username (export limitation — use live mode)")
        rows.append({
            "Name": a["name"],
            "Username": handle,
            "Telegram ID": a["user_id"] if not a["is_group"] else "",
            "Type": typ,
            "Status": status,
            "Msgs in window": a["msgs_in_window"],
            "Their replies": a["their_replies"],
            "First contact": a["first_ever"].isoformat(),
            "Last contact before": a["last_before"].isoformat() if a["last_before"] else "never",
            "Dormant days": gap,
            "Talked about (in window)": a.get("snippet", ""),
            "Followed up?": "",
            "Telegram link": _tg_link(a["username"], a["user_id"]) if not a["is_group"] else "",
            "Notes": "; ".join(notes),
        })
    rows.sort(key=lambda r: (
        STATUS_ORDER.get(r["Status"], 3),
        0 if r["Type"] == "1:1" else 1,
        -(r["Dormant days"] if isinstance(r["Dormant days"], int)
          and r["Status"] == "REACTIVATED" else 0),
        -r["Msgs in window"],
    ))
    return rows


def _csv_safe(v):
    """Defuse CSV/formula injection: a cell a spreadsheet would read as a
    formula (starts with = + - tab or CR) gets a leading apostrophe, so a
    contact name like '=HYPERLINK(...)' can't execute when opened in Sheets/Excel.
    ('@' is excluded — it's the legitimate username prefix and not an execution
    vector in modern spreadsheets.)"""
    if isinstance(v, str) and v and v[0] in ("=", "+", "-", "\t", "\r"):
        return "'" + v
    return v


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        # Build each row from CSV_FIELDS with .get() so a row missing any key
        # can never raise ValueError at the finish line.
        w.writerows({k: _csv_safe(r.get(k, "")) for k in CSV_FIELDS} for r in rows)


def write_html(rows: list[dict], path: str, conference: str,
               start: date, end: date) -> None:
    counts = {"NEW": 0, "REACTIVATED": 0, "ONGOING": 0}
    for r in rows:
        counts[r["Status"]] = counts.get(r["Status"], 0) + 1
    # Embed as JSON inside <script>. Escape the few sequences that could close
    # the tag or break the JS string literal — without this, a message
    # containing "</script>" would break out (XSS). These are all valid JSON
    # string escapes, so the data parses back identically.
    payload = (json.dumps(rows, ensure_ascii=False)
               .replace("<", "\u003c").replace(">", "\u003e")
               .replace(chr(0x2028), "\u2028").replace(chr(0x2029), "\u2029"))
    title = conference.strip() or "Conference"
    html = _TEMPLATE.replace("__TITLE__", _esc(title)) \
        .replace("__DATES__", f"{start.isoformat()} → {end.isoformat()}") \
        .replace("__NEW__", str(counts["NEW"])) \
        .replace("__REACT__", str(counts["REACTIVATED"])) \
        .replace("__ONGOING__", str(counts["ONGOING"])) \
        .replace("__TOTAL__", str(len(rows))) \
        .replace("__DATA__", payload)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ — Post-Conference CRM</title>
<style>
  :root{--bg:#0f1220;--card:#171a2b;--line:#272b40;--txt:#e7e9f3;--mut:#9aa0bd;
    --new:#2ecc71;--react:#f1c40f;--ongo:#5a6b8c;--accent:#6c8cff;--danger:#ff6b6b;
    --s-new:#6c8cff;--s-contacted:#a06bff;--s-replied:#f1c40f;--s-meeting:#e67e22;
    --s-won:#2ecc71;--s-lost:#6b7280}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
    font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
  header{padding:22px 28px 6px}
  h1{margin:0 0 2px;font-size:22px}
  .sub{color:var(--mut);font-size:14px}
  .cards{display:flex;gap:12px;flex-wrap:wrap;padding:12px 28px 4px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
    padding:10px 16px;min-width:104px}
  .card .n{font-size:22px;font-weight:700}
  .card .l{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
  .card.new .n{color:var(--new)} .card.react .n{color:var(--react)}
  .pipe{display:flex;gap:8px;flex-wrap:wrap;padding:6px 28px 2px}
  .pill{font-size:12px;color:var(--mut);background:var(--card);border:1px solid var(--line);
    border-radius:999px;padding:4px 10px}
  .pill b{color:var(--txt)}
  #due{margin:10px 28px 0;padding:10px 14px;border-radius:10px;display:none;
    background:rgba(255,107,107,.12);border:1px solid rgba(255,107,107,.4);
    color:#ffb3b3;font-size:14px;cursor:pointer}
  #due b{color:#fff}
  .controls{display:flex;gap:9px;flex-wrap:wrap;align-items:center;padding:12px 28px 12px}
  .chip{background:var(--card);border:1px solid var(--line);color:var(--txt);
    padding:7px 13px;border-radius:999px;cursor:pointer;font-size:13px;user-select:none}
  .chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
  input[type=search]{flex:1;min-width:170px;background:var(--card);
    border:1px solid var(--line);color:var(--txt);padding:9px 13px;border-radius:10px}
  select.fstage{background:var(--card);border:1px solid var(--line);color:var(--txt);
    padding:8px 11px;border-radius:10px;font-size:13px}
  .btn{background:var(--card);border:1px solid var(--line);color:var(--txt);
    padding:8px 13px;border-radius:10px;cursor:pointer;font-size:13px}
  .btn:hover{border-color:var(--accent)}
  .btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
  .wrap{padding:0 18px 60px;overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:14px;min-width:980px}
  th,td{padding:9px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
  th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;
    letter-spacing:.04em;cursor:pointer;position:sticky;top:0;background:var(--bg);white-space:nowrap}
  tr:hover{background:#1b1f33}
  tr.due td{box-shadow:inset 3px 0 0 var(--danger)}
  .badge{padding:3px 9px;border-radius:999px;font-size:11px;font-weight:700;white-space:nowrap}
  .b-NEW{background:rgba(46,204,113,.16);color:var(--new)}
  .b-REACTIVATED{background:rgba(241,196,15,.16);color:var(--react)}
  .b-ONGOING{background:rgba(120,140,180,.16);color:#aab4d4}
  a.tg{color:var(--accent);text-decoration:none;font-weight:600;white-space:nowrap}
  a.tg:hover{text-decoration:underline}
  .hand{color:var(--mut);font-size:12.5px}
  .note{color:var(--mut);font-size:12px}
  td.talk{color:#c7cce8;font-size:12.5px;max-width:240px;font-style:italic}
  select.stage{border:none;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:700;
    color:#fff;cursor:pointer;-webkit-appearance:none;appearance:none;text-align:center}
  select.stage option{background:var(--card);color:var(--txt);font-weight:600}
  .s-new{background:var(--s-new)} .s-contacted{background:var(--s-contacted)}
  .s-replied{background:var(--s-replied);color:#222} .s-meeting{background:var(--s-meeting)}
  .s-won{background:var(--s-won);color:#0b2417} .s-lost{background:var(--s-lost)}
  .remcell{white-space:nowrap}
  input[type=date]{background:var(--card);border:1px solid var(--line);color:var(--txt);
    padding:5px 7px;border-radius:8px;font-size:12px;color-scheme:dark}
  .ics{background:none;border:none;cursor:pointer;font-size:15px;padding:0 2px;opacity:.8}
  .ics:hover{opacity:1}
  .autonote{color:var(--mut);font-size:11px;margin-bottom:3px;font-style:italic}
  textarea.notes{width:200px;min-height:34px;background:var(--card);border:1px solid var(--line);
    color:var(--txt);border-radius:8px;padding:6px 8px;font:13px inherit;resize:vertical}
  textarea.notes:focus{border-color:var(--accent);outline:none;min-height:64px}
  .foot{color:var(--mut);font-size:12px;padding:18px 28px}
  #toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#222842;
    border:1px solid var(--line);color:#fff;padding:11px 18px;border-radius:10px;
    font-size:14px;opacity:0;pointer-events:none;transition:opacity .25s;z-index:9}
  #toast.show{opacity:1}
</style></head><body>
<header>
  <h1>📇 __TITLE__</h1>
  <div class="sub">Post-conference CRM · conference days __DATES__ · your edits save in this browser</div>
</header>
<div class="cards">
  <div class="card"><div class="n">__TOTAL__</div><div class="l">Total</div></div>
  <div class="card new"><div class="n">__NEW__</div><div class="l">New (met here)</div></div>
  <div class="card react"><div class="n">__REACT__</div><div class="l">Reactivated</div></div>
  <div class="card"><div class="n">__ONGOING__</div><div class="l">Ongoing</div></div>
</div>
<div class="pipe" id="pipe"></div>
<div id="due"></div>
<div class="controls">
  <span class="chip active" data-f="all">All</span>
  <span class="chip" data-f="NEW">🟢 New</span>
  <span class="chip" data-f="REACTIVATED">🟡 Reactivated</span>
  <span class="chip" data-f="ONGOING">⚪ Ongoing</span>
  <span class="chip" data-f="due">⏰ Due</span>
  <select class="fstage" id="fstage"><option value="">Any stage</option></select>
  <input type="search" id="q" placeholder="Search name, @username, notes…">
  <button class="btn primary" id="dl">⬇ Download CRM</button>
  <button class="btn" id="imp">⬆ Import</button>
  <input type="file" id="impfile" accept=".csv,text/csv" style="display:none">
</div>
<div class="wrap"><table id="t"><thead><tr>
  <th data-k="Name">Name</th><th data-k="Username">@username / members</th>
  <th data-k="Telegram ID">ID</th><th data-k="Status">Status</th>
  <th data-k="__stage">Stage</th>
  <th data-k="Msgs in window">Msgs</th><th data-k="Their replies">Replies</th>
  <th data-k="First contact">First</th><th data-k="Last contact before">Last before</th>
  <th data-k="Talked about (in window)">Talked about</th><th>Open</th>
  <th data-k="__remind">Reminder</th><th>Notes</th>
</tr></thead><tbody id="body"></tbody></table></div>
<div class="foot">Generated locally · your data never left your machine · stages, notes &amp; reminders are stored in this browser — use <b>Download CRM</b> to back them up or move them to a spreadsheet.</div>
<div id="toast"></div>
<script>
const DATA = __DATA__;
const META = {title:"__TITLE__"};
const KEY = "tgcrm:"+location.pathname;
const STAGES = [
  {v:"new",l:"New"},{v:"contacted",l:"Contacted"},{v:"replied",l:"Replied"},
  {v:"meeting",l:"Meeting"},{v:"won",l:"Won"},{v:"lost",l:"Lost"}];
const STAGE_L = Object.fromEntries(STAGES.map(s=>[s.v,s.l]));
const L_STAGE = Object.fromEntries(STAGES.map(s=>[s.l.toLowerCase(),s.v]));
const COLS = ["Name","Username","Telegram ID","Type","Status","Msgs in window",
  "Their replies","First contact","Last contact before","Dormant days",
  "Talked about (in window)","Followed up?","Telegram link","Notes",
  "Stage","My notes","Reminder"];

let store = loadStore();
let filter="all", q="", fstage="", sortK=null, sortAsc=true;

function loadStore(){
  let s={};
  try{ s=JSON.parse(localStorage.getItem(KEY)||"{}"); }catch(e){ s={}; }
  // Migrate the old format: a checked follow-up box was stored as 1/true.
  for(const k in s){
    const v=s[k];
    if(v===1||v===true) s[k]={stage:"contacted"};
    else if(typeof v!=="object"||v===null) s[k]={};
  }
  return s;
}
function save(){ try{ localStorage.setItem(KEY,JSON.stringify(store)); }
  catch(e){ toast("Couldn't save — browser storage may be full."); } }
const get = id => store[id] || {};
const rec = id => (store[id] || (store[id]={}));
const idOf = r => r.Username || (r["Telegram ID"]!==""&&r["Telegram ID"]!=null?("id:"+r["Telegram ID"]):("nm:"+r.Name));
const esc = s => String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function todayISO(){ const d=new Date(); d.setMinutes(d.getMinutes()-d.getTimezoneOffset());
  return d.toISOString().slice(0,10); }
const isDue = id => { const r=get(id).remind; return r && r<=todayISO(); };

let toastT;
function toast(m){ const t=document.getElementById("toast"); t.textContent=m;
  t.classList.add("show"); clearTimeout(toastT); toastT=setTimeout(()=>t.classList.remove("show"),2600); }

function stageSelect(id){
  const stg=get(id).stage||"new";
  return `<select class="stage s-${stg}" data-id="${esc(id)}">`+
    STAGES.map(o=>`<option value="${o.v}"${o.v===stg?" selected":""}>${o.l}</option>`).join("")+
    `</select>`;
}
function rowHTML(r){
  const id=idOf(r), g=get(id);
  const link=r["Telegram link"]?`<a class="tg" href="${esc(r["Telegram link"])}">open ↗</a>`:"";
  const handle=r.Username?`<span class="hand">${esc(r.Username)}</span>`:"";
  const auto=r.Notes?`<div class="autonote">${esc(r.Notes)}</div>`:"";
  return `<tr class="${isDue(id)?'due':''}">
    <td><b>${esc(r.Name)}</b></td><td>${handle}</td>
    <td>${esc(r["Telegram ID"])}</td>
    <td><span class="badge b-${r.Status}">${r.Status}</span></td>
    <td>${stageSelect(id)}</td>
    <td>${r["Msgs in window"]}</td><td>${r["Their replies"]}</td>
    <td>${esc(r["First contact"])}</td><td>${esc(r["Last contact before"])}</td>
    <td class="talk">${esc(r["Talked about (in window)"])}</td>
    <td>${link}</td>
    <td class="remcell"><input type="date" class="rem" data-id="${esc(id)}" value="${esc(g.remind||"")}">
      <button class="ics" data-id="${esc(id)}" title="Add to calendar (.ics)">📅</button></td>
    <td><div>${auto}<textarea class="notes" data-id="${esc(id)}" placeholder="Add notes…">${esc(g.notes||"")}</textarea></div></td>
  </tr>`;
}
function valFor(r,k){
  if(k==="__stage") return STAGES.findIndex(s=>s.v===(get(idOf(r)).stage||"new"));
  if(k==="__remind") return get(idOf(r)).remind||"9999-99-99";
  return r[k];
}
function visible(){
  return DATA.filter(r=>{
    const id=idOf(r);
    if(filter==="due"){ if(!isDue(id))return false; }
    else if(filter!=="all" && r.Status!==filter) return false;
    if(fstage && (get(id).stage||"new")!==fstage) return false;
    if(q){ const h=(r.Name+" "+r.Username+" "+(r.Notes||"")+" "+(get(id).notes||"")+" "+
      r["Telegram ID"]+" "+(r["Talked about (in window)"]||"")).toLowerCase();
      if(!h.includes(q)) return false; }
    return true;
  });
}
function render(){
  let rows=visible();
  if(sortK){ rows.sort((a,b)=>{ let x=valFor(a,sortK),y=valFor(b,sortK);
    if(typeof x==="number")return sortAsc?x-y:y-x;
    return sortAsc?String(x).localeCompare(String(y)):String(y).localeCompare(String(x)); }); }
  document.getElementById("body").innerHTML=rows.map(rowHTML).join("");
  renderPipe();
}
function renderPipe(){
  const c={}; STAGES.forEach(s=>c[s.v]=0);
  DATA.forEach(r=>{ c[get(idOf(r)).stage||"new"]++; });
  document.getElementById("pipe").innerHTML=
    STAGES.map(s=>`<span class="pill">${s.l} <b>${c[s.v]}</b></span>`).join("");
  const due=DATA.filter(r=>isDue(idOf(r))).length;
  const d=document.getElementById("due");
  if(due){ d.style.display="block"; d.innerHTML=`⏰ <b>${due}</b> follow-up${due>1?"s":""} due — click to see ${due>1?"them":"it"}`; }
  else d.style.display="none";
}

// ---- calendar (.ics) ----
function icsEsc(s){ return String(s).replace(/[\\;,]/g,m=>"\\"+m).replace(/\n/g,"\\n"); }
function download(name,text,type){ const b=new Blob([text],{type:type||"text/plain"});
  const u=URL.createObjectURL(b),a=document.createElement("a");
  a.href=u; a.download=name; document.body.appendChild(a); a.click();
  a.remove(); setTimeout(()=>URL.revokeObjectURL(u),1000); }
function makeICS(name,dateISO,id){
  const dt=dateISO.replace(/-/g,"");
  return ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//tgcrm//conference-crm//EN",
    "BEGIN:VEVENT","UID:"+icsEsc(id)+"-"+dt+"@tgcrm",
    "DTSTART;VALUE=DATE:"+dt,"DTEND;VALUE=DATE:"+dt,
    "SUMMARY:Follow up with "+icsEsc(name),
    "DESCRIPTION:"+icsEsc("Post-conference follow-up ("+META.title+")"),
    "BEGIN:VALARM","TRIGGER:-PT9H","ACTION:DISPLAY","DESCRIPTION:Follow up","END:VALARM",
    "END:VEVENT","END:VCALENDAR"].join("\r\n");
}

// ---- CSV export / import ----
function csvCell(v){ v=v==null?"":String(v);
  return /[",\n\r]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v; }
function exportCSV(){
  const lines=[COLS.map(csvCell).join(",")];
  DATA.forEach(r=>{ const id=idOf(r),g=get(id),stg=g.stage||"new";
    const row=COLS.map(col=>{
      if(col==="Stage") return STAGE_L[stg];
      if(col==="My notes") return g.notes||"";
      if(col==="Reminder") return g.remind||"";
      if(col==="Followed up?") return (stg!=="new")?"yes":"";
      return r[col]!=null?r[col]:"";
    });
    lines.push(row.map(csvCell).join(","));
  });
  download("conference_crm.csv", lines.join("\r\n"), "text/csv");
  toast("Downloaded CRM with your stages, notes & reminders.");
}
function parseCSV(text){
  const rows=[]; let row=[],cur="",q=false;
  for(let i=0;i<text.length;i++){ const ch=text[i];
    if(q){ if(ch==='"'){ if(text[i+1]==='"'){cur+='"';i++;} else q=false; } else cur+=ch; }
    else if(ch==='"') q=true;
    else if(ch===',') { row.push(cur); cur=""; }
    else if(ch==='\n'){ row.push(cur); rows.push(row); row=[]; cur=""; }
    else if(ch==='\r'){ /* skip */ }
    else cur+=ch;
  }
  if(cur!==""||row.length){ row.push(cur); rows.push(row); }
  return rows.filter(r=>r.length>1||(r.length===1&&r[0]!==""));
}
function importCSV(text){
  const rows=parseCSV(text); if(!rows.length){ toast("That file looks empty."); return; }
  const hdr=rows[0].map(h=>h.trim());
  const ix=n=>hdr.indexOf(n);
  const iU=ix("Username"), iID=ix("Telegram ID"), iN=ix("Name"),
        iS=ix("Stage"), iMN=ix("My notes"), iR=ix("Reminder");
  if(iN<0 && iU<0 && iID<0){ toast("No Name/Username/Telegram ID column — not a CRM export."); return; }
  if(iS<0 && iMN<0 && iR<0){ toast("No Stage/My notes/Reminder columns to import."); return; }
  const byId={}; DATA.forEach(r=>byId[idOf(r)]=true);
  let n=0;
  for(let i=1;i<rows.length;i++){ const c=rows[i];
    const u=iU>=0?(c[iU]||"").trim():"", id4=iID>=0?(c[iID]||"").trim():"", nm=iN>=0?(c[iN]||"").trim():"";
    const id = u || (id4?("id:"+id4):("nm:"+nm));
    if(!id || !byId[id]) continue;
    const g=rec(id);
    if(iS>=0){ const sv=(c[iS]||"").trim().toLowerCase(); if(L_STAGE[sv]) g.stage=L_STAGE[sv]; }
    if(iMN>=0){ const t=(c[iMN]||""); if(t) g.notes=t; }
    if(iR>=0){ const t=(c[iR]||"").trim(); if(/^\d{4}-\d{2}-\d{2}$/.test(t)) g.remind=t; }
    n++;
  }
  save(); render();
  toast(n?("Imported edits for "+n+" contact"+(n>1?"s":"")+"."):"Nothing matched this conference's contacts.");
}

// ---- wiring ----
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{
  document.querySelectorAll(".chip").forEach(x=>x.classList.remove("active"));
  c.classList.add("active"); filter=c.dataset.f; render(); });
document.getElementById("due").onclick=()=>{
  document.querySelectorAll(".chip").forEach(x=>x.classList.toggle("active",x.dataset.f==="due"));
  filter="due"; render(); };
document.getElementById("q").oninput=e=>{ q=e.target.value.toLowerCase().trim(); render(); };
const fst=document.getElementById("fstage");
STAGES.forEach(s=>{ const o=document.createElement("option"); o.value=s.v; o.textContent=s.l; fst.appendChild(o); });
fst.onchange=e=>{ fstage=e.target.value; render(); };
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{
  const k=th.dataset.k; sortAsc=sortK===k?!sortAsc:true; sortK=k; render(); });
document.getElementById("dl").onclick=exportCSV;
document.getElementById("imp").onclick=()=>document.getElementById("impfile").click();
document.getElementById("impfile").onchange=e=>{ const f=e.target.files[0]; if(!f)return;
  const rd=new FileReader(); rd.onload=()=>importCSV(String(rd.result)); rd.readAsText(f); e.target.value=""; };

let notesT;
const body=document.getElementById("body");
body.addEventListener("change",e=>{
  const t=e.target, id=t.dataset.id;
  if(t.classList.contains("stage")){ rec(id).stage=t.value;
    t.className="stage s-"+t.value; save(); renderPipe(); }
  else if(t.classList.contains("rem")){ const v=t.value;
    if(v) rec(id).remind=v; else delete rec(id).remind; save();
    t.closest("tr").classList.toggle("due",isDue(id)); renderPipe(); }
});
body.addEventListener("input",e=>{
  if(e.target.classList.contains("notes")){ const id=e.target.dataset.id, v=e.target.value;
    clearTimeout(notesT); notesT=setTimeout(()=>{ if(v) rec(id).notes=v; else delete rec(id).notes; save(); },400); }
});
body.addEventListener("click",e=>{
  if(e.target.classList.contains("ics")){ const id=e.target.dataset.id, g=get(id);
    if(!g.remind){ toast("Set a reminder date first, then add it to your calendar."); return; }
    const r=DATA.find(x=>idOf(x)===id);
    download("follow-up-"+id.replace(/[^a-z0-9]+/gi,"_")+".ics", makeICS(r?r.Name:id,g.remind,id), "text/calendar");
    toast("Calendar event downloaded — open it to add the reminder."); }
});
render();
</script></body></html>
"""
