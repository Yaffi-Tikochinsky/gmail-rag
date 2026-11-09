"""
מפענח הודעת RFC822 גולמית למבנה אחיד (ParsedEmail): שדות, גוף, וקבצים מצורפים.
לא יודע מאיפה ההודעה הגיעה (mbox או Gmail API).
- פענוח כותרות מקודדות לפי RFC2047 (נושא ושמות בעברית), כולל charsets שפייתון לא מכיר
  (iso-8859-8-i) וכותרות בעברית בלי קידוד בכלל (8bit גולמי, ממיילרים ישנים).
- פענוח הגוף: base64, quoted-printable, ו-charsets כמו windows-1255, עם נפילה לקידודים אחרים אם ה-charset שגוי.
- העדפת text/plain. אם יש רק HTML (או שה-text/plain הוא רק "אין תמיכה ב-HTML"), המרה לטקסט עם html2text,
  אחרי הסרת תוכן מוסתר.
- חילוץ Message-ID, תאריך, שולח, נמענים, תוויות (X-Gmail-Labels) ו-thread_id (X-GM-THRID או References).
- קביעת direction (נכנס/יוצא) לפי התווית Sent והכתובות של בעל התיבה (מ-mailbox.json).
הניקוי (ציטוטים, חתימות) נעשה ב-body_cleaner.py, ולא כאן.
"""
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.header import decode_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
import hashlib
from html import escape
from html.parser import HTMLParser
import re

import html2text

import config

# כינויים של charsets שפייתון לא מכיר, או שמופיעים במיילים ישראליים בשם לא תקני
CHARSET_ALIASES = {
    "iso-8859-8-i": "iso-8859-8",
    "iso-8859-8-e": "iso-8859-8",
    "visual": "iso-8859-8",
    "logical": "iso-8859-8",
    "x-mac-hebrew": "cp1255",
    "unicode-1-1-utf-7": "utf-7",
}
# סדר הניסיון כשה-charset המוצהר נכשל
FALLBACK_CHARSETS = ["cp1255", "iso-8859-8"]

# חלקים שהם לא תוכן: חתימות דיגיטליות ומפתחות הצפנה
NON_CONTENT_TYPES = {
    "application/pkcs7-signature", "application/x-pkcs7-signature",
    "application/pgp-signature", "application/pgp-keys",
}
# text/plain קצר מזה, כשיש גם HTML ארוך בהרבה, הוא כנראה רק "תוכנת המייל שלך לא תומכת ב-HTML"
PLAIN_STUB_MAX_CHARS = 120


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class ParsedEmail:
    message_id: str
    thread_id: str
    date: datetime | None               # תמיד עם אזור זמן (או None)
    subject: str
    from_name: str
    from_email: str
    to: list[tuple[str, str]]           # (שם, כתובת)
    cc: list[tuple[str, str]]
    labels: list[str]
    direction: str                      # "incoming" או "outgoing"
    body: str                           # הגוף המפוענח, לפני ניקוי ציטוטים
    body_is_html: bool                  # הגוף הומר מ-HTML
    attachments: list[Attachment] = field(default_factory=list)
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)

    @property
    def date_int(self) -> int:
        """תאריך כמספר YYYYMMDD, בשביל metadata ופילטרים של Chroma. 0 אם אין תאריך."""
        return int(self.date.strftime("%Y%m%d")) if self.date else 0


# ---------------------------------------------------------------- קידודים

