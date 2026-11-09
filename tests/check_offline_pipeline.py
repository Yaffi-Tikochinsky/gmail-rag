"""
בדיקת כל השרשרת בלי API: אינדוקס -> אחזור -> תשובה -> ממשק.
במקום Gemini: embedding מקומי לפי n-grams של תווים (חיפוש מילולי, אבל עם משמעות) ו-MockLLM.
האינדקס נבנה בתיקייה זמנית, והאינדקס האמיתי לא נפגע.
הרצה (מתיקיית gmail_rag):  python tests/check_offline_pipeline.py
"""
from pathlib import Path
import re
import sys
import tempfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from llama_index.core import Settings
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.llms.mock import MockLLM

import config
import indexer
import llm_setup
from mail_filters import Blacklist, load_blacklist
import qa
from retriever import Filters, get_thread, retrieve
import store


class NgramEmbedding(BaseEmbedding):
    def _vec(self, text: str) -> list[float]:
        v = [0.0] * 1024
        for w in re.findall(r"\w+", text.lower()):
            for i in range(max(1, len(w) - 2)):
                v[zlib.crc32(w[i:i + 3].encode()) % 1024] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]

    def _get_text_embedding(self, text): return self._vec(text)
    def _get_query_embedding(self, query): return self._vec(query)
    async def _aget_query_embedding(self, query): return self._vec(query)


results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))


Settings.embed_model, Settings.llm = NgramEmbedding(), MockLLM()
llm_setup.setup_models = lambda *a: None   # בלי מפתח ובלי רשת
tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
config.STORAGE_ROOT = Path(tmp.name)
name, quiet = config.DEMO_MAILBOX, (lambda *a: None)
info = store.load_info(name)

# ---- אינדוקס ואינקרמנטליות ----
stats = indexer.index_mailbox(name, info, log=quiet)
col = store.collection(name)
check("אינדוקס: 93 מיילים, 110 nodes", stats["חדש"] == 93 and col.count() == 110, f"{stats} / {col.count()}")
stats = indexer.index_mailbox(name, info, log=quiet)
check("ריצה שנייה: אין כלום חדש", stats["חדש"] == 0 and stats["כבר באינדקס"] == 93 and col.count() == 110, str(stats))

# ---- אחזור ----
def ids(res):
    return [h.node.metadata["message_id"].strip("<>").split("@")[0] for h in res.hits]

res = retrieve(col, "נזילה מתחת לכיור במטבח", Filters())
check("אחזור: מייל הנזילה נמצא", "repair-1" in ids(res), str(ids(res)))
thr = [h.node.metadata["thread_id"] for h in res.hits]
check("המקורות לפי תאריך, ושרשור ברצף", all(thr.index(x) == i or thr[i - 1] == x for i, x in enumerate(thr))
      and all(a.node.metadata["ts"] <= b.node.metadata["ts"] for a, b in zip(res.hits, res.hits[1:])
              if a.node.metadata["thread_id"] == b.node.metadata["thread_id"]), str(thr))

check("שקיפות: 93 מיילים בטווח", res.n_messages == 93 and res.date_min and res.date_max, f"{res.n_messages} {res.date_min}-{res.date_max}")

# ---- מי אמר מה ----
res = retrieve(col, "מתנה לאמא שעון", Filters())
src = qa.format_sources(res.hits)
check("מקור: הכותב בראש, והמשתמש מסומן", "| כתב/ה: חני לוין (המשתמש עצמו)" in src and "| כתב/ה: שמעון שטרן | מעביר/ה הודעות של:" in src, src[:600])
check("מקור: הודעה מאותו שרשור מסומנת כהמשך", "| המשך השרשור של מקור" in src, src[:600])
check("העברה: תווית כותב לכל הודעה", "[הודעה מועברת 2 | כתב/ה: Leah Weiss" in src and "[הודעה מועברת 1 | כתב/ה: ראובן פרידמן" in src)
from contacts import Contacts
cts = Contacts(config.mailbox_paths(name)["contacts"])
cts.data["shimon.stern@example.com"]["aliases"] = ["שמעון"]   # ב-MockLLM אין כינויים
check("'משמעון' / 'מה שמעון כתב' = רק מה שהוא כתב", cts.from_only("יש חדש משמעון?", "shimon.stern@example.com")
      and cts.from_only("מה שמעון כתב על המתנה?", "shimon.stern@example.com")
      and not cts.from_only("מה הבטחתי לשמעון?", "shimon.stern@example.com"))
