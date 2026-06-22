"""Classification + output (CSV and a self-contained interactive HTML CRM)."""
from __future__ import annotations

import csv
import json
from datetime import date

STATUS_ORDER = {"NEW": 0, "REACTIVATED": 1, "ONGOING": 2}

CSV_FIELDS = ["Name", "Username", "Telegram ID", "Type", "Status",
              "Msgs in window", "Their replies", "First contact",
              "Last contact before", "Dormant days", "Talked about (in window)",
              "Followed up?", "Telegram link", "Notes"]


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
        w.writerows({k: _csv_safe(v) for k, v in r.items()} for r in rows)


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
               .replace("<", "\\u003c").replace(">", "\\u003e")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
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
    --new:#2ecc71;--react:#f1c40f;--ongo:#5a6b8c;--accent:#6c8cff}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
    font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
  header{padding:24px 28px 8px}
  h1{margin:0 0 2px;font-size:22px}
  .sub{color:var(--mut);font-size:14px}
  .cards{display:flex;gap:12px;flex-wrap:wrap;padding:14px 28px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
    padding:12px 16px;min-width:120px}
  .card .n{font-size:24px;font-weight:700}
  .card .l{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
  .card.new .n{color:var(--new)} .card.react .n{color:var(--react)}
  .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;padding:6px 28px 14px}
  .chip{background:var(--card);border:1px solid var(--line);color:var(--txt);
    padding:7px 13px;border-radius:999px;cursor:pointer;font-size:13px}
  .chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
  input[type=search]{flex:1;min-width:180px;background:var(--card);
    border:1px solid var(--line);color:var(--txt);padding:9px 13px;border-radius:10px}
  .wrap{padding:0 18px 40px}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
  th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;
    letter-spacing:.04em;cursor:pointer;position:sticky;top:0;background:var(--bg)}
  tr:hover{background:#1b1f33}
  .badge{padding:3px 9px;border-radius:999px;font-size:11px;font-weight:700;white-space:nowrap}
  .b-NEW{background:rgba(46,204,113,.16);color:var(--new)}
  .b-REACTIVATED{background:rgba(241,196,15,.16);color:var(--react)}
  .b-ONGOING{background:rgba(120,140,180,.16);color:#aab4d4}
  a.tg{color:var(--accent);text-decoration:none;font-weight:600}
  a.tg:hover{text-decoration:underline}
  .hand{color:var(--mut)}
  .note{color:var(--mut);font-size:12px}
  td.talk{color:#c7cce8;font-size:12.5px;max-width:340px;font-style:italic}
  td.fu{text-align:center}
  input[type=checkbox]{width:18px;height:18px;accent-color:var(--new);cursor:pointer}
  .foot{color:var(--mut);font-size:12px;padding:18px 28px}
  .done{opacity:.5}
</style></head><body>
<header>
  <h1>📇 __TITLE__</h1>
  <div class="sub">Post-conference CRM · conference days __DATES__ · check people off as you follow up (saved in your browser)</div>
</header>
<div class="cards">
  <div class="card"><div class="n">__TOTAL__</div><div class="l">Total</div></div>
  <div class="card new"><div class="n">__NEW__</div><div class="l">New (met here)</div></div>
  <div class="card react"><div class="n">__REACT__</div><div class="l">Reactivated</div></div>
  <div class="card"><div class="n">__ONGOING__</div><div class="l">Ongoing</div></div>
</div>
<div class="controls">
  <span class="chip active" data-f="all">All</span>
  <span class="chip" data-f="NEW">🟢 New</span>
  <span class="chip" data-f="REACTIVATED">🟡 Reactivated</span>
  <span class="chip" data-f="ONGOING">⚪ Ongoing</span>
  <span class="chip" data-f="todo">☐ Not followed up</span>
  <input type="search" id="q" placeholder="Search name, @username, notes…">
</div>
<div class="wrap"><table id="t"><thead><tr>
  <th data-k="Name">Name</th><th data-k="Username">@username / members</th>
  <th data-k="Telegram ID">Telegram ID</th><th data-k="Type">Type</th>
  <th data-k="Status">Status</th><th data-k="Msgs in window">Msgs</th>
  <th data-k="Their replies">Replies</th><th data-k="First contact">First</th>
  <th data-k="Last contact before">Last before</th>
  <th data-k="Talked about (in window)">Talked about</th><th>Open</th>
  <th>Followed up?</th><th data-k="Notes">Notes</th>
</tr></thead><tbody id="body"></tbody></table></div>
<div class="foot">Generated locally · your data never left your machine · follow-up ticks are stored in this browser only.</div>
<script>
const DATA = __DATA__;
const KEY = "tgcrm:"+location.pathname;
const store = JSON.parse(localStorage.getItem(KEY) || "{}");
let filter="all", q="", sortK=null, sortAsc=true;
const idOf = r => r.Username || (r["Telegram ID"]!==""?("id:"+r["Telegram ID"]):("nm:"+r.Name));
const esc = s => String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function rowHTML(r){
  const k=idOf(r), done=!!store[k];
  const link=r["Telegram link"]?`<a class="tg" href="${esc(r["Telegram link"])}">open ↗</a>`:"";
  const handle=r.Username?`<span class="hand">${esc(r.Username)}</span>`:"";
  return `<tr class="${done?'done':''}">
    <td><b>${esc(r.Name)}</b></td><td>${handle}</td>
    <td>${esc(r["Telegram ID"])}</td><td>${esc(r.Type)}</td>
    <td><span class="badge b-${r.Status}">${r.Status}</span></td>
    <td>${r["Msgs in window"]}</td><td>${r["Their replies"]}</td>
    <td>${esc(r["First contact"])}</td><td>${esc(r["Last contact before"])}</td>
    <td class="talk">${esc(r["Talked about (in window)"])}</td>
    <td>${link}</td>
    <td class="fu"><input type="checkbox" data-k="${esc(k)}" ${done?"checked":""}></td>
    <td class="note">${esc(r.Notes)}</td></tr>`;
}
function render(){
  let rows=DATA.filter(r=>{
    if(filter==="todo"){if(store[idOf(r)])return false;}
    else if(filter!=="all" && r.Status!==filter)return false;
    if(q){const h=(r.Name+" "+r.Username+" "+r.Notes+" "+(r["Telegram ID"])+" "+(r["Talked about (in window)"]||"")).toLowerCase();
      if(!h.includes(q))return false;}
    return true;});
  if(sortK){rows.sort((a,b)=>{let x=a[sortK],y=b[sortK];
    if(typeof x==="number")return sortAsc?x-y:y-x;
    return sortAsc?String(x).localeCompare(String(y)):String(y).localeCompare(String(x));});}
  document.getElementById("body").innerHTML=rows.map(rowHTML).join("");
}
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{
  document.querySelectorAll(".chip").forEach(x=>x.classList.remove("active"));
  c.classList.add("active");filter=c.dataset.f;render();});
document.getElementById("q").oninput=e=>{q=e.target.value.toLowerCase().trim();render();};
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{
  const k=th.dataset.k;sortAsc=sortK===k?!sortAsc:true;sortK=k;render();});
document.getElementById("body").addEventListener("change",e=>{
  if(e.target.type==="checkbox"){const k=e.target.dataset.k;
    if(e.target.checked)store[k]=1;else delete store[k];
    localStorage.setItem(KEY,JSON.stringify(store));
    e.target.closest("tr").classList.toggle("done",e.target.checked);
    if(filter==="todo")render();}});
render();
</script></body></html>
"""
