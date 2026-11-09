"""
הגדרות קבועות של הפרויקט.
כל הנתיבים, המודלים והפרמטרים במקום אחד, כדי שקל לשנות אותם בלי לגעת בקוד.
"""
import os
from pathlib import Path

# ---------- נתיבים ----------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DEMO_DIR = DATA_DIR / "demo"                # תיבת הדמו (mbox) וקבצים נלווים
PRIVATE_DIR = DATA_DIR / "private"          # מקום מומלץ לייצוא Takeout אמיתי. ב-.gitignore
REPORTS_DIR = BASE_DIR / "reports"          # תוצאות הערכה

# ---------- תיבות ----------
# כל תיבה (חשבון) מקבלת שם ותיקייה משלה ב-storage/<שם>/.
# אין כאן תיבה "פעילה": הממשק או indexer.py מקבלים את שם התיבה ומשתמשים ב-mailbox_paths.
# תיקייה נפרדת לכל תיבה, כי אינדקס של תיבה אמיתית הוא מידע רגיש ואסור שיתערבב עם אחרות.
# כל storage/ ב-.gitignore.
STORAGE_ROOT = BASE_DIR / "storage"

DEMO_MAILBOX = "demo"                         # תיבה מובנית, תמיד קיימת
DEMO_MBOX_PATH = DEMO_DIR / "demo_mailbox.mbox"
DEMO_MY_ADDRESSES = ["chani.levin@example.com"]   # הדמות הבדויה של תיבת הדמו
DEMO_ADDRESSING = "נקבה"   # איך התשובות פונות לבעלת התיבה ("נקבה" / "זכר" / "" = בלי פנייה מגדרית)
# שאלות פתיחה במסך הריק (כפתורים)
STARTERS = {
    "demo": ["מה בעל הדירה הסכים לגבי התיקונים?", "מתי ישיבת סיכום הרבעון?", "מה הבטחתי להביא לארוחת הצוות?",
             "תמצא לי את הסרטון מהכינוס"],
    "default": ["מה סוכם בפגישה האחרונה?", "מתי מגיעה ההזמנה?", "תמצא לי את הקבלה האחרונה"],
}


def mailbox_paths(name: str) -> dict[str, Path]:
    """כל הנתיבים של תיבה אחת."""
    root = STORAGE_ROOT / name
    return {
        "root": root,
        "info": root / "mailbox.json",              # נתיב המקור, הכתובות שלי, labels_checked
        "chroma": root / "chroma",
        "contacts": root / "contacts.json",
    }


BLACKLIST_FILE = DATA_DIR / "blacklist.json"   # המשתמש עורך, גם מתוך הממשק

CHROMA_COLLECTION = "gmail"   # בפועל מתווספים האסטרטגיה והספק, ראה llm_setup.py

# ---------- מודלים ----------
# ספק המודלים נקבע לכל תיבה (provider ב-mailbox.json), כי פרטיות שונה לכל תיבה:
# הדמו על Gemini החינמי (הבודק צריך רק מפתח חינמי). תיבה אמיתית על OpenAI: ב-API התוכן לא משמש לאימון.
# זו ברירת המחדל לתיבה בלי provider. החלפת ספק לתיבה קיימת מחייבת --rebuild (embedding אחר).
PROVIDER = "gemini"
PRIVATE_PROVIDER = "openai"   # ברירת המחדל בהוספת תיבה אמיתית

MODELS = {
    "gemini": {
        "llm": "gemini-3.5-flash-lite",   # flash איכותי יותר, אבל בשכבה החינמית רק 20 קריאות ביום (problems_log 15)
        "embed": "gemini-embedding-001",
        "key_env": "GOOGLE_API_KEY",
    },
    "openai": {
        "llm": "gpt-5.4-mini",
        "reasoning": "medium",   # בלי חשיבה המודל טעה ב"מי הציע" בשרשור מועבר. medium: 3/3 נכון, 3-9 שניות (problems_log 22)
        "embed": "text-embedding-3-large",   # small: hit rate 0.71 בדמו (עברית מול אנגלית). large: 0.94 (problems_log 23)
        "key_env": "OPENAI_API_KEY",
    },
}

LLM_TEMPERATURE = 0.0   # תשובות עקביות ככל האפשר

# המפתח נקרא רק ממשתנה סביבה. לעולם לא כותבים מפתח בקוד.
def get_api_key(provider: str) -> str:
    env_name = MODELS[provider]["key_env"]
    key = os.environ.get(env_name)
    if not key:
        raise RuntimeError(f"משתנה הסביבה {env_name} לא מוגדר.")
    return key

# הכתובות של בעל התיבה (לקביעת direction) לא נכתבות כאן: הן מזוהות אוטומטית
# מהשולח של מיילים עם התווית Sent, ונשמרות ב-mailbox.json של התיבה.

# ---------- טווח וסינון ----------
INDEX_YEARS = 3   # כמה שנים אחורה מאנדקסים. חיסכון בעלות אינדוקס, לא הגבלה של החיפוש

# תוויות Gmail (מהכותרת X-Gmail-Labels בייצוא Takeout) שלא מאנדקסים.
# השמות הם הנחה! לפני אינדוקס ראשון של ייצוא אמיתי בודקים עם:
#   python indexer.py --mbox <קובץ> --list-labels
# ייתכן שחשבון עם ממשק בעברית מייצא שמות אחרים. אותו דבר לגבי SENT_LABEL.
# Draft: טיוטה לא נשלחה. בלי ההחרגה, "מה הבטחתי ל..." יענה גם לפי מיילים שמעולם לא יצאו.
EXCLUDED_LABELS = {"Spam", "Trash", "Category Promotions", "Draft"}
SENT_LABEL = "Sent"

# ---------- עיבוד ----------
# "message": כל הודעה היא Node (ברירת המחדל).
# "thread": כל השרשור הוא מסמך אחד. רק להשוואה בסקריפט ההערכה.
CHUNKING_STRATEGY = "message"
CHUNK_SIZE = 1024        # טוקנים ל-SentenceSplitter, להודעות ארוכות
CHUNK_OVERLAP = 100

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024   # קובץ גדול מזה: רק שם הקובץ והקשר המייל
MAX_ATTACHMENT_CHARS = 20_000             # חיתוך טקסט מחולץ מקובץ מצורף

# ---------- אחזור ----------
CANDIDATE_K = 30          # כמה לשלוף מ-Chroma לפני סינון לפי כתובת ודירוג מחדש
TOP_K = 8                 # כמה מקורות מוצגים ונשלחים ל-LLM
RECENCY_WEIGHT = 0.01     # מספיק להכריע בין מיילים דומים. 0.05 גבר על הרלוונטיות (problems_log 15)
RECENCY_HALF_LIFE_DAYS = 365
TOPIC_SLOTS = 2           # מקומות שמורים לתוצאות הטובות של החיפוש לפי הנושא בלבד (problems_log 24)
PERSON_BOOST = 0.05       # עדיפות למיילים של איש קשר שהוזכר בשאלה (problems_log 23)   # אחרי כמה ימים היתרון יורד לחצי
