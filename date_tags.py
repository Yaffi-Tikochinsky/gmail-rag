"""
תיוג תאריכים בטקסט לפני שליחה ל-LLM: "(עבר, ט׳ בחשון תשפ״ז, לפני כ-3 שבועות)".
מודל שפה טועה בהשוואת תאריכים ("החתונה ב-18.6.2026 עתידית" כשהיום 3.11.2026), וקוד לא טועה.
תאריך בלי שנה ("20.10", "29 במרץ") מקבל את שנת המייל, או את השנה הבאה אם יצא חודשיים ויותר לפני המייל.
"""
from datetime import date, timedelta
import re

from hebrew_date import distance, hebrew

HE_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
EN_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_HE = "|".join(HE_MONTHS)
_UNIT = r"\s*(?:%|₪|ש\"ח|ליטר|שעות|שעה|ק\"ג|ק״ג|מ\"ר|ס\"מ|kg|km|cm|hours?|liters?|version)"   # 2.5 שעות = לא תאריך
_EN = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE = re.compile(
    rf"(?<![\d.,/$₪])(?P<d>\d{{1,2}})[./](?P<m>\d{{1,2}})(?:[./](?P<y>\d{{4}}|\d{{2}}))?(?![\d/]|[.,]\d|{_UNIT})"   # 18.6.2026, 20.10
    rf"|(?<!\d)(?P<d2>\d{{1,2}})\s+ב?(?P<hm>{_HE})(?:\s+(?P<y2>\d{{4}}))?"                         # 29 במרץ 2026
    rf"|(?<!\d)(?P<d3>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<em>{_EN})(?:\s+(?P<y3>\d{{4}}))?"               # 31 March
    rf"|\b(?P<em2>{_EN})\s+(?P<d4>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<y4>\d{{4}}))?",            # March 31, 2026
    re.I)


def _parse(m: re.Match, mail_date: date) -> date | None:
    g = m.groupdict()
    day = int(g["d"] or g["d2"] or g["d3"] or g["d4"])
    if g["m"]:
        month = int(g["m"])
    elif g["hm"]:
        month = HE_MONTHS.index(g["hm"]) + 1
    else:
        month = EN_MONTHS.index((g["em"] or g["em2"])[:3].lower()) + 1
    year = g["y"] or g["y2"] or g["y3"] or g["y4"]
    try:
        if year:
            return date(int(year) + (2000 if len(year) == 2 else 0), month, day)
        d = date(mail_date.year, month, day)
        return d.replace(year=d.year + 1) if d < mail_date - timedelta(days=60) else d
    except ValueError:   # 9.99 (מחיר), 31.2 וכו'
        return None


def tag_dates(text: str, mail_date_int: int, today: date) -> str:
    mail_date = date(mail_date_int // 10000, mail_date_int // 100 % 100, mail_date_int % 100) if mail_date_int else today

    def repl(m: re.Match) -> str:
        d = _parse(m, mail_date)
        if d is None:
            return m.group(0)
        when = "היום" if d == today else "עבר" if d < today else "עתידי"
        return m.group(0) + f" ({when}, {hebrew(d)}" + ("" if d == today else f", {distance(d, today)}") + ")"
    return DATE.sub(repl, text)