def decode_bytes(data: bytes, declared: str | None) -> str:
    """פענוח bytes לטקסט.
    קודם UTF-8 תקין: רצף UTF-8 תקין עם עברית כמעט אף פעם לא נוצר במקרה מטקסט windows-1255,
    ולכן אם הוא מצליח, ה-charset המוצהר כנראה שגוי. אחר כך ה-charset המוצהר, ואז קידודים נפוצים בעברית."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    tried = []
    if declared:
        declared = declared.lower().strip()
        tried.append(CHARSET_ALIASES.get(declared, declared))
    tried += [c for c in FALLBACK_CHARSETS if c not in tried]
    for cs in tried:
        try:
            return data.decode(cs)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def decode_words(value: str) -> str:
    """ערך כותרת גולמי -> טקסט: מילים מקודדות (RFC2047) ובתים גולמיים בעברית."""
    if any("\udc80" <= ch <= "\udcff" for ch in value):
        # בתים שאינם ASCII בכותרת בלי קידוד: פייתון שומר אותם כ-surrogates. מפענחים בעצמנו.
        value = decode_bytes(value.encode("ascii", "surrogateescape"), None)
    if "=?" not in value:
        return value
    try:
        chunks = decode_header(value)
    except Exception:
        return value
    out = []
    for chunk, charset in chunks:
        out.append(decode_bytes(chunk, charset) if isinstance(chunk, bytes) else chunk)
    return "".join(out)


# ---------------------------------------------------------------- כותרות

def _raw_header(msg: EmailMessage, name: str) -> str:
    """הערך הגולמי של הכותרת, לפני שפייתון מפענח אותו (הוא מחליף charsets לא מוכרים ב-�)."""
    for k, v in msg.raw_items():
        if k.lower() == name.lower():
            return str(v)
    return ""


def _header(msg: EmailMessage, name: str) -> str:
    return " ".join(decode_words(_raw_header(msg, name)).split())


def _addresses(msg: EmailMessage, name: str) -> list[tuple[str, str]]:
    raw = _raw_header(msg, name)
    if not raw:
        return []
    if any("\udc80" <= ch <= "\udcff" for ch in raw):
        raw = decode_words(raw)
    # מפרקים לכתובות לפני פענוח השמות: שם מקודד יכול להכיל פסיק ("כהן, משה")
    return [(" ".join(decode_words(n).split()), a.strip().lower())
            for n, a in getaddresses([" ".join(raw.split())]) if a]


def _parse_labels(raw: str) -> list[str]:
    # X-Gmail-Labels: Inbox,Opened,"Label, with comma"
    if not raw:
        return []
    row = next(csv.reader([raw], skipinitialspace=True), [])
    return [label.strip() for label in row if label.strip()]


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        d = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    # תאריך בלי אזור זמן: מניחים UTC, כדי שכל התאריכים יהיו ברי השוואה
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _msgid_list(raw: str) -> list[str]:
    return re.findall(r"<[^<>\s]+>", raw)


# ---------------------------------------------------------------- גוף

def _part_text(part: EmailMessage) -> str:
    data = part.get_payload(decode=True) or b""
    return decode_bytes(data, part.get_content_charset())


class _HiddenContentFilter(HTMLParser):
    """מסיר אלמנטים מוסתרים (display:none וכו'). המשתמש לא רואה אותם, ולכן הם לא אמורים להיכנס לאינדקס.
    זו שכבת הגנה נוספת מפני prompt injection שמוסתר ב-HTML.
    סופרים רק תגיות מאותו סוג כמו התגית המוסתרת: ב-HTML אמיתי יש הרבה <p> ו-<li> לא סגורים,
    וספירה של כל התגיות הייתה "בולעת" את כל שאר המייל."""
    HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d])|"
                              r"max-height\s*:\s*0(?![.\d])|opacity\s*:\s*0(?![.\d])", re.I)
    VOID = {"br", "img", "hr", "meta", "link", "input", "area", "base", "col", "wbr", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.hidden_tag = ""     # התגית שפתחה את האזור המוסתר
        self.hidden_count = 0    # כמה תגיות פתוחות מאותו סוג בתוך האזור

    def _is_hidden(self, attrs) -> bool:
        d = {k.lower(): (v or "") for k, v in attrs}
        return "hidden" in d or bool(self.HIDDEN_STYLE.search(d.get("style", "")))

    def handle_starttag(self, tag, attrs):
        if self.hidden_tag:
            if tag == self.hidden_tag:
                self.hidden_count += 1
            return
        if tag not in self.VOID and self._is_hidden(attrs):
            self.hidden_tag, self.hidden_count = tag, 1
            return
        self.out.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag, attrs):
        if not self.hidden_tag:
            self.out.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if self.hidden_tag:
            if tag == self.hidden_tag:
                self.hidden_count -= 1
                if self.hidden_count == 0:
                    self.hidden_tag = ""
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.hidden_tag:
            self.out.append(escape(data, quote=False))


def html_to_text(html: str) -> str:
    f = _HiddenContentFilter()
    try:
        f.feed(html)
        f.close()
        html = "".join(f.out)
    except Exception:
        pass   # HTML שבור: ממירים את המקור כמו שהוא
    h = html2text.HTML2Text()
    h.body_width = 0           # בלי שבירת שורות מלאכותית
    h.ignore_images = True
    h.ignore_links = True      # כתובות URL הן רעש ל-embedding, וממילא לא מציעים לפתוח קישורים
    h.ignore_emphasis = True
    h.unicode_snob = True      # להשאיר תווי Unicode כמו שהם
    return h.handle(html).strip()


def _walk_leaves(part: EmailMessage):
    """כל החלקים שאינם multipart. לא נכנס לתוך מייל מצורף (message/rfc822): הוא קובץ מצורף שלם."""
    if part.get_content_type() == "message/rfc822":
        yield part
    elif part.is_multipart():
        for sub in part.iter_parts():
            yield from _walk_leaves(sub)
    else:
        yield part


def _filename(part: EmailMessage) -> str:
    try:
        name = part.get_filename() or ""
    except Exception:
        name = ""
    return decode_words(name).strip()   # גם RFC2047 בתוך מרכאות, כמו ש-Gmail שולח


def _extract_body_and_attachments(msg: EmailMessage) -> tuple[str, bool, list[Attachment]]:
    plain_parts, html_parts, attachments, seen = [], [], [], set()
    leaves = list(_walk_leaves(msg))

    # Content-ID של תמונות שה-HTML מציג בעצמו (cid:). הן חלק מהעיצוב, לא קבצים מצורפים.
    html_sources = " ".join(_part_text(p) for p in leaves
                            if p.get_content_type() == "text/html" and not _filename(p))
    referenced_cids = set(re.findall(r"cid:([^\"'\s>)]+)", html_sources))

    for part in leaves:
        ctype = part.get_content_type()
        disposition = part.get_content_disposition()
        name = _filename(part)

        if ctype == "message/rfc822":
            inner = part.get_payload(0) if part.is_multipart() else None
            data = inner.as_bytes() if inner is not None else (part.get_payload(decode=True) or b"")
            attachments.append(Attachment(name or "forwarded.eml", ctype, data))
            continue
        if ctype in ("text/plain", "text/html") and disposition != "attachment" and not name:
            (plain_parts if ctype == "text/plain" else html_parts).append(_part_text(part))
            continue
        if ctype in NON_CONTENT_TYPES:
            continue
        cid = (part.get("Content-ID") or "").strip().strip("<>")
        if cid and cid in referenced_cids:
            continue
        if not name and disposition != "attachment":
            continue   # חלק בלי שם שאינו גוף, למשל תמונה מוטבעת בלי Content-ID
        data = part.get_payload(decode=True) or b""
        fingerprint = (name, hashlib.sha1(data).hexdigest())
        if not data or fingerprint in seen:
            continue   # קובץ ריק, או אותו קובץ פעמיים באותו מייל
        seen.add(fingerprint)
        attachments.append(Attachment(name or "attachment", ctype, data))

    plain = "\n\n".join(p.strip() for p in plain_parts if p.strip())
    html_text = "\n\n".join(html_to_text(h) for h in html_parts) if html_parts else ""
    if plain and not (len(plain) <= PLAIN_STUB_MAX_CHARS and len(html_text) > 3 * len(plain)):
        return plain, False, attachments
    if html_text:
        return html_text, True, attachments
    return plain, False, attachments


# ---------------------------------------------------------------- ראשי

def parse_email(raw: bytes, my_addresses: list[str] | tuple[str, ...] = (),
                fallback_date: datetime | None = None) -> ParsedEmail:
    """fallback_date: תאריך מהקורא (למשל שורת ה-From של mbox), למייל בלי כותרת Date תקינה."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    message_id = (_msgid_list(_header(msg, "Message-ID")) or [_header(msg, "Message-ID")])[0]
    if not message_id:
        # בלי Message-ID אין זיהוי לעדכון אינקרמנטלי. מזהה יציב מתוכן ההודעה.
        message_id = f"<generated-{hashlib.sha1(raw).hexdigest()}@gmail-rag.local>"

    references = _msgid_list(_header(msg, "References"))
    in_reply_to = (_msgid_list(_header(msg, "In-Reply-To")) or [""])[0]
    thread_id = _header(msg, "X-GM-THRID") or (references[0] if references else in_reply_to) or message_id

    from_list = _addresses(msg, "From")
    from_name, from_email = from_list[0] if from_list else ("", "")
    labels = _parse_labels(_header(msg, "X-Gmail-Labels"))
    mine = {a.lower() for a in my_addresses}
    direction = "outgoing" if (config.SENT_LABEL in labels or from_email in mine) else "incoming"

    body, is_html, attachments = _extract_body_and_attachments(msg)
    return ParsedEmail(
        message_id=message_id,
        thread_id=thread_id,
        date=_parse_date(_header(msg, "Date")) or fallback_date,
        subject=_header(msg, "Subject"),
        from_name=from_name,
        from_email=from_email,
        to=_addresses(msg, "To"),
        cc=_addresses(msg, "Cc"),
        labels=labels,
        direction=direction,
        body=body,
        body_is_html=is_html,
        attachments=attachments,
        in_reply_to=in_reply_to,
        references=references,
    )
