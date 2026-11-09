"""
הכנת שאלה לחיפוש: ניסוח מחדש, כתיב שמות, נושא, ואיש הקשר שהוזכר. משותף לממשק, להערכה ולמלכודות,
כדי שהבדיקות יריצו בדיוק את מה שהמשתמש מריץ.
"""
from dataclasses import dataclass, field, replace

from contacts import EMAIL_IN_QUERY, Contacts
from qa import condense
from retriever import Filters, SearchResult, retrieve


@dataclass
class Plan:
    sq: str                  # השאלה המנוסחת מחדש. עליה המודל עונה
    search_q: str            # השאלה + כתיב שמות. עליה מחפשים
    topic: str               # הנושא לבד, לחיפוש נוסף (problems_log 24)
    filters: Filters
    ambiguous: list = field(default_factory=list)   # כמה אנשי קשר מתאימים לשם: המשתמש בוחר
    from_name: str = ""      # "רק מה ש-X כתב"


def plan(question: str, history: list[tuple[str, str]], owner: str, contacts: Contacts, base: Filters,
         llm=None, skip_contacts: bool = False) -> Plan:
    sq, names, topic = condense(history, question, owner, llm)
    addr, person, ambiguous = base.address, "", []
    found = EMAIL_IN_QUERY.search(sq)
    if not addr and found:   # כתובת בתוך השאלה = סינון מדויק
        addr = found.group(0).lower()
    if not addr and not skip_contacts:
        matches = contacts.find(f"{sq} {names}")
        if len(matches) > 1:
            ambiguous = matches
        elif matches and contacts.from_only(sq, matches[0][0]):
            addr = matches[0][0]     # "מה חדש משמעון": רק המיילים שהוא כתב (problems_log 22)
        elif matches:
            person = matches[0][0]   # "לאה": המיילים שלה בעדיפות, בלי לסנן (problems_log 23)
    from_only = bool(addr) and contacts.from_only(sq, addr)
    c = contacts.data.get(addr, {})
    return Plan(sq, f"{sq} ({names})" if names else sq, topic,
                replace(base, address=addr, from_only=from_only, person=person), ambiguous,
                (c.get("canonical") or (c.get("names") or [addr])[0]) if from_only else "")


def search(col, p: Plan) -> SearchResult:
    return retrieve(col, p.search_q, p.filters, topic=p.topic)
