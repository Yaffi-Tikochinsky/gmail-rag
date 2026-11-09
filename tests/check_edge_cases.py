"""
מקרי קצה שלא מופיעים בתיבת הדמו: מיילים קטנים שנבנים כאן ישירות כ-bytes.
כל מקרה מתאר מצב אמיתי שעלול להופיע בתיבה אמיתית, ומה התוצאה הנכונה.
הרצה (מתיקיית gmail_rag):  python tests/check_edge_cases.py
"""
import base64
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from attachments import attachment_kind
from body_cleaner import clean_body
import config
from email_parser import parse_email
from readers.mbox_reader import iter_raw_messages

results = []


def case(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def mail(headers: str, body: str | bytes, ctype: str = "text/plain; charset=utf-8") -> bytes:
    head = "From: Test <t@example.com>\nTo: me@example.com\nSubject: test\nDate: Mon, 05 Jan 2026 10:00:00 +0200\n"
    head += "Message-ID: <x@example.com>\nMIME-Version: 1.0\n" + (f"Content-Type: {ctype}\n" if ctype else "") + headers
    body_b = body if isinstance(body, bytes) else body.encode("utf-8")
    return head.encode("utf-8") + b"\n" + body_b


def mixed(*parts: str, boundary: str = "BND") -> tuple[str, str]:
    body = "".join(f"--{boundary}\n{p}\n" for p in parts) + f"--{boundary}--\n"
    return body, f'multipart/mixed; boundary="{boundary}"'


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ---------------------------------------------------------------- HTML
html = ('<div style="display:none"><p>SECRET one<p>SECRET two<li>SECRET three</div>'
        '<p>visible text after the hidden block</p>')
p = parse_email(mail("", html, "text/html; charset=utf-8"))
case("HTML מוסתר עם תגיות לא סגורות", "visible text after" in p.body and "SECRET" not in p.body, p.body[:80])

html = "<html><head><style>.x{color:red}</style><title>t</title></head><body><p>hello</p></body></html>"
p = parse_email(mail("", html, "text/html; charset=utf-8"))
case("תוכן <style> לא נכנס לטקסט", "color:red" not in p.body and "hello" in p.body, p.body[:80])

body, ct = mixed("Content-Type: text/plain; charset=utf-8\n\nThis message requires an HTML-capable mail client.",
                 "Content-Type: text/html; charset=utf-8\n\n<p>" + "תוכן אמיתי של ההזמנה. " * 20 + "</p>")
p = parse_email(mail("", body, ct.replace("mixed", "alternative")))
case("טקסט 'אין תמיכה ב-HTML' מול HTML מלא", "תוכן אמיתי" in p.body, p.body[:60])

# ---------------------------------------------------------------- ציטוטים
c = clean_body("On Mon, Jan 5, 2026 at 10:00 AM Sara <s@example.com> wrote:\n> what time?\n\nmy answer: 5pm")
case("תשובה מתחת לציטוט: נשמרת, עם מה שנענה", c.text == '[בתגובה ל-Sara: "what time?"]\nmy answer: 5pm', repr(c.text))

c = clean_body("On Mon, Jan 5, 2026 at 10:00 AM Sara <s@example.com> wrote:\n> q1?\nanswer one\n> q2?\nanswer two")
case("תשובות בתוך הציטוט: כל אחת עם מה שהיא עונה עליו",
     c.text == '[בתגובה ל-Sara: "q1?"]\nanswer one\n[בתגובה ל-Sara: "q2?"]\nanswer two',
     repr(c.text))

c = clean_body("fyi\n\n---------- Forwarded message ---------\nFrom: Leah <l@example.com>\nDate: Mon, Dec 1, 2025\n"
               "Subject: Re: gift\n\nwatch!\n\nOn Sun, Nov 30, 2025 at 8:00 PM Dan <d@example.com> wrote:\n> idea?\n>\n"
               "> On Sat, Nov 29, 2025 at 9:00 AM Ron <r@example.com> wrote:\n>> gift for mom", "Fwd: gift")
case("העברה של שרשור: לפי סדר, עם תווית כותב לכל הודעה ולמי היא עונה",
     "[הודעה מועברת 3 | כתב/ה: Leah | Mon, Dec 1, 2025 | תגובה להודעה של Dan]\nwatch!" in c.text
     and "[הודעה מועברת 2 | כתב/ה: Dan | Sun, Nov 30, 2025 at 8:00 PM | תגובה להודעה של Ron]\nidea?" in c.text
     and "[הודעה מועברת 1 | כתב/ה: Ron | Sat, Nov 29, 2025 at 9:00 AM]\ngift for mom" in c.text
     and c.text.index("Ron") < c.text.index("Dan |") < c.text.index("Leah |")
     and [a for _, a in c.forwarded_from] == ["l@example.com", "d@example.com", "r@example.com"], repr(c.text))

c = clean_body("ok thanks\n\nOn Tue, Mar 4, 2025 at 10:12 AM Some Very Long Display Name <\n"
               "very.long.address.for.test@example.com>\nwrote:\n> old text")
case("כותרת ציטוט ששבורה ל-3 שורות", c.text == "ok thanks", repr(c.text))

c = clean_body("reply\n\n-----Original Message-----\nFrom: x\nSent: y\n\nold text without quote marks")
case("Original Message בלי '>'", c.text == "reply", repr(c.text))

c = clean_body("see you\n\nSent from Yahoo Mail on Android")
case("חתימת Yahoo", c.text == "see you", repr(c.text))

# ---------------------------------------------------------------- העברות
c = clean_body("FYI\n\n________________________________\nFrom: Daniel Klein\nSent: Monday, March 2, 2026 9:00 AM\n"
               "To: Miriam\nSubject: invoices\n\ncontent", "FW: invoices")
case("העברת Outlook בלי כתובת מייל", c.forwarded_from == [("Daniel Klein", "")], str(c.forwarded_from))

c = clean_body("FYI\n\n-----Original Message-----\nFrom: Daniel Klein [mailto:daniel@klein.example]\n"
               "Sent: Monday, March 2, 2026 9:00 AM\nSubject: invoices\n\ncontent", "FW: invoices")
case("העברת Outlook בפורמט [mailto:]", c.forwarded_from == [("Daniel Klein", "daniel@klein.example")]
     and "content" in c.text, f"{c.forwarded_from} | {c.text[-20:]!r}")

c = clean_body("FYI\n\n---------- Forwarded message ---------\nFrom: <reuven@example.com>\nDate: x\n\ncontent")
case("העברה עם כתובת בלי שם", c.forwarded_from == [("", "reuven@example.com")], str(c.forwarded_from))

# ---------------------------------------------------------------- קידודים
p = parse_email(mail("", "שלום עולם".encode("utf-8"), "text/plain; charset=windows-1255"))
case("charset מוצהר windows-1255 אבל הגוף UTF-8", p.body == "שלום עולם", repr(p.body))

p = parse_email(mail("", "שלום עולם".encode("cp1255"), "text/plain; charset=utf-8"))
case("charset מוצהר UTF-8 אבל הגוף windows-1255", p.body == "שלום עולם", repr(p.body))

subj = "=?iso-8859-8-i?B?" + b64("שלום".encode("iso-8859-8")) + "?="
p = parse_email(mail("", "x").replace(b"Subject: test", f"Subject: {subj}".encode()))
case("נושא בקידוד iso-8859-8-i", p.subject == "שלום", repr(p.subject))

p = parse_email(mail("", "x").replace(b"Subject: test", b"Subject: " + "שלום".encode("cp1255")))
case("נושא בעברית בלי קידוד (8bit גולמי)", p.subject == "שלום", repr(p.subject))

p = parse_email(mail("", "x").replace(b"From: Test <t@example.com>",
                                      b"From: " + "משה".encode("cp1255") + b" <m@example.com>"))
case("שם שולח בעברית בלי קידוד", p.from_name == "משה", repr(p.from_name))

# ---------------------------------------------------------------- תאריכים
p = parse_email(mail("", "x").replace(b"Mon, 05 Jan 2026 10:00:00 +0200", b"5 Jan 2026 10:00:00"))
case("תאריך בלי אזור זמן", p.date is not None and p.date.tzinfo is not None, str(p.date))

with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "t.mbox"
    raw = mail("", "x").replace(b"Date: Mon, 05 Jan 2026 10:00:00 +0200\n", b"")
    path.write_bytes(b"From 123@xxx Wed Mar 12 07:14:00 +0000 2025\n" + raw + b"\n")
    msgs = list(iter_raw_messages(path))
    p = parse_email(msgs[0].data, fallback_date=msgs[0].envelope_date) if hasattr(msgs[0], "data") else None
    case("בלי כותרת Date: תאריך משורת ה-From של mbox",
         p is not None and p.date == datetime(2025, 3, 12, 7, 14, tzinfo=timezone.utc), str(p and p.date))

# ---------------------------------------------------------------- קבצים מצורפים
pdf_part = f"Content-Type: application/pdf\nContent-Disposition: attachment; filename=\"invoice\"\nContent-Transfer-Encoding: base64\n\n{b64(b'%PDF-1.4 x')}"
sig_part = "Content-Type: application/pkcs7-signature; name=smime.p7s\nContent-Disposition: attachment; filename=smime.p7s\nContent-Transfer-Encoding: base64\n\nAAAA"
empty_part = "Content-Type: application/octet-stream\nContent-Disposition: attachment; filename=empty.bin\n\n"
long_name = "חשבונית מס קבלה מספר 12345 עבור שירותי אחזקה לחודש מרץ.pdf"
enc = "".join(f"%{b:02X}" for b in long_name.encode("utf-8"))
cont_part = (f"Content-Type: application/pdf\nContent-Disposition: attachment;\n filename*0*=utf-8''{enc[:90]};\n"
             f" filename*1*={enc[90:]}\nContent-Transfer-Encoding: base64\n\n{b64(b'%PDF-1.4 x')}")
body, ct = mixed("Content-Type: text/plain; charset=utf-8\n\nsee attached", pdf_part, sig_part, empty_part, cont_part)
p = parse_email(mail("", body, ct))
names = [a.filename for a in p.attachments]
case("PDF בלי סיומת מזוהה לפי Content-Type", bool(p.attachments) and attachment_kind(p.attachments[0]) == "pdf",
     str([(a.filename, attachment_kind(a)) for a in p.attachments]))
case("חתימה דיגיטלית (smime.p7s) לא נחשבת קובץ מצורף", "smime.p7s" not in names, str(names))
case("קובץ מצורף ריק מדולג", "empty.bin" not in names, str(names))
case("שם קובץ ארוך בעברית ב-RFC2231 מפוצל", long_name in names, str(names))

# ---------------------------------------------------------------- תוויות
p = parse_email(mail('X-Gmail-Labels: Inbox,"Work, 2025",Opened\n', "x"))
case("תווית עם פסיק בתוך מרכאות", p.labels == ["Inbox", "Work, 2025", "Opened"], str(p.labels))
case("טיוטות (Draft) מוחרגות", "Draft" in config.EXCLUDED_LABELS, str(config.EXCLUDED_LABELS))

# ---------------------------------------------------------------- סיכום
width = max(len(n) for n, _, _ in results)
for name, ok, detail in results:
    print(f"{'✓' if ok else '✗'} {name.ljust(width)}  {'' if ok else detail}")
failed = sum(not ok for _, ok, _ in results)
print(f"\n{len(results) - failed}/{len(results)} עברו")
sys.exit(1 if failed else 0)
