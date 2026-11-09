"""
טבלת אנשי קשר: לכל כתובת, השמות שהופיעו איתה. נבנית מחדש בכל אינדוקס.
LLM מוסיף שם קנוני בעברית וכינויים (Moshe / משה). זו הצעה בלבד: שם שמתאים לכמה כתובות מוצג למשתמש לבחירה.
"""
import json
from pathlib import Path
import re

from body_cleaner import CleanResult
from email_parser import ParsedEmail

EMAIL_IN_QUERY = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
LLM_BATCH = 150
FROM_VERBS = r"(?:כתב|כתבה|אמר|אמרה|שלח|שלחה|ביקש|ביקשה|הציע|הציעה|ענה|ענתה|עדכן|עדכנה|סיפר|סיפרה|wrote|said|sent)\b"

PROMPT = """לפניך רשימת אנשי קשר מתיבת מייל: כתובת, והשמות שהופיעו איתה.
לכל כתובת החזר שם קנוני בעברית, ורשימת כינויים: תעתיק לאנגלית/עברית, שם פרטי לבד, וצורות נפוצות,
כולל שמות חיבה נפוצים (מרים -> מירי, שמעון -> שימי, יעקב -> קובי).
אל תאחד כתובות ואל תמציא מידע. החזר JSON בלבד, בצורה: {{"כתובת": {{"canonical": "...", "aliases": ["..."]}}}}

{rows}"""


class Contacts:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def start_rebuild(self) -> None:
        """מאפס שמות ומונים, ושומר את מה שה-LLM כבר החזיר (כדי לא לשלם שוב)."""
        for c in self.data.values():
            c.update(names=[], count=0, last=0)

    def add(self, name: str, addr: str, date: int) -> None:
        if not addr:
            return
        c = self.data.setdefault(addr, {"names": [], "count": 0, "last": 0, "canonical": "", "aliases": []})
        if name and name not in c["names"]:
            c["names"].append(name)
        c["count"] += 1
        c["last"] = max(c["last"], date)

    def add_mail(self, mail: ParsedEmail, clean: CleanResult) -> None:
        for name, addr in [(mail.from_name, mail.from_email), *mail.to, *mail.cc, *clean.forwarded_from]:
            self.add(name, addr, mail.date_int)

    def save(self) -> None:
        self.data = {a: c for a, c in self.data.items() if c["count"]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    def enrich_with_llm(self, llm) -> int:
        """שם קנוני וכינויים לאנשי קשר חדשים. מחזיר כמה עודכנו."""
        pending = [a for a, c in self.data.items() if c["count"] and not c["canonical"]]
        done = 0
        for i in range(0, len(pending), LLM_BATCH):
            batch = pending[i:i + LLM_BATCH]
            rows = "\n".join(f"{a}: {', '.join(self.data[a]['names']) or '(בלי שם)'}" for a in batch)
            reply = llm.complete(PROMPT.format(rows=rows)).text
            match = re.search(r"\{.*\}", reply, re.S)
            try:
                result = json.loads(match.group(0)) if match else {}
            except json.JSONDecodeError:
                result = {}
            for addr, r in result.items():
                if addr in self.data and isinstance(r, dict):
                    self.data[addr]["canonical"] = str(r.get("canonical", ""))
                    self.data[addr]["aliases"] = [str(x) for x in r.get("aliases", [])]
                    done += 1
        return done

    def from_only(self, query: str, addr: str) -> bool:
        """השאלה על מה שהוא כתב ("משמעון", "מה שמעון כתב"), ולא על מה שנשלח אליו ("לשמעון", "הבטחתי לו")."""
        c = self.data.get(addr)
        if not c:
            return False
        q = query.lower()
        for t in {t.lower() for t in c["names"] + c["aliases"] + [c["canonical"]] if len(t) >= 2}:
            t = re.escape(t)
            if re.search(rf"(?:^|\W)ו?מ{t}(?!\w)|(?:^|\W){t}\s+{FROM_VERBS}|\bfrom\s+{t}", q):
                return True
        return False

    def find(self, query: str) -> list[tuple[str, dict]]:
        """אנשי קשר ששם או כינוי שלהם מופיע בשאלה. כמה תוצאות = המשתמש בוחר.
        רק ההתאמות הארוכות ביותר: "ראובן פרידמן" הוא ראובן, ולא גם רחלי פרידמן (ששתיהן מתאימות ל"פרידמן")."""
        q = query.lower()
        hits = []
        for addr, c in self.data.items():
            terms = {t.lower() for t in c["names"] + c["aliases"] + [c["canonical"]] if len(t) >= 2}
            # מילה שלמה, עם אותיות שימוש בעברית לפניה ("למשה", "ומשה")
            best = max((len(t) for t in terms if re.search(rf"(?:^|\W)[ובלמשהכ]{{0,2}}{re.escape(t)}(?!\w)", q)), default=0)
            if best:
                hits.append((best, addr, c))
        top = max((b for b, _, _ in hits), default=0)
        return [(a, c) for b, a, c in hits if b == top]
