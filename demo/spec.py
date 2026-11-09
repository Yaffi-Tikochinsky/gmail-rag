"""
מבני הנתונים של תיבת הדמו: איש קשר, מייל, קובץ מצורף.
וגם הפורמטים של כותרות ציטוט והעברה, כפי שתוכנות מייל שונות כותבות אותן.
המטרה: שהדמו ייראה כמו תיבה אמיתית, כדי שהמנקה (body_cleaner) ייבדק על כל הצורות.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TZ_IL = ZoneInfo("Asia/Jerusalem")


@dataclass(frozen=True)
class Person:
    name: str                       # שם תצוגה. "" = כתובת בלי שם
    addr: str
    sig: str = ""                   # חתימה שמתווספת בסוף המייל
    quote: str = "gmail_he"         # סגנון ציטוט כשהאדם עונה (ראה QUOTE_STYLES)
    encoding: str = "utf8-b64"      # קידוד הגוף כברירת מחדל (ראה generate_demo_mailbox.ENCODINGS)
    subject_charset: str = "utf-8"  # קידוד נושא ושמות לפי RFC2047


@dataclass
class Att:
    """קובץ מצורף. התוכן נוצר בזמן הבנייה לפי kind."""
    filename: str
    kind: str                # pdf | pdf_scan | docx | image | audio | video | ics | xlsx | zip | eml
    content: Any = None      # שורות טקסט / טבלה / מייל פנימי, לפי הסוג
    inline_cid: str = ""     # תמונה מוטבעת ב-HTML (cid:) ולא קובץ מצורף רגיל
    name_encoding: str = "rfc2047"   # שם קובץ בעברית: rfc2047 (כמו Gmail) או rfc2231


@dataclass
class Mail:
    key: str                          # מזהה קצר וייחודי. ממנו נבנה ה-Message-ID
    date: str                         # "2025-03-12 09:14", שעון ישראל
    frm: Person
    to: list[Person]
    subject: str
    body: str = ""                    # text/plain
    html: str = ""                    # text/html. רק html = מייל HTML בלבד; שניהם = alternative
    cc: list[Person] = field(default_factory=list)
    reply_to: str = ""                # key של ההודעה שעליה עונים (In-Reply-To, References, ציטוט)
    quote: str | None = None          # סגנון ציטוט. None = של השולח, "none" = בלי ציטוט
    labels: list[str] | None = None   # None = ברירת מחדל לפי כיוון
    attachments: list[Att] = field(default_factory=list)
    encoding: str | None = None
    sig: bool = True
    no_thrid: bool = False            # בלי X-GM-THRID, כדי לבדוק נפילה ל-References
    header_reply_to: Person | None = None   # כותרת Reply-To (רשימות תפוצה)
    expect: str = "indexed"           # indexed | excluded:label | excluded:date | excluded:blacklist | duplicate
    note: str = ""                    # מה המייל הזה בודק. נכנס ל-manifest


def parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ_IL)


# ---------- פורמטים של תאריך ----------
HE_DAYS_SHORT = ["יום ב׳", "יום ג׳", "יום ד׳", "יום ה׳", "יום ו׳", "שבת", "יום א׳"]
HE_DAYS_LONG = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "שבת", "יום ראשון"]
HE_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
EN_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _en_time(d: datetime) -> str:
    return d.strftime("%I:%M %p").lstrip("0")


def gmail_en_date(d: datetime) -> str:
    return f"{EN_DAYS[d.weekday()]}, {EN_MONTHS[d.month - 1]} {d.day}, {d.year} at {_en_time(d)}"


def gmail_he_date(d: datetime) -> str:
    return f"{HE_DAYS_SHORT[d.weekday()]}, {d.day} ב{HE_MONTHS[d.month - 1]} {d.year} ב-{d:%H:%M}"


def outlook_he_date(d: datetime) -> str:
    return f"{HE_DAYS_LONG[d.weekday()]} {d.day:02d} {HE_MONTHS[d.month - 1]} {d.year} {d:%H:%M}"


def _addr(p: Person) -> str:
    return f"{p.name} <{p.addr}>" if p.name else p.addr


# ---------- כותרות ציטוט (כשעונים למייל) ----------
# RLM (U+200F) ו-LRE/PDF מופיעים באמת בכותרות של Gmail בעברית. השארנו אותם בכוונה.
RLM, LRE, PDF = "‏", "‪", "‬"


def quote_block(style: str, parent: "Mail", parent_body: str) -> str:
    d = parse_date(parent.date)
    p = parent.frm
    prefixed = "\n".join(("> " + line) if line else ">" for line in parent_body.splitlines())
    if style == "gmail_en":
        return f"On {gmail_en_date(d)} {_addr(p)} wrote:\n{prefixed}"
    if style == "gmail_he":
        return f"בתאריך {gmail_he_date(d)} מאת {LRE}{p.name or p.addr}{PDF}{RLM} <{p.addr}>:\n{prefixed}"
    if style == "he_wrote":   # אפליקציות מובייל
        return f"בתאריך {d:%d.%m.%Y} {d:%H:%M}, {p.name or p.addr} כתב:\n{prefixed}"
    if style == "outlook_he":  # Outlook: בלי סימני ">", כל ההודעה הקודמת מתחת לקו
        to = "; ".join(x.name or x.addr for x in parent.to)
        return ("________________________________\n"
                f"מאת: {_addr(p)}\nנשלח: {outlook_he_date(d)}\nאל: {to}\nנושא: {parent.subject}\n\n"
                f"{parent_body}")
    if style == "outlook_en":
        to = "; ".join(x.name or x.addr for x in parent.to)
        return ("-----Original Message-----\n"
                f"From: {_addr(p)}\nSent: {d:%A, %B} {d.day}, {d.year} {_en_time(d)}\n"
                f"To: {to}\nSubject: {parent.subject}\n\n{parent_body}")
    raise ValueError(f"סגנון ציטוט לא מוכר: {style}")


# ---------- בלוקים של העברה (Forward) ----------
def forward_block(style: str, frm: Person, date: str, subject: str, to: list[Person], body: str) -> str:
    """בלוק "Forwarded message" כפי שהוא מופיע בגוף המייל המועבר. זה תוכן, ולא נמחק בניקוי."""
    d = parse_date(date)
    to_s = ", ".join(_addr(x) for x in to)
    if style == "gmail_en":
        return ("---------- Forwarded message ---------\n"
                f"From: {_addr(frm)}\nDate: {gmail_en_date(d)}\nSubject: {subject}\nTo: {to_s}\n\n{body}")
    if style == "gmail_he":
        return ("---------- הודעה שהועברה ---------\n"
                f"מאת: {LRE}{frm.name}{PDF} <{frm.addr}>\nתאריך: {gmail_he_date(d)}\n"
                f"נושא: {subject}\nאל: {to_s}\n\n{body}")
    if style == "outlook_he":
        return ("________________________________\n"
                f"מאת: {_addr(frm)}\nנשלח: {outlook_he_date(d)}\nאל: {to_s}\nנושא: {subject}\n\n{body}")
    raise ValueError(f"סגנון העברה לא מוכר: {style}")
