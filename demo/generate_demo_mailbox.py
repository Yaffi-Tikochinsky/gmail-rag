"""
יצירת תיבת הדמו הבדויה: data/demo/demo_mailbox.mbox, ולצידה demo_manifest.json.
הדמות: חני לוין, אישה חרדית, אמא לילדים קטנים, מנהלת חשבונות, שוכרת דירה (ראה people.py).

התיבה מחקה ייצוא Google Takeout: כותרות X-GM-THRID ו-X-Gmail-Labels, קידודים מעורבים
(UTF-8 / windows-1255, base64 / quoted-printable / 8bit, נושאים לפי RFC2047), ציטוטים בכמה סגנונות,
העברות, HTML בלבד, וקבצים מצורפים מסוגים שונים. היא עוברת בדיוק באותו קוד כמו תיבה אמיתית.

ה-manifest הוא "התשובות הנכונות": לכל מייל ה-Message-ID, מה הוא בודק, והאם הוא אמור להיות מאונדקס.
משמש לבדיקות ולקובץ שאלות ההערכה.

קבצים אמיתיים (תמונות, וידאו, אודיו): אם קיים קובץ בשם זהה ב-data/demo/assets/, הוא נכנס כמו שהוא.
אחרת נוצר קובץ חלופי קטן (תמונה צבעונית, צליל, וידאו ריק). בשלב 1 המערכת משתמשת רק בשם הקובץ
ובהקשר המייל, כך שהתוכן לא משנה. בשלב 2 (מודל ראייה) כדאי תמונות אמיתיות.

הרצה (מתיקיית gmail_rag):  python demo/generate_demo_mailbox.py
תלויות: רק הספרייה הסטנדרטית ו-python-docx (שכבר נמצאת ב-requirements).
"""
import hashlib
import io
import json
import mailbox
import math
import random
import struct
import sys
import zipfile
from email import charset as email_charset
from email import encoders
from email.charset import Charset
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import format_datetime, formataddr
from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from spec import Att, Mail, Person, parse_date, quote_block

import content_family
import content_home
import content_kids
import content_misc
import content_orders
import content_work

GMAIL_RAG_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = GMAIL_RAG_DIR / "data" / "demo"
ASSETS_DIR = OUT_DIR / "assets"
MBOX_PATH = OUT_DIR / "demo_mailbox.mbox"
MANIFEST_PATH = OUT_DIR / "demo_manifest.json"

OWNER_ADDR = "chani.levin@example.com"
MSGID_DOMAIN = "mail.demo.example"

# קידודי גוף: (charset, קידוד העברה)
ENCODINGS = {
    "utf8-b64": ("utf-8", email_charset.BASE64),
    "utf8-qp": ("utf-8", email_charset.QP),
    "utf8-8bit": ("utf-8", None),
    "cp1255-qp": ("windows-1255", email_charset.QP),
    "cp1255-b64": ("windows-1255", email_charset.BASE64),
}

MIME_BY_EXT = {
    ".jpg": ("image", "jpeg"), ".jpeg": ("image", "jpeg"), ".png": ("image", "png"),
    ".mp4": ("video", "mp4"), ".mov": ("video", "quicktime"),
    ".mp3": ("audio", "mpeg"), ".m4a": ("audio", "mp4"), ".wav": ("audio", "wav"),
    ".ogg": ("audio", "ogg"), ".opus": ("audio", "ogg"),
}


# =====================================================================
# יצירת קבצים מצורפים (בלי ספריות חיצוניות, חוץ מ-python-docx)
# =====================================================================

