"""
ניקוי גוף ההודעה לפני embedding.
כל הודעה בשרשור היא Node נפרד, ולכן מותר למחוק ציטוטים: ההודעה המצוטטת כבר באינדקס בעצמה.
- מוחק שורות שמתחילות ב-">".
- מוחק כותרות ציטוט ("On ... wrote:", "בתאריך ... מאת ...:", "בתאריך ... כתב:", Outlook).
  אחרי כותרת שאחריה שורות ">" ממשיכים לקרוא: מי שעונה מתחת לציטוט או בתוכו (bottom-posting / inline)
  כותב את התשובה בין שורות ה-">", והיא נשמרת. אחרי כותרת בסגנון Outlook (בלי ">") כל השאר נמחק.
- מוחק חתימות ("-- ", "נשלח מה-iPhone שלי").
- לא מוחק בלוק "Forwarded message", כי הוא תוכן. ממנו מחולץ השולח המקורי של מייל שהועבר.

הבעיה הקשה: ב-Outlook, ציטוט והעברה נראים אותו דבר (קו, ואחריו "מאת: ... נשלח: ...").
ההבחנה היא לפי הנושא: FW / Fwd / הועבר / העבר = העברה (תוכן), אחרת = ציטוט (נמחק).
"""
from dataclasses import dataclass, field
import re

# תווי כיווניות בלתי נראים. Gmail מכניס אותם לכותרות ציטוט בעברית, והם שוברים התאמת regex.
_BIDI = re.compile("[‎‏‪-‮⁦-⁩﻿]")
EMAIL_RE = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")

FORWARD_MARKER = re.compile(
    r"^-{3,}\s*(forwarded message|הודעה שהועברה|הודעה מועברת)\s*-{3,}$|^begin forwarded message:$", re.I)
FORWARD_SUBJECT = re.compile(r"^\s*(fwd?|הועבר|העבר)\s*:", re.I)
ORIGINAL_MESSAGE = re.compile(r"^-{2,}\s*(original message|הודעה מקורית)\s*-{2,}$", re.I)

# כותרות ציטוט שאחריהן בדרך כלל באות שורות ">"
QUOTE_HEADERS = [
    re.compile(r"^on\b.+\bwrote:$", re.I),                         # Gmail / Apple Mail באנגלית
    re.compile(r"^בתאריך\b.+\bמאת\b.+:$"),                         # Gmail בעברית
    re.compile(r"^בתאריך\b.+(כתב|כתבה|כתב/ה)\s*:$"),               # אפליקציות מובייל
]
OUTLOOK_RULE = re.compile(r"^_{8,}$")
OUTLOOK_FROM = re.compile(r"^(from|מאת)\s*:\s*\S", re.I)
OUTLOOK_SENT = re.compile(r"^(sent|נשלח|date|תאריך)\s*:", re.I)

MOBILE_SIGNATURE = re.compile(
    r"^(sent from (my |yahoo|outlook|aol|samsung|mail for).*|get outlook for .+|"
    r"נשלח מה-?\s?.+ שלי|נשלח מ.+ שלי|נשלח מהטלפון.*)$", re.I)


@dataclass
class CleanResult:
    text: str
    forwarded_from: list[tuple[str, str]] = field(default_factory=list)   # (שם, כתובת). כתובת "" אם לא ידועה
    removed_quote: bool = False


def _norm(line: str) -> str:
    return _BIDI.sub("", line).strip()


def _quote_header_span(lines: list[str], i: int) -> int:
    """אם בשורה i מתחילה כותרת ציטוט בסגנון Gmail: כמה שורות היא תופסת (Gmail שובר כותרת ארוכה עד 3 שורות).
    אחרת 0."""
    n = _norm(lines[i])
    if not n or n.startswith(">"):
        return 0
    joined = n
    for span in range(1, 4):
        if span > 1:
            if i + span - 1 >= len(lines):
                break
            joined += " " + _norm(lines[i + span - 1])
        if any(p.match(joined) for p in QUOTE_HEADERS):
            return span
    return 0


