"""
החלטה אילו הודעות מאנדקסים בכלל.
- תוויות מוחרגות: ספאם, אשפה, Promotions, טיוטות (X-Gmail-Labels).
- טווח תאריכים: INDEX_YEARS אחרונות (חיסכון בעלות, לא הגבלה של החיפוש).
- רשימה שחורה מ-data/blacklist.json: שולחים, דומיינים ומילות מפתח.
  כולל טעינה ושמירה של הקובץ, כדי שהממשק יוכל לערוך אותו.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json

import config
from email_parser import ParsedEmail


@dataclass
class Blacklist:
    senders: list[str] = field(default_factory=list)          # כתובות מלאות
    sender_domains: list[str] = field(default_factory=list)   # כולל תת-דומיינים
    keywords: list[str] = field(default_factory=list)         # בנושא או בגוף, בלי תלות באותיות גדולות

    def match(self, mail: ParsedEmail) -> str:
        """הסיבה שהמייל ברשימה השחורה, או "" אם הוא לא."""
        sender = mail.from_email.lower()
        if sender in (s.lower() for s in self.senders):
            return f"שולח: {sender}"
        domain = sender.rsplit("@", 1)[-1]
        for d in self.sender_domains:
            d = d.lower().lstrip("@.")
            if domain == d or domain.endswith("." + d):
                return f"דומיין: {d}"
        haystack = f"{mail.subject}\n{mail.body}".lower()
        for kw in self.keywords:
            if kw.lower() in haystack:
                return f"מילת מפתח: {kw}"
        return ""


def load_blacklist(path=config.BLACKLIST_FILE) -> Blacklist:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Blacklist(data.get("senders", []), data.get("sender_domains", []), data.get("keywords", []))


def save_blacklist(bl: Blacklist, path=config.BLACKLIST_FILE) -> None:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(senders=bl.senders, sender_domains=bl.sender_domains, keywords=bl.keywords)   # שומר את "_הסבר"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def index_cutoff(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now - timedelta(days=round(365.25 * config.INDEX_YEARS))


@dataclass
class FilterDecision:
    keep: bool
    reason: str = ""    # למה לא (לסטטיסטיקה ולהסבר למשתמש)


def decide(mail: ParsedEmail, blacklist: Blacklist, cutoff: datetime) -> FilterDecision:
    excluded = [label for label in mail.labels if label in config.EXCLUDED_LABELS]
    if excluded:
        return FilterDecision(False, f"תווית: {excluded[0]}")
    # מייל בלי תאריך בכלל נשמר: אין סיבה להניח שהוא ישן
    if mail.date is not None and mail.date < cutoff:
        return FilterDecision(False, "ישן מטווח האינדוקס")
    reason = blacklist.match(mail)
    if reason:
        return FilterDecision(False, f"רשימה שחורה ({reason})")
    return FilterDecision(True)