res = retrieve(col, "מה חדש", Filters(address="shimon.stern@example.com", from_only=True))
check("סינון 'רק מה שהוא כתב': בלי המיילים של חני אליו", res.hits and all(h.node.metadata["direction"] == "incoming" for h in res.hits), str(ids(res)))
q = "יש הזדמנות לפגוש את לאה?"
plain = ids(retrieve(col, q, Filters()))
boosted = ids(retrieve(col, q, Filters(person="leah.weiss@example.com")))
check("שם של איש קשר: המיילים שלו בעדיפות, בלי לסנן את השאר",
      sum("leah" in i for i in boosted) > sum("leah" in i for i in plain) and any("leah" not in i for i in boosted),
      f"{plain} -> {boosted}")
from llama_index.core.base.llms.types import CompletionResponse
class Fixed:
    def complete(self, _): return CompletionResponse(text="שאלה: מתי לאה נוחתת בפסח?\nשמות: לאה, Leah, פסח, Pesach\nנושא: נחיתה, טיסה")
check("ניסוח מחדש: שמות בשפה השנייה, והשאלה נשארת אם אין שיחה",
      qa.condense([], "מתי לאה נוחתת?", llm=Fixed()) == ("מתי לאה נוחתת?", "לאה, Leah, פסח, Pesach", "נחיתה, טיסה")
      and qa.condense([("q", "a")], "ומתי היא נוחתת?", llm=Fixed())[0] == "מתי לאה נוחתת בפסח?")
class NoNames:
    def complete(self, _): return CompletionResponse(text="שאלה: כמה עולה המנוי?\nשמות:\nנושא: מנוי, כושר")
check("ניסוח מחדש: שורת שמות ריקה לא לוקחת את השורה הבאה", qa.condense([], "כמה עולה המנוי?", llm=NoNames())[1:] == ("", "מנוי, כושר"))
q = "מירי מהמשרד הודיעה משהו חדש על ההשתלמות?"
check("חיפוש גם לפי הנושא לבד: מייל ההשתלמות נמצא", "training-excel" in ids(retrieve(col, q, Filters(), topic="השתלמות")),
      f"{ids(retrieve(col, q, Filters()))} -> {ids(retrieve(col, q, Filters(), topic='השתלמות'))}")
from node_builder import _with_labels
txt = "intro\n\n[הודעה מועברת 1 | כתב/ה: Dan]\nAAA BBB\n\n[הודעה מועברת 2 | כתב/ה: Ron]\nCCC"
check("קטע מאמצע הודעה מועברת מקבל את התווית שלה", _with_labels(txt, ["intro\n\n[הודעה מועברת 1 | כתב/ה: Dan]\nAAA", "BBB", "[הודעה מועברת 2 | כתב/ה: Ron]\nCCC"])
      == ["intro\n\n[הודעה מועברת 1 | כתב/ה: Dan]\nAAA", "[הודעה מועברת 1 | כתב/ה: Dan | המשך]\nBBB", "[הודעה מועברת 2 | כתב/ה: Ron]\nCCC"])

res = retrieve(col, "מה משה אמר", Filters(address="moshe.cohen.fix@example.com"))
check("סינון לפי כתובת: רק השיפוצניק", res.hits and all("moshe.cohen.fix" in h.node.metadata["participants"] + h.node.metadata["recipients"] for h in res.hits), str(ids(res)))
check("סינון לפי כתובת: לא המלמד", not any("rebbe" in i or "chumash" in i for i in ids(res)), str(ids(res)))

res = retrieve(col, "שכר דירה", Filters(address="yaakov.berger@example.com"))
check("כתובת כוללת מיילים יוצאים אליו", any(h.node.metadata["direction"] == "outgoing" for h in res.hits), str(ids(res)))

res = retrieve(col, "ישיבה", Filters(date_from=20260101))
check("סינון תאריך", res.hits and all(h.node.metadata["date"] >= 20260101 for h in res.hits))
res = retrieve(col, "קבלה", Filters(node_type="attachment"))
check("סינון סוג: קבצים מצורפים", res.hits and all(h.node.metadata["node_type"] == "attachment" for h in res.hits))

thread = get_thread(col, next(m for m in col.get(include=["metadatas"])["metadatas"]
                              if m["message_id"] == "<lease-renewal-1@mail.demo.example>")["thread_id"])