def _is_outlook_header(lines: list[str], i: int) -> bool:
    """קו תחתון ארוך ואחריו "מאת:", "-----Original Message-----", או "מאת:" ש"נשלח:" אחריו תוך שלוש שורות."""
    n = _norm(lines[i])
    if ORIGINAL_MESSAGE.match(n):
        return True
    following = [_norm(x) for x in lines[i + 1:i + 5] if _norm(x)]
    if OUTLOOK_RULE.match(n):
        return bool(following) and bool(OUTLOOK_FROM.match(following[0]))
    if OUTLOOK_FROM.match(n):
        return any(OUTLOOK_SENT.match(x) for x in following[:3])
    return False


def _parse_sender(value: str) -> tuple[str, str] | None:
    """'Name <a@b>' / 'Name [mailto:a@b]' / '<a@b>' / 'Name' -> (שם, כתובת)."""
    value = _norm(value)
    m = EMAIL_RE.search(value)
    addr = m.group(0).lower() if m else ""
    name = re.split(r"[<\[]", value)[0].strip().strip("\"'").strip()
    if name.lower() == addr:
        name = ""
    return (name, addr) if (name or addr) else None


def _quote_writer(header: str) -> tuple[str, str] | None:
    """הכותב מתוך כותרת ציטוט: "On <תאריך> Name <a@b> wrote:" / "בתאריך ... מאת Name <a@b>:" / "..., Name כתב:"."""
    h = _norm(header)
    m = EMAIL_RE.search(h)
    pre = h[:m.start()] if m else re.sub(r"\s*(wrote|כתב/ה|כתבה|כתב)\s*:$", "", h)
    name = re.split(r"\bמאת\b|\d{1,2}:\d{2}(?:\s*[AP]M)?|,", pre)[-1].strip(" <[\"'()")
    addr = m.group(0).lower() if m else ""
    return (name, addr) if (name or addr) else None


HEADER_FIELD = re.compile(r"^(subject|נושא|to|אל|cc|עותק)\s*:", re.I)


def _segments(block: list[str]) -> list[dict]:
    """בלוק העברה -> ההודעות שבו, בסדר שבו הן מופיעות (החדשה למעלה).
    גבול הודעה: סימון העברה / Original Message / קו Outlook, או כותרת ציטוט ("On ... wrote:").
    סימני ">" מוסרים: הייחוס עובר לתווית של כל הודעה."""
    lines = [re.sub(r"^\s*(?:>\s?)+", "", _BIDI.sub("", l)) for l in block]
    segs, cur, i = [], None, 0
    while i < len(lines):
        n = lines[i].strip()
        if FORWARD_MARKER.match(n) or ORIGINAL_MESSAGE.match(n) or OUTLOOK_RULE.match(n):
            cur = {"who": None, "date": "", "lines": [], "reply": False, "hdr": True}
            segs.append(cur)
            i += 1
            continue
        span = _quote_header_span(lines, i)
        if span:
            if cur:
                cur["reply"] = True   # ההודעה הנוכחית עונה לזו שמצוטטת מתחתיה
            header = _norm(" ".join(lines[i:i + span]))
            who = _quote_writer(header)
            cut = header.find(who[0]) if who and who[0] else -1   # התאריך: מה שבין "On"/"בתאריך" לבין השם
            date = re.sub(r"^(on|בתאריך)\s+|[\s,]*(מאת)?[\s,]*$", "", header[:cut] if cut > 0 else "", flags=re.I)
            cur = {"who": who, "date": date, "lines": [], "reply": False, "hdr": False}
            segs.append(cur)
            i += span
            continue
        if cur is None:
            cur = {"who": None, "date": "", "lines": [], "reply": False, "hdr": False}
            segs.append(cur)
        if cur["hdr"]:   # שורות "From / Date / Subject / To" שאחרי סימון ההעברה
            if OUTLOOK_FROM.match(n):
                cur["who"] = _parse_sender(n.split(":", 1)[1])
            elif OUTLOOK_SENT.match(n):
                cur["date"] = n.split(":", 1)[1].strip()
            elif n and not HEADER_FIELD.match(n):
                cur["hdr"] = False
            if cur["hdr"]:
                i += 1
                continue
        cur["lines"].append(lines[i].rstrip())
        i += 1
    return segs


