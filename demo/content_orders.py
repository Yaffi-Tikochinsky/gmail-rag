"""מיילים: הזמנות ומנויים. חנות באנגלית (הזמנה שהגיעה + הזמנה שבוטלה), אתרים בעברית, צימר, מנויים."""
from people import *
from spec import Att, Mail

L_UPD = ["Inbox", "Opened", "Category Updates"]
L_PURCHASE = ["Inbox", "Opened", "Category Updates", "Purchases"]


def shopnest_html(title: str, rows: str, footer: str) -> str:
    return f"""<html><body style="font-family:Helvetica,Arial;color:#222">
<table width="600" align="center" cellpadding="0" cellspacing="0">
<tr><td style="background:#ff6a3d;color:#fff;padding:16px;font-size:22px"><b>ShopNest</b></td></tr>
<tr><td style="padding:20px"><h2>{title}</h2>{rows}<p style="color:#777;font-size:12px">{footer}</p></td></tr>
</table></body></html>"""


MAILS = [
    # ---------- הזמנה א': עגלה, שהגיעה ----------
    Mail("shopnest-stroller-1", "2025-10-14 22:31", SHOPNEST, [CHANI_EN], "Your ShopNest order #SN-48213 is confirmed",
         body="""Hi Chani,
Thanks for your order!
Order #SN-48213
- Compact Travel Stroller, Navy - $229.00
Shipping to: 12 HaNarkis St., Apt 4, Beit Shemesh, Israel
Estimated delivery: Oct 28 - Nov 3""",
         html=shopnest_html("Thanks for your order!",
                            "<p>Order <b>#SN-48213</b></p><table><tr><td>Compact Travel Stroller, Navy</td>"
                            "<td>$229.00</td></tr></table><p>Estimated delivery: <b>Oct 28 - Nov 3</b></p>",
                            "You received this email because you placed an order on ShopNest."),
         labels=L_PURCHASE, note="multipart/alternative: גם טקסט וגם HTML. באנגלית."),
    Mail("shopnest-stroller-2", "2025-10-21 06:12", SHOPNEST, [CHANI_EN], "Your order #SN-48213 has shipped",
         html=shopnest_html("Your package is on its way",
                            "<p>Order <b>#SN-48213</b> has shipped with IsraelPost Express.</p>"
                            "<p>Tracking number: <b>EX123456789IL</b></p><p>Expected delivery: <b>Sunday, Nov 2</b></p>",
                            "Track your package in the ShopNest app."),
         labels=L_PURCHASE, note="HTML בלבד. מועד מסירה צפוי: 2.11."),
    Mail("shopnest-stroller-3", "2025-11-02 14:40", SHOPNEST, [CHANI_EN], "Delivered: your ShopNest order #SN-48213",
         html=shopnest_html("Your package was delivered",
                            "<p>Order <b>#SN-48213</b> was delivered on Nov 2 at 14:20.</p>"
                            "<p>Left with: neighbor, apartment 7.</p>",
                            "Questions? Contact support@shopnest.example"),
         labels=L_PURCHASE, note="ההזמנה נמסרה לשכנה בדירה 7."),

    # ---------- הזמנה ב': כסא אוכל, שבוטלה. שרשור בלי X-GM-THRID ----------
    Mail("shopnest-chair-1", "2026-08-20 21:15", SHOPNEST, [CHANI_EN], "Your ShopNest order #SN-61007 is confirmed",
         html=shopnest_html("Thanks for your order!",
                            "<p>Order <b>#SN-61007</b></p><table><tr><td>Convertible High Chair, Grey</td>"
                            "<td>$189.00</td></tr></table><p>Estimated delivery: <b>Sep 3 - Sep 9</b></p>",
                            "You received this email because you placed an order on ShopNest."),
         labels=L_PURCHASE),
    Mail("shopnest-chair-2", "2026-08-21 09:40", CHANI_EN, [SHOPNEST_SUPPORT], "Cancel order SN-61007",
         """Hello,
Please cancel order SN-61007 (Convertible High Chair). I found one at a local gemach.
Thank you,
Chani Levin""",
         no_thrid=True, note="שרשור בלי X-GM-THRID: ה-thread_id צריך לבוא מ-References."),
    Mail("shopnest-chair-3", "2026-08-21 13:05", SHOPNEST_SUPPORT, [CHANI_EN], "Re: Cancel order SN-61007",
         """Hi Chani,
Your order SN-61007 has been cancelled. A refund of $189.00 will be issued to your original payment method within 5-7 business days.""",
         reply_to="shopnest-chair-2", no_thrid=True, labels=L_PURCHASE,
         note="ההזמנה בוטלה. ציטוט Gmail באנגלית עם '>'."),
    Mail("shopnest-chair-4", "2026-08-27 10:00", SHOPNEST, [CHANI_EN], "Refund processed for order #SN-61007",
         html=shopnest_html("Your refund is on its way",
                            "<p>We refunded <b>$189.00</b> to your Visa card for order <b>#SN-61007</b>.</p>"
                            "<p>It may take a few days to appear on your statement.</p>", ""),
         labels=L_PURCHASE, note="מידע שהתעדכן: הזמנה שבוטלה, והכסף הוחזר."),

    # ---------- אתרים בעברית ----------
    Mail("school-supplies", "2026-08-10 19:20", OLAM_HASEFER, [CHANI], "אישור הזמנה 20931 - עולם הספר",
         html="""<div dir="rtl" style="font-family:Arial">
<h3>תודה שקנית בעולם הספר!</h3>
<p>מספר הזמנה: <b>20931</b></p>
<table border="1" cellpadding="3" style="border-collapse:collapse">
<tr><th>מוצר</th><th>כמות</th><th>מחיר</th></tr>
<tr><td>ילקוט אורתופדי כחול</td><td>1</td><td>189 ש"ח</td></tr>
<tr><td>קלמר כפול</td><td>1</td><td>35 ש"ח</td></tr>
<tr><td>מחברות שורה 40 דף</td><td>10</td><td>48 ש"ח</td></tr>
<tr><td>עפרונות וצבעים - ערכה</td><td>1</td><td>40 ש"ח</td></tr>
</table>
<p>סה"כ: <b>312 ש"ח</b>. משלוח עד הבית ביום שלישי 18.8.2026.</p></div>""",
         labels=L_PURCHASE, note="HTML בלבד בעברית, עם טבלה."),
    Mail("shefa-order", "2026-10-28 13:00", SHEFA, [CHANI], "ההזמנה שלך לחמישי 29.10 התקבלה",
         html="""<div dir="rtl" style="font-family:Arial">
<p>שלום חני,</p>
<p>ההזמנה שלך התקבלה ותגיע ביום חמישי 29.10.2026 בין 14:00 ל-18:00.</p>
<ul><li>עוף שלם x2</li><li>חלות x4</li><li>ירקות לשבת - סל משפחתי</li><li>חלב 3% x6</li></ul>
<p>סה"כ לתשלום: 486.90 ש"ח</p>
<p>שפע - משלוחי מזון כשרים</p></div>""",
         labels=L_PURCHASE),
    Mail("shefa-otp", "2026-10-27 22:14", SHEFA, [CHANI], "קוד אימות לכניסה לחשבון",
         "קוד אימות: 482913\nאל תמסרי את הקוד לאף אחד.",
         labels=["Inbox", "Category Updates"], expect="excluded:blacklist",
         note="קוד אימות (מילת מפתח בנושא): אסור שיאונדקס."),

    # ---------- צימר: הזמנה ושינוי תאריכים ----------
    Mail("zimmer-1", "2026-07-01 11:00", ZIMMER, [CHANI], "אישור הזמנה - צימר נוף הגליל",
         """שלום חני,
הזמנתך אושרה!
צימר "גפן" (משפחתי, 6 מיטות), 3.8.2026 עד 6.8.2026, שלושה לילות.
מחיר: 2,700 ש"ח. מקדמה של 500 ש"ח שולמה, היתרה תשולם בהגעה.
כניסה מ-15:00, יציאה עד 11:00. כתובת: מושב אמירים, רחוב הגפן 4.
ביטול חינם עד 14 יום לפני ההגעה.""",
         labels=L_PURCHASE),
    Mail("zimmer-2", "2026-07-20 21:30", CHANI, [ZIMMER], "Re: אישור הזמנה - צימר נוף הגליל",
         "שלום, אפשר לשנות לתאריכים 10.8 עד 13.8? אותו צימר.",
         reply_to="zimmer-1"),
    Mail("zimmer-3", "2026-07-21 09:15", ZIMMER, [CHANI], "Re: אישור הזמנה - צימר נוף הגליל",
         "שונה. צימר גפן, 10.8.2026 עד 13.8.2026. המחיר והמקדמה ללא שינוי.",
         reply_to="zimmer-2", labels=L_PURCHASE,
         note="מידע שהתעדכן: התאריכים הוזזו מ-3-6.8 ל-10-13.8."),

    # ---------- מנויים ----------
    Mail("kidstales-renewal", "2026-01-05 15:00", KIDSTALES, [CHANI_EN], "Your KidsTales subscription renews on January 20",
         """Hi Chani,
Your KidsTales Family plan renews on January 20, 2026 for $7.99/month.
Your kids listened to 34 stories last month! Top story: "The Lost Lamb".""",
         labels=L_UPD),
    Mail("kidstales-price", "2026-06-01 15:00", KIDSTALES, [CHANI_EN], "An update to your KidsTales plan price",
         """Hi Chani,
Starting July 1, 2026, the KidsTales Family plan will cost $9.99/month (was $7.99).
No action is needed to keep your plan. You can cancel anytime in Settings.""",
         labels=L_UPD, note="מידע שהתעדכן: המחיר עולה ל-9.99 מיולי 2026."),
]