check("שרשור מלא לפי סדר", [r["meta"]["message_id"].split("@")[0][1:] for r in thread] ==
      ["lease-renewal-1", "lease-renewal-2", "lease-renewal-3", "lease-renewal-4"], str([r["meta"]["message_id"] for r in thread]))

# ---- תשובה ----
check("בלי מקורות: 'לא נמצא' בלי קריאה ל-LLM", qa.answer("x", []) == qa.NOT_FOUND)
res = retrieve(col, "מתי הישיבה", Filters())
check("פרומפט כולל את המקורות ממוספרים, עם גיל המייל", "<מקור 1 | התקבל " in qa.format_sources(res.hits))
check("זיהוי שאלת סכימה", qa.is_aggregate("כמה שילמנו על שכר דירה?") and not qa.is_aggregate("מתי הישיבה?"))
check("כל מייל מופיע פעם אחת במקורות", len(ids(res)) == len(set(ids(res))), str(ids(res)))
check("זיהוי בקשת חיפוש", qa.is_find("תמצא לי את הציור") and qa.is_find("תמצאי את החשבונית")
      and not qa.is_find("מתי הישיבה?") and not qa.is_find("מה מצאו בבדיקה?"))
check("חילוץ מקורות שצוטטו", qa.cited("נדחה [7, 8]. ובוטל [2] [12]", 8) == [2, 7, 8])
class Busy:   # שרת עמוס פעמיים, ואז עונה
    calls = 0
    def stream_complete(self, _):
        Busy.calls += 1
        if Busy.calls < 3:
            raise RuntimeError("503 UNAVAILABLE. The model is overloaded.")
        yield CompletionResponse(text="x", delta="תשובה [1].")
from types import SimpleNamespace
import time
real_sleep, real_settings = time.sleep, qa.Settings
time.sleep, qa.Settings = (lambda s: None), SimpleNamespace(llm=Busy())
out = {}
streamed = "".join(qa.answer_stream("q", res.hits, "", out))
time.sleep, qa.Settings = real_sleep, real_settings
check("שרת עמוס (503): ניסיון חוזר, והתשובה מגיעה", streamed == "תשובה [1]." and Busy.calls == 3, f"{streamed!r} {Busy.calls}")
from datetime import date
from date_tags import tag_dates
t = date(2026, 11, 3)
check("תיוג תאריכים: עבר / עתידי / שנה חסרה / לא תאריך",
      tag_dates("חתונה ב-18.6.2026, כנס ב-5.12.2026", 20261018, t)
      == "חתונה ב-18.6.2026 (עבר, ג׳ בתמוז תשפ״ו, לפני כ-5 חודשים), כנס ב-5.12.2026 (עתידי, כ״ה בכסלו תשפ״ז, בעוד כ-5 שבועות)"
      and tag_dates("מסיבה ב-5.1", 20251215, t).startswith("מסיבה ב-5.1 (עבר, ט״ז בטבת תשפ״ו")   # ינואר 2026, לא 2025
      and tag_dates("נחיתה 31 במרץ, March 31st", 20260210, t).count("(עבר, י״ג בניסן תשפ״ו") == 2
      and tag_dates("$9.99, 2.5 שעות, 4,900", 20260601, t) == "$9.99, 2.5 שעות, 4,900")
from hebrew_date import hebrew
check("תאריך עברי בקוד: ראש השנה, פסח, חנוכה, אדר ב', 15/16",
      [hebrew(date(*d)) for d in [(2026, 9, 12), (2026, 4, 2), (2025, 12, 15), (2024, 3, 24), (2000, 1, 1)]]
      == ["א׳ בתשרי תשפ״ז", "ט״ו בניסן תשפ״ו", "כ״ה בכסלו תשפ״ו", "י״ד באדר ב׳ תשפ״ד", "כ״ג בטבת תש״ס"])
check("זיהוי שאלת רשימה", qa.is_aggregate("איזה אירועים עתידיים אני מוזמנת אליהם?")
      and not qa.is_aggregate("באיזו שעה עובר קו 3?") and not qa.is_aggregate("איזה צבע העגלה?"))
check("שאלות המשך מופרדות מהתשובה", qa.split_followups("יומיים [5].\nהמשך: מתי חוזרים? | מי מחליפה אותי?")
      == ("יומיים [5].", ["מתי חוזרים?", "מי מחליפה אותי?"]))