def _who(sender: tuple[str, str] | None) -> str:
    return (sender[0] or sender[1]) if sender else "לא ידוע"


def _render_forward(segs: list[dict]) -> str:
    """כל הודעה עם תווית מפורשת: מי כתב, מתי, ולמי היא עונה.
    בסדר כרונולוגי (הישנה ראשונה), ולא כמו בציטוט: המודל קורא מלמעלה למטה כרצף של הצעה, תגובה, החלטה."""
    out = []
    for k, sg in enumerate(segs):
        label = [f"הודעה מועברת {len(segs) - k}", f"כתב/ה: {_who(sg['who'])}"] + ([sg["date"]] if sg["date"] else [])
        if sg["reply"] and k + 1 < len(segs):
            label.append(f"תגובה להודעה של {_who(segs[k + 1]['who'])}")
        out.append(f"[{' | '.join(label)}]\n{_collapse(sg['lines'])}")
    return "\n\n".join(reversed(out))


def _clean_own_part(lines: list[str], quoted: str = "") -> list[str]:
    """שורות ">" נמחקות. תשובה בין השורות מקבלת שורה מקוצרת של מה שהיא עונה עליו, כדי לא לאבד את ההקשר."""
    out, quote = [], []
    for line in lines:
        if line.rstrip("\r") in ("-- ", "--"):
            break   # מכאן חתימה עד סוף החלק של הכותב
        n = _norm(line)
        if n.startswith(">"):
            if n.lstrip("> ").strip():
                quote.append(n.lstrip("> ").strip())
            continue
        if MOBILE_SIGNATURE.match(n):
            continue
        if quote and n:
            text = " ".join(quote)
            out.append(f'[בתגובה ל{quoted and "-" + quoted}: "{text[:100]}{"..." if len(text) > 100 else ""}"]')
            quote = []
        out.append(line.rstrip())
    return out


def _collapse(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def _next_nonempty(lines: list[str], start: int) -> str:
    for line in lines[start:]:
        if _norm(line):
            return _norm(line)
    return ""


def clean_body(text: str, subject: str = "") -> CleanResult:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    is_forward = bool(FORWARD_SUBJECT.match(subject or ""))

    own, forward_block, removed_quote, quoted = [], [], False, ""
    i = 0
    while i < len(lines):
        n = _norm(lines[i])
        if FORWARD_MARKER.match(n) or (is_forward and _is_outlook_header(lines, i)):
            forward_block = lines[i:]
            break
        span = _quote_header_span(lines, i)
        if span:
            removed_quote = True
            if _next_nonempty(lines, i + span).startswith(">"):
                quoted = _who(_quote_writer(" ".join(lines[i:i + span])))
                i += span        # הציטוט עצמו (">") יימחק, ותשובה שבין השורות תישמר
                continue
            break                # כותרת בלי ">" אחריה: כל השאר הוא ההודעה הקודמת
        if _is_outlook_header(lines, i):
            removed_quote = True
            break
        own.append(lines[i])
        i += 1

    own_clean = _clean_own_part(own, quoted)
    if not forward_block:
        return CleanResult(_collapse(own_clean), [], removed_quote)
    # תוכן ההעברה הוא המידע עצמו: נשמר, מחולק להודעות עם תווית כותב לכל אחת
    segs = _segments(forward_block)
    senders = list(dict.fromkeys(sg["who"] for sg in segs if sg["who"]))
    return CleanResult(_collapse(own_clean + ["", _render_forward(segs)]), senders, removed_quote)
