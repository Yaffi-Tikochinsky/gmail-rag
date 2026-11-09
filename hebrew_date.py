"""
תאריך עברי ומרחק מהיום, מחושבים בקוד ולא על ידי המודל (problems_log 25).
המודל המיר את 20.10.2026 פעם ל-ט' ופעם ל-י' בחשוון. כאן: האלגוריתם הסטנדרטי של הלוח העברי
(מולד, דחיות), לפי Reingold & Dershowitz, "Calendrical Calculations". בלי תלות חיצונית.
"""
from datetime import date

EPOCH = -1373427   # א' בתשרי שנת 1, כמספר יום (date.toordinal)
MONTHS = {1: "ניסן", 2: "אייר", 3: "סיון", 4: "תמוז", 5: "אב", 6: "אלול", 7: "תשרי", 8: "חשון", 9: "כסלו",
          10: "טבת", 11: "שבט", 12: "אדר", 13: "אדר ב׳"}


def _leap(y: int) -> bool:
    return (7 * y + 1) % 19 < 7


def _elapsed(y: int) -> int:
    months = (235 * y - 234) // 19
    days = 29 * months + (12084 + 13753 * months) // 25920
    return days + 1 if (3 * (days + 1)) % 7 < 3 else days


def _new_year(y: int) -> int:
    e0, e1, e2 = _elapsed(y - 1), _elapsed(y), _elapsed(y + 1)
    return EPOCH + e1 + (2 if e2 - e1 == 356 else 1 if e1 - e0 == 382 else 0)


def _month_days(m: int, y: int) -> int:
    length = _new_year(y + 1) - _new_year(y)
    if m in (2, 4, 6, 10, 13) or (m == 12 and not _leap(y)) or (m == 8 and length % 10 != 5) \
            or (m == 9 and length % 10 == 3):
        return 29
    return 30


def _fixed(y: int, m: int, d: int) -> int:
    last = 13 if _leap(y) else 12
    months = range(7, m) if m >= 7 else [*range(7, last + 1), *range(1, m)]
    return _new_year(y) + d - 1 + sum(_month_days(x, y) for x in months)


def to_hebrew(g: date) -> tuple[int, int, int]:
    """(שנה, חודש, יום). ניסן = 1, תשרי = 7, אדר ב' = 13."""
    n = g.toordinal()
    y = (n - EPOCH) * 98496 // 35975351 + 1
    while _new_year(y) > n:
        y -= 1
    while _new_year(y + 1) <= n:
        y += 1
    m = 7 if n < _fixed(y, 1, 1) else 1
    while n > _fixed(y, m, _month_days(m, y)):
        m = m % (13 if _leap(y) else 12) + 1
    return y, m, n - _fixed(y, m, 1) + 1


def gematria(n: int) -> str:
    """787 -> תשפ״ז, 15 -> ט״ו."""
    letters = [(400, "ת"), (300, "ש"), (200, "ר"), (100, "ק"), (90, "צ"), (80, "פ"), (70, "ע"), (60, "ס"), (50, "נ"),
               (40, "מ"), (30, "ל"), (20, "כ"), (10, "י"), (9, "ט"), (8, "ח"), (7, "ז"), (6, "ו"), (5, "ה"), (4, "ד"),
               (3, "ג"), (2, "ב"), (1, "א")]
    out = ""
    while n:
        if n % 100 in (15, 16) and n < 100:   # ט"ו, ט"ז ולא י"ה, י"ו
            out += "ט" + ("ו" if n == 15 else "ז")
            break
        v, ch = next((v, ch) for v, ch in letters if v <= n)
        out, n = out + ch, n - v
    return out + "׳" if len(out) == 1 else out[:-1] + "״" + out[-1]


def hebrew(g: date) -> str:
    """ט׳ בחשון תשפ״ז"""
    y, m, d = to_hebrew(g)
    month = "אדר א׳" if m == 12 and _leap(y) else MONTHS[m]
    return f"{gematria(d)} ב{month} {gematria(y % 1000)}"


def distance(g: date, today: date) -> str:
    """ "לפני כ-3 שבועות" / "בעוד יומיים" / "היום". מעוגל, כמו שאדם אומר."""
    days = (g - today).days
    if days == 0:
        return "היום"
    n = abs(days)
    span = ("יום אחד" if n == 1 else "יומיים" if n == 2 else f"{n} ימים" if n < 14 else
            f"כ-{round(n / 7)} שבועות" if n < 60 else f"כ-{round(n / 30.4)} חודשים" if n < 548 else
            f"כ-{round(n / 365.25)} שנים")
    return ("בעוד " if days > 0 else "לפני ") + span