def _pdf_from_objects(objs: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def _pdf_page(stream: bytes, resources: bytes) -> bytes:
    return _pdf_from_objects([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources " + resources
        + b" /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ])


def make_pdf(lines: list[str]) -> bytes:
    """PDF עם שכבת טקסט (pypdf יחלץ אותו). אנגלית בלבד: ראה problems_log לגבי PDF בעברית."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    ops = ["BT", "/F1 11 Tf", "15 TL", "56 790 Td"]
    ops += [f"({esc(line)}) Tj T*" for line in lines]
    ops.append("ET")
    return _pdf_page("\n".join(ops).encode("latin-1"), b"<< /Font << /F1 5 0 R >> >>")


def make_scanned_pdf(seed: str) -> bytes:
    """PDF "סרוק": רק צורות שנראות כמו שורות טקסט, בלי שכבת טקסט בכלל."""
    r = random.Random(seed)
    ops = ["0.96 g 0 0 595 842 re f", "0.25 g"]
    y = 780
    while y > 120:
        if r.random() < 0.15:
            y -= 18
            continue
        width = r.randint(180, 480)
        ops.append(f"{539 - width} {y} {width} 7 re f")   # מיושר לימין, כמו מסמך בעברית
        y -= 16
    ops.append("0.4 g 70 90 140 40 re f")                  # "חתימה"
    return _pdf_page("\n".join(ops).encode("ascii"), b"<< >>")


def make_docx(paragraphs: list[str]) -> bytes:
    """docx בעברית, עם כיווניות מימין לשמאל. השורה הראשונה היא כותרת מודגשת."""
    from datetime import datetime
    from docx import Document
    from docx.oxml import OxmlElement

    doc = Document()
    doc.core_properties.author = ""
    doc.core_properties.created = datetime(2025, 1, 1)
    for i, text in enumerate(paragraphs):
        p = doc.add_paragraph()
        p._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
        run = p.add_run(text)
        run._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
        run.bold = i == 0
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_png(seed: str, w: int = 320, h: int = 240) -> bytes:
    """תמונה חלופית: רקע מדורג ועיגולים צבעוניים. כל seed נותן תמונה אחרת."""
    import zlib
    r = random.Random(seed)
    top = [r.randint(60, 230) for _ in range(3)]
    bottom = [r.randint(20, 200) for _ in range(3)]
    circles = [(r.randint(0, w), r.randint(0, h), r.randint(15, 70), [r.randint(0, 255) for _ in range(3)])
               for _ in range(r.randint(3, 7))]
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        t = y / h
        base = [int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)]
        row = [list(base) for _ in range(w)]
        for cx, cy, rad, col in circles:
            dy = y - cy
            if abs(dy) >= rad:
                continue
            half = int(math.sqrt(rad * rad - dy * dy))
            for x in range(max(0, cx - half), min(w, cx + half)):
                row[x] = col
        for px in row:
            raw += bytes(px)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def make_wav(seed: str, seconds: float = 2.0) -> bytes:
    """קובץ קול חלופי: כמה צלילים קצרים."""
    r = random.Random(seed)
    rate = 8000
    notes = [r.choice([262, 294, 330, 349, 392, 440, 494]) for _ in range(4)]
    n = int(rate * seconds)
    data = bytes(int(128 + 50 * math.sin(2 * math.pi * notes[int(i / n * len(notes))] * i / rate))
                 for i in range(n))
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8) + b"data" + struct.pack("<I", n) + data)


def make_mp4_placeholder() -> bytes:
    """וידאו חלופי: כותרת MP4 תקינה בלי תוכן. מספיק לשלב 1, שמשתמש רק בשם הקובץ."""
    note = b"demo placeholder - put a real video in data/demo/assets"
    return (struct.pack(">I", 24) + b"ftypisom" + struct.pack(">I", 512) + b"isomiso2"
            + struct.pack(">I", 8 + len(note)) + b"free" + note)


def make_xlsx(rows: list[list]) -> bytes:
    """גיליון xlsx מינימלי ותקין (zip של קבצי XML), עם תאים מסוג inlineStr."""
    def cell(ref: str, v) -> str:
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(str(v))}</t></is></c>'

    xml_rows = "".join(
        f'<row r="{ri}">' + "".join(cell(f"{chr(65 + ci)}{ri}", v) for ci, v in enumerate(row)) + "</row>"
        for ri, row in enumerate(rows, 1))
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    files = {
        "[Content_Types].xml": head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>",
        "_rels/.rels": head + f'<Relationships xmlns="{ns_pkg}"><Relationship Id="rId1" '
        f'Type="{ns_rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": head + f'<workbook xmlns="{ns_main}" xmlns:r="{ns_rel}"><sheets>'
        '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": head + f'<Relationships xmlns="{ns_pkg}"><Relationship Id="rId1" '
        f'Type="{ns_rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": head + f'<worksheet xmlns="{ns_main}"><sheetViews>'
        '<sheetView rightToLeft="1" workbookViewId="0"/></sheetViews>'
        f"<sheetData>{xml_rows}</sheetData></worksheet>",
    }
    return _zip(files)


def _zip(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))   # קבוע, כדי שהפלט יהיה זהה בכל הרצה
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


def make_ics(ev: dict) -> str:
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Demo//Calendar//HE", f"METHOD:{ev.get('method', 'REQUEST')}",
        "BEGIN:VEVENT", f"UID:{ev['uid']}", f"SEQUENCE:{ev.get('sequence', 0)}",
        f"DTSTART;TZID=Asia/Jerusalem:{ev['start']}", f"DTEND;TZID=Asia/Jerusalem:{ev['end']}",
        f"SUMMARY:{ev['summary']}", f"LOCATION:{ev.get('location', '')}",
        f"DESCRIPTION:{ev.get('description', '')}", f"ORGANIZER;CN={ev['organizer'].name}:mailto:{ev['organizer'].addr}",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


# =====================================================================
# בניית הודעות MIME
# =====================================================================

def text_part(text: str, subtype: str, encoding: str) -> MIMEText:
    charset_name, body_enc = ENCODINGS[encoding]
    try:
        text.encode(charset_name)
    except UnicodeEncodeError:
        # תווים שאין ב-windows-1255 (למשל סימני כיווניות מציטוט של Gmail): כמו תוכנות מייל אמיתיות, עוברים ל-UTF-8
        charset_name = "utf-8"
    cs = Charset(charset_name)
    cs.body_encoding = body_enc
    return MIMEText(text, subtype, cs)


def _set_filename(part: MIMEBase, att: Att, filename: str, disposition: str) -> None:
    if filename.isascii():
        part.add_header("Content-Disposition", disposition, filename=filename)
        part.set_param("name", filename)
    elif att.name_encoding == "rfc2231":
        part.add_header("Content-Disposition", disposition, filename=("utf-8", "", filename))
        part.set_param("name", ("utf-8", "", filename))
    else:   # rfc2047 בתוך מרכאות, כמו ש-Gmail שולח
        encoded = Header(filename, "utf-8").encode()
        part.add_header("Content-Disposition", disposition, filename=encoded)
        part.set_param("name", encoded)


def _asset(filename: str) -> bytes | None:
    p = ASSETS_DIR / filename
    return p.read_bytes() if p.exists() else None


def make_attachment(att: Att, build_inner) -> tuple[MIMEBase, str, bool]:
    """מחזיר (חלק MIME, שם הקובץ בפועל, האם זה קובץ חלופי)."""
    name, kind = att.filename, att.kind
    placeholder = False

    if kind == "pdf":
        part = MIMEApplication(make_pdf(att.content), "pdf")
    elif kind == "pdf_scan":
        part = MIMEApplication(make_scanned_pdf(name), "pdf")
    elif kind == "docx":
        part = MIMEApplication(make_docx(att.content),
                               "vnd.openxmlformats-officedocument.wordprocessingml.document")
    elif kind == "xlsx":
        part = MIMEApplication(make_xlsx(att.content),
                               "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    elif kind == "zip":
        part = MIMEApplication(_zip({n: make_png(n) for n in att.content}), "zip")
    elif kind == "ics":
        part = MIMEText(make_ics(att.content), "calendar", "utf-8")
        part.set_param("method", att.content.get("method", "REQUEST"))
    elif kind == "eml":
        part = MIMEMessage(build_inner(att.content))
    elif kind in ("image", "audio", "video"):
        data = _asset(name)
        if data is None:
            placeholder = True
            stem = Path(name).stem
            if kind == "image":
                data, name = make_png(name), stem + ".png"
            elif kind == "audio":
                data, name = make_wav(name), stem + ".wav"
            else:
                data = make_mp4_placeholder()
        maintype, subtype = MIME_BY_EXT.get(Path(name).suffix.lower(), ("application", "octet-stream"))
        part = MIMEBase(maintype, subtype)
        part.set_payload(data)
        encoders.encode_base64(part)
    else:
        raise ValueError(f"סוג קובץ לא מוכר: {kind}")

    if att.inline_cid:
        part.add_header("Content-ID", f"<{att.inline_cid}>")
        _set_filename(part, att, name, "inline")
    else:
        _set_filename(part, att, name, "attachment")
    return part, name, placeholder


def thread_id(root_key: str) -> str:
    """מספר בן 19 ספרות, כמו X-GM-THRID של Gmail."""
    h = int(hashlib.md5(root_key.encode()).hexdigest()[:16], 16)
    return str(1_000_000_000_000_000_000 + h % 8_000_000_000_000_000_000)


def message_id(key: str) -> str:
    return f"<{key}@{MSGID_DOMAIN}>"


def _addr_header(people: list[Person]) -> str:
    return ", ".join(formataddr((p.name, p.addr), charset=p.subject_charset) if p.name else p.addr
                     for p in people)


def _header(value: str, charset: str):
    return value if value.isascii() else Header(value, charset)


class Builder:
    def __init__(self):
        self.by_key: dict[str, Mail] = {}
        self.text_of: dict[str, str] = {}      # הגוף המלא של כל מייל, לציטוט מקונן בתשובות
        self.root_of: dict[str, str] = {}      # key -> key של ההודעה הראשונה בשרשור
        self.refs_of: dict[str, list[str]] = {}

    def full_text(self, m: Mail) -> str:
        parts = [m.body.strip("\n")]
        if m.sig and m.frm.sig:
            parts.append(m.frm.sig)
        text = "\n\n".join(p for p in parts if p)
        parent = self.by_key.get(m.reply_to)
        style = m.quote or m.frm.quote
        if parent and style != "none" and self.text_of.get(parent.key):
            text += "\n\n" + quote_block(style, parent, self.text_of[parent.key])
        return text

    def build(self, m: Mail, register: bool = True, gmail_headers: bool = True):
        if m.reply_to and m.reply_to not in self.by_key:
            raise ValueError(f"{m.key}: עונה ל-{m.reply_to}, שלא הוגדר לפניו")
        enc = m.encoding or m.frm.encoding
        text = self.full_text(m) if (m.body or not m.html) else ""
        html = m.html
        parent = self.by_key.get(m.reply_to)
        if html and parent and self.text_of.get(parent.key) and (m.quote or m.frm.quote) != "none":
            d = parse_date(parent.date)
            html += ('<div class="gmail_quote"><div dir="ltr" class="gmail_attr">'
                     f"On {d:%a, %b} {d.day}, {d.year} {escape(parent.frm.name)} &lt;{parent.frm.addr}&gt; wrote:<br></div>"
                     '<blockquote class="gmail_quote" style="margin:0 0 0 .8ex;border-left:1px #ccc solid;padding-left:1ex">'
                     + escape(self.text_of[parent.key]).replace("\n", "<br>") + "</blockquote></div>")

        inline = [a for a in m.attachments if a.inline_cid]
        regular = [a for a in m.attachments if not a.inline_cid]
        att_info = []

        def add_atts(container, atts):
            for a in atts:
                part, name, placeholder = make_attachment(a, lambda inner: self.build(inner, register=False, gmail_headers=False)[0])
                container.attach(part)
                att_info.append({"filename": name, "kind": a.kind, "inline": bool(a.inline_cid),
                                 "placeholder": placeholder})

        hpart = None
        if html:
            hpart = text_part(html, "html", enc)
            if inline:
                rel = MIMEMultipart("related")
                rel.attach(hpart)
                add_atts(rel, inline)
                hpart = rel
        if text and hpart:
            body = MIMEMultipart("alternative")
            body.attach(text_part(text, "plain", enc))
            body.attach(hpart)
        elif hpart:
            body = hpart
        else:
            body = text_part(text, "plain", enc)

        if regular:
            msg = MIMEMultipart("mixed")
            msg.attach(body)
            add_atts(msg, regular)
        else:
            msg = body

        # ---- שרשור ----
        if parent:
            root = self.root_of[parent.key]
            refs = self.refs_of[parent.key] + [message_id(parent.key)]
        else:
            root, refs = m.key, []

        # ---- תוויות ----
        labels = m.labels if m.labels is not None else (
            ["Sent"] if m.frm.addr == OWNER_ADDR else ["Inbox", "Opened", "Category Personal"])

        cs = m.frm.subject_charset
        if gmail_headers:   # רק בהודעות שבתיבה עצמה, לא במייל שמצורף כקובץ
            if not m.no_thrid:
                msg["X-GM-THRID"] = thread_id(root)
            msg["X-Gmail-Labels"] = _header(",".join(labels), "utf-8")
        msg["Message-ID"] = message_id(m.key)
        msg["Date"] = format_datetime(parse_date(m.date))
        msg["From"] = _addr_header([m.frm])
        msg["To"] = _addr_header(m.to)
        if m.cc:
            msg["Cc"] = _addr_header(m.cc)
        if m.header_reply_to:
            msg["Reply-To"] = _addr_header([m.header_reply_to])
        msg["Subject"] = _header(m.subject, cs)
        if parent:
            msg["In-Reply-To"] = message_id(parent.key)
            msg["References"] = " ".join(refs)
        if "MIME-Version" not in msg:
            msg["MIME-Version"] = "1.0"

        if register:
            self.by_key[m.key] = m
            self.text_of[m.key] = text
            self.root_of[m.key] = root
            self.refs_of[m.key] = refs
        return msg, {
            "key": m.key,
            "message_id": message_id(m.key),
            "thread_id": None if m.no_thrid else thread_id(root),
            "date": m.date,
            "from": f"{m.frm.name} <{m.frm.addr}>" if m.frm.name else m.frm.addr,
            "to": [p.addr for p in m.to],
            "subject": m.subject,
            "labels": labels,
            "html_only": bool(html) and not text,
            "attachments": att_info,
            "expect": m.expect,
            "note": m.note,
        }


TOPICS = [(content_home, "דירה"), (content_work, "עבודה"), (content_kids, "ילדים"),
          (content_family, "משפחה"), (content_orders, "הזמנות ומנויים"), (content_misc, "קהילה והגנות")]


def all_mails() -> list[tuple[str, Mail]]:
    return [(topic, m) for module, topic in TOPICS for m in module.MAILS]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if MBOX_PATH.exists():
        MBOX_PATH.unlink()

    builder = Builder()
    manifest, seen = [], set()
    box = mailbox.mbox(str(MBOX_PATH), create=True)
    try:
        for topic, m in all_mails():
            if m.key in seen:
                # אותו אובייקט פעמיים ברשימה = כפילות מכוונת, עם אותו Message-ID
                msg, info = builder.build(m, register=False)
                info["expect"] = "duplicate"
                info["note"] = "עותק כפול של אותה הודעה (אותו Message-ID). אסור שייכנס פעמיים."
            else:
                msg, info = builder.build(m)
                seen.add(m.key)
            mbox_msg = mailbox.mboxMessage(msg)
            mbox_msg.set_from(f"{info['thread_id'] or '0'}@xxx", parse_date(m.date).utctimetuple())
            box.add(mbox_msg)
            info["topic"] = topic
            manifest.append(info)
    finally:
        box.close()

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    counts: dict[str, int] = {}
    for item in manifest:
        counts[item["expect"]] = counts.get(item["expect"], 0) + 1
    print(f"נכתבו {len(manifest)} הודעות אל {MBOX_PATH.relative_to(GMAIL_RAG_DIR)}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    n_att = sum(len(i["attachments"]) for i in manifest)
    n_ph = sum(a["placeholder"] for i in manifest for a in i["attachments"])
    print(f"  קבצים מצורפים: {n_att} (מהם {n_ph} קבצים חלופיים)")


if __name__ == "__main__":
    sys.exit(main())
