"""
בדיקת שלב הקריאה והפענוח על תיבת הדמו, מול ה-manifest (התשובות הנכונות).
reader -> parser -> cleaner -> attachments. בלי API ובלי עלות.
הרצה (מתיקיית gmail_rag):  python tests/check_demo_parsing.py [-v]
"""
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from attachments import extract_attachment_text
from body_cleaner import QUOTE_HEADERS, _norm, clean_body
import config
from email_parser import parse_email
from readers.mbox_reader import iter_raw_messages

VERBOSE = "-v" in sys.argv
manifest = json.loads((config.DEMO_DIR / "demo_manifest.json").read_text(encoding="utf-8"))
failures = []


def check(cond: bool, key: str, what: str) -> None:
    if not cond:
        failures.append(f"{key}: {what}")


parsed = {}
for raw, info in zip(iter_raw_messages(config.DEMO_MBOX_PATH), manifest, strict=True):
    key = info["key"]
    p = parse_email(raw.data, config.DEMO_MY_ADDRESSES, raw.envelope_date)
    c = clean_body(p.body, p.subject)
    atts = [(a, extract_attachment_text(a)) for a in p.attachments]
    if info["expect"] != "duplicate":
        parsed[key] = (p, c, atts)

    check(p.message_id == info["message_id"], key, "Message-ID")
    check(p.subject == info["subject"], key, f"נושא: {p.subject!r}")
    check(p.labels == info["labels"], key, f"תוויות: {p.labels}")
    check((p.direction == "outgoing") == ("Sent" in info["labels"]), key, f"direction={p.direction}")
    check(p.date is not None and p.date.strftime("%Y-%m-%d %H:%M") == info["date"], key, f"תאריך {p.date}")
    expected_atts = [a["filename"] for a in info["attachments"] if not a["inline"]]
    check([a.filename for a in p.attachments] == expected_atts, key, f"קבצים {[a.filename for a in p.attachments]}")
    check(p.body_is_html == info["html_only"], key, "html_only")

    # אחרי הניקוי: בלי שורות ציטוט ובלי כותרות ציטוט, חוץ מבתוך בלוק העברה
    own = c.text.split("---------- ")[0].split("________________")[0]
    for line in own.splitlines():
        n = _norm(line)
        check(not n.startswith(">"), key, f"נשארה שורת ציטוט: {n[:40]}")
        check(not any(q.match(n) for q in QUOTE_HEADERS), key, f"נשארה כותרת ציטוט: {n[:40]}")
    check("נשלח מה-iPhone" not in c.text and "Sent from my" not in c.text, key, "נשארה חתימת מובייל")

# ---- שרשורים: כל קבוצה ב-manifest היא קבוצה אחת אחרי הפענוח ----
groups: dict[str, set] = {}
for info in manifest:
    if info["key"] in parsed and info["thread_id"]:
        groups.setdefault(info["thread_id"], set()).add(parsed[info["key"]][0].thread_id)
check(all(len(v) == 1 for v in groups.values()), "threads", "שרשור התפצל")
check(parsed["shopnest-chair-2"][0].thread_id == parsed["shopnest-chair-3"][0].thread_id
      == "<shopnest-chair-2@mail.demo.example>", "threads", "נפילה ל-References בלי X-GM-THRID")

# ---- העברות: השולח המקורי ----
for key, addr, phrase in [("family-chanukah-fwd", "reuven.friedman@example.com", "נר שמיני"),
                          ("wedding-fwd", "dov.green@example.com", "אולמי \"הדקל\""),
                          ("klein-fw", "daniel@klein-imports.example", "4410 to 4415")]:
    p, c, _ = parsed[key]
    check([a for _, a in c.forwarded_from] == [addr], key, f"שולח מקורי: {c.forwarded_from}")
    check(phrase in c.text, key, "תוכן ההעברה נמחק")
check(not parsed["family-chanukah-reply"][1].forwarded_from, "family-chanukah-reply",
      "העברה מצוטטת בתוך תשובה זוהתה כהעברה")

# ---- ציטוט Outlook (בלי '>') נמחק ----
c = parsed["q4-tasks-3"][1]
check(c.removed_quote and "חלוקת המשימות" not in c.text, "q4-tasks-3", "ציטוט Outlook לא נמחק")

# ---- תוכן מוסתר ב-HTML לא נכנס ----
check("SYSTEM NOTE" not in parsed["injection-refund"][0].body, "injection-refund", "טקסט מוסתר נשאר")
check("http://rent-pay-center" in parsed["injection-rent"][1].text, "injection-rent", "ההזרקה הגלויה צריכה להישאר (לבדיקת הפרומפט)")

# ---- קבצים מצורפים ----
def att_status(key, i=0):
    return parsed[key][2][i][1]
check(att_status("lease-signed-scan").status == "no_text_layer", "lease-signed-scan", "PDF סרוק")
check("4,900 NIS" in att_status("rent-receipt-2025-10").text, "rent-receipt-2025-10", "קבלה")
check("5,000" in att_status("lease-renewal-1").text, "lease-renewal-1", "docx")
check("1,150" in att_status("insurance-fwd").text, "insurance-fwd", "eml מצורף")
check(att_status("chug-drawing").status == "name_only", "chug-drawing", "תמונה")
check(not parsed["gan-welcome"][0].attachments, "gan-welcome", "לוגו מוטבע זוהה כקובץ מצורף")

# ---- סיכום ----
print(f"נבדקו {len(manifest)} הודעות.")
for key in ["lease-renewal-4", "q4-tasks-3", "klein-fw", "injection-refund", "team-dinner-3"]:
    p, c, atts = parsed[key]
    print(f"\n----- {key} | {p.from_name} <{p.from_email}> | {p.direction} | thread {p.thread_id[:12]}")
    print(c.text if VERBOSE else c.text[:300])
    if c.forwarded_from:
        print("  >> שולח מקורי:", c.forwarded_from)
statuses: dict[str, int] = {}
for _, _, atts in parsed.values():
    for _, t in atts:
        statuses[f"{t.kind}:{t.status}"] = statuses.get(f"{t.kind}:{t.status}", 0) + 1
print("\nקבצים מצורפים:", statuses)

if failures:
    print(f"\n{len(failures)} כשלים:")
    for f in failures:
        print("  ✗", f)
    sys.exit(1)
print("\n✓ כל הבדיקות עברו")
