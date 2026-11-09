"""
כלי עזר: מייצר דף HTML אחד לצפייה בתיבת הדמו (data/demo/demo_viewer.html), שנפתח בכל דפדפן.
לא חלק מהמערכת. המטרה: לראות בעין את כל מה שבתיבה, ולוודא שהדמו מכסה את המקרים שתכננו.

הדף מציג לכל מייל:
- את הגוף כפי שהוא (טקסט או HTML בתוך iframe מבודד, בלי סקריפטים), את השרשור ואת הקבצים המצורפים;
- את הטקסט שחולץ מ-PDF ומ-docx, כלומר מה שהמערכת "תראה";
- מה-manifest: מה המייל בודק, והאם הוא אמור להיות מאונדקס;
- פרטים טכניים: קידוד כל חלק, הכותרות הגולמיות (כולל RFC2047) והמקור המלא.

הרצה (מתיקיית gmail_rag):  python demo/view_mailbox.py [נתיב לקובץ mbox]
"""
import base64
import io
import json
import mailbox
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path

GMAIL_RAG_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = GMAIL_RAG_DIR / "data" / "demo"
OUT_PATH = DEMO_DIR / "demo_viewer.html"


def extract_text(name: str, data: bytes) -> str | None:
    """טקסט מ-PDF או docx, כדי לראות מה ייכנס לאינדקס. None לסוגים אחרים."""
    low = name.lower()
    try:
        if low.endswith(".pdf"):
            import pypdf
            text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages).strip()
            return text or "(אין שכבת טקסט: PDF סרוק)"
        if low.endswith(".docx"):
            import docx
            return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    except Exception as e:   # כלי צפייה: מציגים את השגיאה ולא נופלים
        return f"(שגיאה בחילוץ: {e})"
    return None


def parse_message(raw: bytes) -> dict:
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    # תמונות מוטבעות (cid:) הופכות ל-data URI, כדי שה-HTML יוצג עם הלוגו
    cids = {}
    for part in msg.walk():
        cid = part.get("Content-ID")
        if cid and part.get_content_maintype() == "image":
            data = base64.b64encode(part.get_payload(decode=True)).decode()
            cids[cid.strip("<>")] = f"data:{part.get_content_type()};base64,{data}"

    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    html_text = html.get_content() if html else ""
    for cid, uri in cids.items():
        html_text = html_text.replace(f"cid:{cid}", uri)

    parts = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        parts.append({
            "type": part.get_content_type(),
            "charset": part.get_content_charset() or "",
            "cte": part.get("Content-Transfer-Encoding", ""),
            "filename": part.get_filename() or "",
        })

    attachments = []
    for part in msg.iter_attachments():
        name = part.get_filename() or "(ללא שם)"
        if part.get_content_type() == "message/rfc822":
            inner = part.get_payload(0)
            data = inner.as_bytes()
            text = f"מאת: {inner['From']}\nנושא: {inner['Subject']}\n\n" + (
                inner.get_body(preferencelist=("plain",)).get_content() if inner.get_body(("plain",)) else "")
        else:
            data = part.get_payload(decode=True) or b""
            text = extract_text(name, data)
        attachments.append({
            "name": name,
            "type": part.get_content_type(),
            "size": len(data),
            "inline": part.get_content_disposition() == "inline",
            "uri": f"data:{part.get_content_type()};base64,{base64.b64encode(data).decode()}",
            "text": text,
        })

    raw_text = raw.decode("utf-8", "replace")
    header_end = raw_text.find("\n\n")
    return {
        "from": str(msg["From"] or ""),
        "to": str(msg["To"] or ""),
        "cc": str(msg["Cc"] or ""),
        "reply_to": str(msg["Reply-To"] or ""),
        "plain": plain.get_content() if plain else "",
        "html": html_text,
        "parts": parts,
        "attachments": attachments,
        "raw_headers": raw_text[:header_end] if header_end > 0 else raw_text,
        "raw": raw_text if len(raw_text) < 60_000 else raw_text[:60_000] + "\n...(קוצר)",
    }


