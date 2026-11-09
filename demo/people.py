"""
הדמויות של תיבת הדמו. הכל בדוי. כתובות רק בדומיינים שמורים (example.com, *.example).

בעלת התיבה: חני לוין, מנהלת חשבונות במשרד "אופק", גרה בשכירות ברחוב הנרקיס 12 בבית שמש.
בעלה אברהם (אבי). ילדים: יוסי (כיתה א׳ בת"ת), מיכלי (גן), נחמי (נולדה בפברואר 2025).

מקרי קצה שמובנים בדמויות:
- שני אנשים בשם "משה כהן" עם כתובות שונות: השיפוצניק והמלמד של יוסי.
- אותו אדם בשם עברי ובשם אנגלי (אותה כתובת): יעקב ברגר / Yaakov Berger, בעל הדירה.
- אותו אדם בשתי כתובות: אסתי רוזן מהעבודה ו-Esty Rosen מהכתובת הפרטית.
- שולח בלי שם תצוגה (תאגיד המים).
"""
from spec import Person

# ---------- בעלת התיבה ----------
CHANI = Person("חני לוין", "chani.levin@example.com", quote="gmail_he")
CHANI_MOBILE = Person("חני לוין", "chani.levin@example.com", sig="נשלח מה-iPhone שלי", quote="he_wrote")
CHANI_EN = Person("Chani Levin", "chani.levin@example.com", quote="gmail_en")

# ---------- בית ----------
AVI = Person("אברהם לוין", "avraham.levin@example.com", sig="-- \nאבי", quote="gmail_he")
YAAKOV = Person("יעקב ברגר", "yaakov.berger@example.com", quote="he_wrote",
                encoding="cp1255-qp", subject_charset="windows-1255")
YAAKOV_EN = Person("Yaakov Berger", "yaakov.berger@example.com", quote="gmail_en",
                   sig="Sent from my Galaxy")
MOSHE_FIX = Person("משה כהן", "moshe.cohen.fix@example.com",
                   sig="-- \nמשה כהן | שיפוצים ואחזקה\n050-7000123", quote="he_wrote")
VAAD = Person("ועד הבית הנרקיס 12", "vaad.narkis12@example.com")
IRIYA = Person("עיריית בית שמש - ארנונה", "arnona@city-bs.example")
MAYIM = Person("", "noreply@water-corp.example")      # בלי שם תצוגה, בכוונה
OLD_LANDLORD = Person("שמואל גרוס", "shmuel.gross@example.com")
INSURANCE = Person("יוסף מזרחי - סוכנות ביטוח", "yosef@mizrahi-insurance.example")

# ---------- עבודה ----------
_OFEK_SIG = "\n\nבברכה,\n{name}\n{role}\nאופק הנהלת חשבונות בע\"מ | 02-9900000"
MIRIAM = Person("מרים כהן", "miriam.cohen@ofek-office.example",
                sig=_OFEK_SIG.format(name="מרים כהן", role="מנהלת המשרד").strip("\n"),
                quote="outlook_he", encoding="utf8-qp")
SARA = Person("שרה גולדברג", "sara.goldberg@ofek-office.example", quote="gmail_he")
RACHELI = Person("רחלי פרידמן", "racheli.friedman@ofek-office.example", quote="gmail_he")
ESTY = Person("אסתי רוזן", "esty.rosen@ofek-office.example", quote="gmail_he")
ESTY_PRIVATE = Person("Esty Rosen", "esty.rosen85@example.com", quote="gmail_he",
                      sig="נשלח מה-iPhone שלי")
HADRACHA = Person("רכזת הדרכה - אופק", "training@ofek-office.example")
IT_SUPPORT = Person("Ofek IT Support", "it@ofek-office.example")
KLEIN = Person("Daniel Klein", "daniel@klein-imports.example",
               sig="--\nDaniel Klein | CFO\nKlein Imports Ltd.", quote="outlook_en")
OLD_JOB = Person("משרד רו\"ח שפירא", "office@shapira-cpa.example")
TEAM = [SARA, RACHELI, ESTY, CHANI]

# ---------- ילדים ----------
GAN = Person("גננת חיה - גן שושנים", "gan.shoshanim@example.com",
             encoding="cp1255-qp", subject_charset="windows-1255")
GAN_PARENTS = Person("הורי גן שושנים", "horei-gan-shoshanim@groups.example")
SHIRA_MOM = Person("'אמא של שירה' via הורי גן שושנים", "horei-gan-shoshanim@groups.example")
MOSHE_TT = Person("משה כהן", "m.cohen@orchot-tt.example",
                  sig="בברכה,\nהרב משה כהן\nמלמד כיתה א׳, ת\"ת אורחות חיים", quote="gmail_he")
TT_OFFICE = Person("מזכירות ת\"ת אורחות חיים", "office@orchot-tt.example")
TT_PAY = Person("מערכת תשלומים - אורחות חיים", "pay@orchot-tt.example")
TT_PARENTS = Person("הורי כיתה א׳", "kita-alef@orchot-tt.example")
TIPAT_CHALAV = Person("טיפת חלב רמת אברהם", "tipat-chalav@briut.example")
TZIPI = Person("ציפי - חוג ציור", "tzipi.art@example.com")

# ---------- משפחה ----------
IMA = Person("רבקה שטרן", "rivka.stern@example.com", encoding="utf8-8bit")
SHIMON = Person("שמעון שטרן", "shimon.stern@example.com")
REUVEN = Person("ראובן פרידמן", "reuven.friedman@example.com")   # מופיע רק בתוך העברה
LEAH = Person("Leah Weiss", "leah.weiss@example.com", quote="gmail_en")
SHOSHANA = Person("שושנה לוין", "shoshana.levin@example.com")
GITI = Person("גיטי לוין", "giti.levin@example.com")
DOV_GREEN = Person("דב גרין", "dov.green@example.com")           # מופיע רק בתוך העברה
FAMILY_STERN = [IMA, SHIMON, LEAH]

# ---------- הזמנות ומנויים ----------
SHOPNEST = Person("ShopNest", "orders@shopnest.example")
SHOPNEST_SUPPORT = Person("ShopNest Support", "support@shopnest.example",
                          sig="--\nShopNest Customer Care", quote="gmail_en")
SHOPNEST_PROMO = Person("ShopNest Deals", "deals@shopnest.example")
KIDSTALES = Person("KidsTales", "billing@kidstales.example")
SHEFA = Person("שפע - משלוחי מזון", "orders@shefa-delivery.example")
OLAM_HASEFER = Person("עולם הספר", "orders@olam-hasefer.example")
ZIMMER = Person("צימרים נוף הגליל", "booking@nof-hagalil.example", quote="he_wrote")
MAGAZINE = Person("שבועון הבית שלנו - מנויים", "manuy@habayit-shelanu.example")

# ---------- שונות ----------
KEHILA = Person("קהילת אוהל שרה", "news@ohel-sara.example")
PNINA = Person("פנינה אדלר", "pnina.adler@example.com")
NEIGHBORS = Person("שכנות הנרקיס", "shchenot-narkis@groups.example")
GMACH = Person("גמ\"ח מוצרי תינוקות - בית שמש", "gmach.baby.bs@example.com")
SCAM_BILLING = Person("מחלקת גבייה", "billing@rent-pay-center.example")
SCAM_SHOPNEST = Person("ShopNest Refunds", "refunds@shopnest-help.example")
LOTTERY = Person("הגרלת הענק", "winner@mega-prize.example")
