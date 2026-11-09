"""
קורא mbox, עם המודול המובנה mailbox.
משרת גם את תיבת הדמו וגם ייצוא Google Takeout של התיבה האמיתית.
מחזיר הודעות גולמיות (bytes) אחת-אחת (generator), כדי לא לטעון תיבה גדולה לזיכרון.
הקורא לא מפענח את ההודעה: זה התפקיד של email_parser.py.
הוא כן מעביר את התאריך משורת ה-"From " של mbox, כגיבוי למייל בלי כותרת Date תקינה.
"""
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import mailbox
from pathlib import Path
import re


@dataclass
class RawMessage:
    data: bytes                       # ההודעה המלאה (RFC822)
    envelope_date: datetime | None    # תאריך מהמעטפה (שורת From של mbox). גם קורא Gmail API יספק תאריך כזה


def _envelope_date(from_line: str) -> datetime | None:
    # Takeout:  "From 1786543210987654321@xxx Wed Mar 12 07:14:00 +0000 2025"
    # mbox רגיל: "From MAILER-DAEMON Wed Mar 12 07:14:00 2025"
    tokens = from_line.split()[1:]   # בלי "From" ובלי השולח
    tz = timezone.utc
    rest = []
    for tok in tokens[1:]:
        m = re.fullmatch(r"([+-])(\d{2})(\d{2})", tok)
        if m:
            sign = 1 if m.group(1) == "+" else -1
            tz = timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
        else:
            rest.append(tok)
    try:
        return datetime.strptime(" ".join(rest[-5:]), "%a %b %d %H:%M:%S %Y").replace(tzinfo=tz)
    except ValueError:
        return None


def iter_raw_messages(path: str | Path) -> Iterator[RawMessage]:
    """כל הודעה בקובץ, כ-bytes גולמיים, יחד עם תאריך המעטפה."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"קובץ mbox לא נמצא: {path}")
    # mailbox סורק את הקובץ פעם אחת ושומר רק את המיקום של כל הודעה, לא את התוכן
    box = mailbox.mbox(str(path), create=False)
    try:
        for key in box.iterkeys():
            data = box.get_bytes(key, from_=True)
            first, _, rest = data.partition(b"\n")
            if first.startswith(b"From "):
                yield RawMessage(rest, _envelope_date(first.decode("ascii", "replace")))
            else:
                yield RawMessage(data, None)
    finally:
        box.close()


def count_messages(path: str | Path) -> int:
    box = mailbox.mbox(str(path), create=False)
    try:
        return len(box)
    finally:
        box.close()