check("קישור בתשובה לא לחיץ", "http" not in qa.safe_markdown("כנסי ל-http://evil.example/pay עכשיו"))
check("'לא מצאתי' = בלי מקורות, אבל תשובה חלקית שומרת את המקור", qa.cited("לא מצאתי מידע על קוד אימות [8].", 8) == []
      and qa.cited("לא מצאתי עדכון ממירי על ההשתלמות; ההודעה שמצאתי היא על השתלמות אקסל מתקדם ב-24.3.2026 בזום, מרכזת ההדרכה [3].", 8) == [3])
check("'תראה לי מה...' היא שאלה ולא חיפוש", not qa.is_find("תראה לי מה הבוסית ביקשה לגבי הדוח")
      and qa.is_find("תראה לי את הקבלה"))

res = retrieve(col, "חוזר פתיחת שנה תשפ\"ו תלמוד תורה אורחות חיים", Filters())
att = col.get(where={"$and": [{"message_id": "<tt-opening@mail.demo.example>"}, {"node_type": "attachment"}]},
              include=["documents"])["documents"][0].split("\n\n", 1)[1][:60]
hit = next((h for h in res.hits if "tt-opening" in h.node.metadata["message_id"]), None)
check("מייל + קובץ מצורף מאוחדים למקור אחד, בלי לאבד את הקובץ", hit and att in hit.node.get_content(),
      hit.node.get_content()[:300] if hit else str(ids(res)))

res = retrieve(col, "חשבונית לתשלום שכר דירה מרץ מחלקת גבייה", Filters())
safe, bad = qa.split_suspicious(res.hits)
check("מייל זדוני מסומן ולא נשלח ל-LLM", any("injection-rent" in h.node.metadata["message_id"] for h in bad)
      and not any("injection" in h.node.metadata["message_id"] for h in safe if "injection-rent" in h.node.metadata["message_id"])
      and len(bad) == 1, str([h.node.metadata["message_id"] for h in bad]))

# ---- רשימה שחורה אחרי אינדוקס: הסרה ----
indexer.load_blacklist = lambda: Blacklist(keywords=["ShopNest"])
stats = indexer.index_mailbox(name, info, log=quiet)
left = [m for m in col.get(include=["metadatas"])["metadatas"] if "shopnest" in m["from_email"]]
check("מילה שנוספה לרשימה השחורה מסירה מיילים שכבר באינדקס", not left, f"נשארו {len(left)}")
indexer.load_blacklist = load_blacklist

# ---- ממשק (בלי דפדפן) ----
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=60)
at.run()
check("ממשק: נטען בלי שגיאות, עם שאלות פתיחה", not at.exception and any(b.label == "מתי ישיבת סיכום הרבעון?" for b in at.button),
      str(at.exception or [b.label for b in at.button]))
at.chat_input[0].set_value("מה משה כהן אמר?").run()
labels = [b.label for b in at.button]
check("ממשק: שני משה כהן -> כפתור לכל אחד", any("orchot" in l for l in labels) and any("fix" in l for l in labels), str(labels))
next(b for b in at.button if "fix" in b.label).click().run()
check("ממשק: בחירת איש קשר מריצה את השאלה מסוננת", not at.exception and any("חיפשתי ב-" in c.value for c in at.caption),
      str(at.exception or [c.value for c in at.caption]))
next(b for b in at.button if b.label == "מתי ישיבת סיכום הרבעון?").click().run() if any(
    b.label == "מתי ישיבת סיכום הרבעון?" for b in at.button) else at.chat_input[0].set_value("מתי ישיבת סיכום הרבעון?").run()
check("ממשק: השיחה נשמרת (3 תורות)", not at.exception and len(at.chat_message) >= 6, str(at.exception or len(at.chat_message)))
at.chat_input[0].set_value("תמצא לי את הציור של מיכלי").run()
check("ממשק: בקשת חיפוש מציגה הודעה בלי תשובה כתובה",
      not at.exception and any("ההודעה שחיפשת" in m.value or "לא מצאתי הודעה" in m.value for m in at.markdown),
      str(at.exception or [m.value for m in at.markdown]))
check("ממשק: יש משוב לכל תשובה", len(at.get("feedback")) >= 2, str(len(at.get("feedback"))))

# ---- סיכום ----
for n, ok, d in results:
    print(f"{'✓' if ok else '✗'} {n}  {'' if ok else d}")
failed = sum(not ok for _, ok, _ in results)
print(f"\n{len(results) - failed}/{len(results)} עברו")
sys.exit(1 if failed else 0)