def main() -> None:
    mbox_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEMO_DIR / "demo_mailbox.mbox"
    manifest_path = mbox_path.with_name("demo_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []

    messages = []
    for i, m in enumerate(mailbox.mbox(str(mbox_path))):
        item = parse_message(m.as_bytes())
        meta = manifest[i] if i < len(manifest) else {}
        item.update({
            "i": i,
            "key": meta.get("key", ""),
            "message_id": m["Message-ID"] or "",
            "thread_id": meta.get("thread_id") or "",
            "date": meta.get("date", str(m["Date"])),
            "subject": meta.get("subject", ""),
            "labels": meta.get("labels", []),
            "topic": meta.get("topic", ""),
            "expect": meta.get("expect", ""),
            "note": meta.get("note", ""),
            "html_only": meta.get("html_only", False),
        })
        messages.append(item)

    data = json.dumps(messages, ensure_ascii=False).replace("</", "<\\/")
    OUT_PATH.write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")
    print(f"נוצר {OUT_PATH.relative_to(GMAIL_RAG_DIR)} ({len(messages)} הודעות). פתחו אותו בדפדפן.")


TEMPLATE = r"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>תיבת הדמו</title>
<style>
:root {
  --bg: #f6f5f2; --panel: #ffffff; --ink: #1d1d1f; --muted: #6b6b70; --line: #e3e1dc;
  --accent: #2f5d8a; --accent-soft: #e6eef6; --sel: #dfe9f3;
  --ok: #2e7d4f; --ok-soft: #e3f2e9; --bad: #a33a2b; --bad-soft: #f8e5e1; --warn: #8a6a12; --warn-soft: #f7efd6;
  --code: #f1efea;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #17181a; --panel: #1f2023; --ink: #ececee; --muted: #9a9aa2; --line: #33343a;
    --accent: #8fb8e0; --accent-soft: #24313e; --sel: #2a3746;
    --ok: #7fcf9d; --ok-soft: #1f3327; --bad: #ef9a8a; --bad-soft: #3a2420; --warn: #e3c46b; --warn-soft: #382f17;
    --code: #2a2b2f;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.5 "Segoe UI", Arial, sans-serif; }
header { padding: 12px 16px; border-bottom: 1px solid var(--line); background: var(--panel); }
header h1 { margin: 0 0 8px; font-size: 18px; }
.stats { color: var(--muted); font-size: 13px; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.filters input, .filters select { font: inherit; padding: 5px 8px; border: 1px solid var(--line); border-radius: 6px;
  background: var(--bg); color: var(--ink); }
.filters input[type=search] { flex: 1 1 220px; }
.filters label { display: flex; align-items: center; gap: 4px; color: var(--muted); font-size: 13px; }
main { display: grid; grid-template-columns: minmax(280px, 380px) 1fr; height: calc(100vh - 118px); }
#list { overflow-y: auto; border-left: 1px solid var(--line); background: var(--panel); }
.row { padding: 8px 12px; border-bottom: 1px solid var(--line); cursor: pointer; }
.row:hover { background: var(--accent-soft); }
.row.sel { background: var(--sel); }
.row .top { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--muted); }
.row .subj { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row .icons { font-size: 12px; color: var(--muted); }
.badge { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; margin-inline-end: 4px; }
.b-indexed { background: var(--ok-soft); color: var(--ok); }
.b-excluded { background: var(--bad-soft); color: var(--bad); }
.b-duplicate { background: var(--warn-soft); color: var(--warn); }
.b-label { background: var(--code); color: var(--muted); font-weight: 400; }
#view { overflow-y: auto; padding: 16px 20px 40px; }
#view h2 { margin: 0 0 8px; font-size: 20px; }
.meta { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; font-size: 13px; margin: 8px 0; }
.meta b { color: var(--muted); font-weight: 400; }
.ltr { direction: ltr; unicode-bidi: plaintext; }
.note { background: var(--accent-soft); border-inline-start: 3px solid var(--accent); padding: 8px 12px; border-radius: 4px; margin: 10px 0; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); margin-top: 14px; }
.tabs button { font: inherit; background: none; border: none; padding: 6px 12px; cursor: pointer; color: var(--muted);
  border-bottom: 2px solid transparent; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
pre { white-space: pre-wrap; word-break: break-word; background: var(--code); padding: 12px; border-radius: 6px;
  margin: 10px 0; font: 13px/1.55 Consolas, "Courier New", monospace; unicode-bidi: plaintext; }
pre.body { font: 14px/1.6 "Segoe UI", Arial, sans-serif; background: var(--panel); border: 1px solid var(--line); }
iframe { width: 100%; height: 520px; border: 1px solid var(--line); border-radius: 6px; background: #fff; margin-top: 10px; }
.att { border: 1px solid var(--line); border-radius: 6px; padding: 8px 12px; margin: 8px 0; background: var(--panel); }
.att img { max-width: 260px; max-height: 200px; display: block; margin-top: 6px; border-radius: 4px; }
.att a { color: var(--accent); }
table.parts { border-collapse: collapse; font-size: 12px; margin-top: 8px; }
table.parts td, table.parts th { border: 1px solid var(--line); padding: 3px 8px; text-align: start; }
.thread a { color: var(--accent); cursor: pointer; text-decoration: underline; }
.thread .cur { font-weight: 600; }
.empty { color: var(--muted); padding: 40px; text-align: center; }
@media (max-width: 760px) {
  main { grid-template-columns: 1fr; height: auto; }
  #list { max-height: 45vh; border-left: none; border-bottom: 1px solid var(--line); }
  #view { padding: 12px 16px 40px; }
}
</style>
</head>
<body>
<header>
  <h1>תיבת הדמו של חני לוין</h1>
  <div class="stats" id="stats"></div>
  <div class="filters">
    <input type="search" id="q" placeholder="חיפוש בנושא, בשולח, בגוף ובהערות...">
    <select id="topic"><option value="">כל התחומים</option></select>
    <select id="expect">
      <option value="">כל הסטטוסים</option>
      <option value="indexed">יאונדקס</option>
      <option value="excluded">לא יאונדקס</option>
      <option value="duplicate">כפילות</option>
    </select>
    <label><input type="checkbox" id="f-att"> עם קבצים</label>
    <label><input type="checkbox" id="f-html"> HTML בלבד</label>
    <label><input type="checkbox" id="f-sent"> יוצא</label>
    <label><input type="checkbox" id="f-update"> מידע שהתעדכן</label>
    <select id="sort"><option value="file">סדר בקובץ</option><option value="date">לפי תאריך</option></select>
  </div>
</header>
<main>
  <div id="list"></div>
  <div id="view"><div class="empty">בחרו מייל מהרשימה</div></div>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const MSGS = JSON.parse(document.getElementById("data").textContent);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const EXPECT = {
  "indexed": ["יאונדקס", "b-indexed"], "duplicate": ["כפילות", "b-duplicate"],
  "excluded:label": ["לא יאונדקס: תווית", "b-excluded"], "excluded:date": ["לא יאונדקס: ישן", "b-excluded"],
  "excluded:blacklist": ["לא יאונדקס: רשימה שחורה", "b-excluded"],
};
const badge = (e) => { const [t, c] = EXPECT[e] || [e, "b-label"]; return `<span class="badge ${c}">${esc(t)}</span>`; };
const isSent = (m) => m.labels.includes("Sent");
const isUpdate = (m) => /התעדכן/.test(m.note);
let current = null, tab = "body";

[...new Set(MSGS.map((m) => m.topic))].forEach((t) => $("topic").insertAdjacentHTML("beforeend", `<option>${esc(t)}</option>`));

function stats() {
  const n = (f) => MSGS.filter(f).length;
  $("stats").textContent = `${MSGS.length} הודעות | ${n((m) => m.expect === "indexed")} יאונדקסו | `
    + `${n((m) => m.expect.startsWith("excluded"))} יסוננו | ${n((m) => m.expect === "duplicate")} כפילות | `
    + `${n(isSent)} יוצאות | ${n((m) => m.attachments.some((a) => !a.inline))} עם קבצים | ${n((m) => m.html_only)} HTML בלבד`;
}

function filtered() {
  const q = $("q").value.trim().toLowerCase();
  let list = MSGS.filter((m) =>
    (!$("topic").value || m.topic === $("topic").value) &&
    (!$("expect").value || m.expect.startsWith($("expect").value)) &&
    (!$("f-att").checked || m.attachments.some((a) => !a.inline)) &&
    (!$("f-html").checked || m.html_only) &&
    (!$("f-sent").checked || isSent(m)) &&
    (!$("f-update").checked || isUpdate(m)) &&
    (!q || [m.subject, m.from, m.to, m.plain, m.html, m.note, m.key, ...m.attachments.map((a) => a.name + " " + (a.text || ""))]
      .join(" ").toLowerCase().includes(q)));
  if ($("sort").value === "date") list = [...list].sort((a, b) => b.date.localeCompare(a.date));
  return list;
}

function renderList() {
  const list = filtered();
  $("list").innerHTML = list.length ? list.map((m) => `
    <div class="row ${current === m.i ? "sel" : ""}" data-i="${m.i}">
      <div class="top"><span>${esc(m.from.replace(/<.*>/, "").trim() || m.from)}</span><span>${esc(m.date.slice(0, 10))}</span></div>
      <div class="subj">${esc(m.subject || "(ללא נושא)")}</div>
      <div class="icons">${badge(m.expect)}${isSent(m) ? "↩ יוצא " : ""}${m.attachments.some((a) => !a.inline) ? "📎 " : ""}${m.html_only ? "HTML " : ""}${esc(m.topic)}</div>
    </div>`).join("") : '<div class="empty">אין תוצאות</div>';
  $("list").querySelectorAll(".row").forEach((r) => r.onclick = () => show(+r.dataset.i));
}

function fmtSize(n) { return n > 1024 ? (n / 1024).toFixed(1) + " KB" : n + " B"; }

function show(i) {
  current = i;
  const m = MSGS[i];
  const thread = m.thread_id ? MSGS.filter((x) => x.thread_id === m.thread_id) : [];
  const atts = m.attachments;
  const body = tab === "body"
    ? (m.plain ? `<pre class="body" dir="auto">${esc(m.plain)}</pre>` : "")
      + (m.html ? `<iframe sandbox="" srcdoc="${esc(m.html)}"></iframe>` : "")
      + (!m.plain && !m.html ? '<div class="empty">(גוף ריק)</div>' : "")
    : tab === "htmlsrc" ? `<pre class="ltr">${esc(m.html || "(אין חלק HTML)")}</pre>`
    : tab === "headers" ? `<pre class="ltr">${esc(m.raw_headers)}</pre>
        <table class="parts"><tr><th>חלק</th><th>charset</th><th>קידוד העברה</th><th>שם קובץ</th></tr>
        ${m.parts.map((p) => `<tr><td class="ltr">${esc(p.type)}</td><td>${esc(p.charset)}</td><td>${esc(p.cte)}</td><td>${esc(p.filename)}</td></tr>`).join("")}</table>`
    : `<pre class="ltr">${esc(m.raw)}</pre>`;
  $("view").innerHTML = `
    <h2 dir="auto">${esc(m.subject || "(ללא נושא)")}</h2>
    <div>${badge(m.expect)}${m.labels.map((l) => `<span class="badge b-label">${esc(l)}</span>`).join("")}</div>
    <div class="meta">
      <b>מאת</b><span dir="auto">${esc(m.from)}</span>
      <b>אל</b><span dir="auto">${esc(m.to)}</span>
      ${m.cc ? `<b>עותק</b><span dir="auto">${esc(m.cc)}</span>` : ""}
      ${m.reply_to ? `<b>Reply-To</b><span dir="auto">${esc(m.reply_to)}</span>` : ""}
      <b>תאריך</b><span>${esc(m.date)}</span>
      <b>Message-ID</b><span class="ltr">${esc(m.message_id)}</span>
      <b>Thread</b><span class="ltr">${esc(m.thread_id || "(אין X-GM-THRID)")}</span>
      <b>תחום</b><span>${esc(m.topic)}</span>
    </div>
    ${m.note ? `<div class="note"><b>מה המייל הזה בודק:</b> ${esc(m.note)}</div>` : ""}
    ${thread.length > 1 ? `<div class="thread"><b>שרשור (${thread.length}):</b> ${thread.map((x) =>
      x.i === i ? `<span class="cur">${esc(x.date.slice(5, 16))}</span>` : `<a data-i="${x.i}">${esc(x.date.slice(5, 16))}</a>`).join(" ← ")}</div>` : ""}
    ${atts.length ? `<h3>קבצים מצורפים (${atts.length})</h3>` + atts.map((a) => `
      <div class="att">
        <a download="${esc(a.name)}" href="${a.uri}">${esc(a.name)}</a>
        <span style="color:var(--muted)"> · ${esc(a.type)} · ${fmtSize(a.size)}${a.inline ? " · מוטבע ב-HTML" : ""}</span>
        ${a.type.startsWith("image/") ? `<img src="${a.uri}" alt="">` : ""}
        ${a.type.startsWith("audio/") ? `<audio controls src="${a.uri}" style="display:block;margin-top:6px"></audio>` : ""}
        ${a.text ? `<pre dir="auto">${esc(a.text)}</pre>` : ""}
      </div>`).join("") : ""}
    <div class="tabs">
      <button data-t="body">גוף</button><button data-t="htmlsrc">מקור HTML</button>
      <button data-t="headers">כותרות וקידודים</button><button data-t="raw">מקור גולמי</button>
    </div>
    ${body}`;
  $("view").querySelectorAll(".tabs button").forEach((b) => {
    b.classList.toggle("on", b.dataset.t === tab);
    b.onclick = () => { tab = b.dataset.t; show(i); };
  });
  $("view").querySelectorAll(".thread a").forEach((a) => a.onclick = () => show(+a.dataset.i));
  renderList();
}

["q", "topic", "expect", "f-att", "f-html", "f-sent", "f-update", "sort"].forEach((id) =>
  $(id).addEventListener("input", renderList));
stats();
renderList();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
