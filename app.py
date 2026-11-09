"""
ממשק Streamlit בצורת שיחה: שאלות המשך מובנות לפי ההקשר, התשובה מוזרמת, ומתחתיה רק המקורות שצוטטו.
סרגל הצד: בחירת תיבה ומסננים. בהגדרות: עדכון האינדקס, הרשימה השחורה והוספת תיבה.
הרצה: streamlit run app.py (או לחיצה כפולה על הפעלה.bat)
"""
from datetime import date, datetime
import json
import re
from urllib.parse import quote

import streamlit as st

import config
from contacts import Contacts
from indexer import index_mailbox, label_stats
import llm_setup
from mail_filters import Blacklist, load_blacklist, save_blacklist
from pipeline import plan, search
from qa import (answer_stream, cited, find, is_aggregate, is_find, safe_markdown, split_followups,
                split_suspicious)
from retriever import Filters, get_thread
import store

st.set_page_config(page_title="חיפוש בתיבת המייל", page_icon="📬", layout="wide")
st.markdown("<style>.stApp, .stMarkdown, .stTextInput input, textarea {direction: rtl; text-align: right}</style>",
            unsafe_allow_html=True)


def fmt(d: int) -> str:
    return f"{d % 100:02d}.{d // 100 % 100:02d}.{d // 10000}" if d else "?"


def as_int(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def queue(q: str, address: str = "", skip_contacts: bool = False) -> None:
    """כפתורים (שאלות פתיחה, שאלות המשך, בחירת איש קשר) שולחים שאלה כאילו הוקלדה."""
    st.session_state.queued = {"q": q, "address": address, "skip_contacts": skip_contacts}


def friendly_error(e: Exception) -> str:
    text = f"{type(e).__name__} {e}"
    if any(s in text for s in ("503", "UNAVAILABLE", "overloaded", "high demand")):
        return "השרת של ספק ה-AI עמוס כרגע (ניסיתי שוב כמה פעמים). אפשר לנסות שוב בעוד דקה."
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return "הגענו למכסת השימוש של ספק ה-AI. אפשר לנסות שוב בעוד דקה (או מחר, אם זו המכסה היומית)."
    if any(s in text for s in ("SSL", "Connect", "Timeout", "certificate")):
        return "לא הצלחתי להתחבר לשרת של ספק ה-AI. ייתכן שזה הסינון של נטפרי, או שהחיבור לאינטרנט נפל."
    return "משהו השתבש בזמן החיפוש. אפשר לנסות שוב, ואם זה חוזר, הפרטים הטכניים כאן למטה."


# ---------------------------------------------------------------- הגדרות
def blacklist_editor() -> None:
    bl = load_blacklist()
    fields = {"senders": "כתובות", "sender_domains": "דומיינים", "keywords": "מילות מפתח"}
    values = {k: st.text_area(label, "\n".join(getattr(bl, k)), height=120) for k, label in fields.items()}
    if st.button("שמירת הרשימה השחורה"):
        save_blacklist(Blacklist(**{k: [x.strip() for x in v.splitlines() if x.strip()] for k, v in values.items()}))
        st.success("נשמר. ייכנס לתוקף בעדכון האינדקס הבא, ומיילים שכבר באינדקס יוסרו.")


def add_mailbox_form() -> None:
    new = st.text_input("שם התיבה (אנגלית, בלי רווחים)", key="new_name")
    mbox = st.text_input("נתיב לקובץ mbox (ייצוא Google Takeout)", key="new_mbox")
    if st.button("בדיקת תוויות") and re.fullmatch(r"[a-z0-9_-]+", new) and mbox:
        st.session_state.labels = (new, mbox, *label_stats({"mbox": mbox}))
    if not new or st.session_state.get("labels", ("",))[0] != new:
        return
    _, mbox, labels, mine, total = st.session_state.labels
    st.write(f"{total} הודעות. מוחרגות: {sorted(config.EXCLUDED_LABELS)} | יוצא: {config.SENT_LABEL}")
    st.dataframe({"תווית": list(labels), "מיילים": list(labels.values())}, height=200)
    addresses = st.text_input("הכתובות שלי (מופרדות בפסיק)", ", ".join(mine))
    addressing = {"בלי פנייה מגדרית": "", "לשון נקבה": "נקבה", "לשון זכר": "זכר"}[
        st.radio("איך התשובות יפנו אליך?", ["בלי פנייה מגדרית", "לשון נקבה", "לשון זכר"], horizontal=True)]
    provider = st.radio("ספק AI", list(config.MODELS), list(config.MODELS).index(config.PRIVATE_PROVIDER), horizontal=True,
                        help="ב-API של OpenAI התוכן לא משמש לאימון. ב-Gemini החינמי הוא כן.")
    if st.checkbox("שמות התוויות ב-config.py נכונים לתיבה הזו") and st.button("שמירה ואינדוקס"):
        info = {"mbox": mbox, "my_addresses": [a.strip() for a in addresses.split(",") if a.strip()],
                "labels_checked": True, "addressing": addressing, "provider": provider}
        store.save_info(new, info)
        run_indexing(new, info)


def run_indexing(name: str, info: dict) -> None:
    with st.status(f"מאנדקס את {name}...") as status:
        try:
            index_mailbox(name, info, log=st.write)
            status.update(label="האינדוקס הסתיים", state="complete")
        except RuntimeError as e:
            status.update(label="האינדוקס נכשל", state="error")
            st.error(str(e))


# ---------------------------------------------------------------- סרגל צד
with st.sidebar:
    name = st.selectbox("תיבה", store.list_mailboxes())
    info = store.load_info(name)
    chat = st.session_state.setdefault("chats", {}).setdefault(name, [])   # שיחה נפרדת לכל תיבה
    if st.button("🗒️ שיחה חדשה", use_container_width=True):
        chat.clear()
    st.subheader("מסננים")
    address = st.text_input("כתובת מייל").strip().lower()
    dates = st.date_input("טווח תאריכים", value=(), format="DD.MM.YYYY") if st.checkbox("סינון לפי תאריך") else ()
    kind = st.radio("סוג", ["הכל", "מיילים", "קבצים מצורפים"], horizontal=True)
    if st.toggle("⚙️ הגדרות"):
        if info and info.get("labels_checked") and st.button("עדכון האינדקס (מיילים חדשים)"):
            run_indexing(name, info)
        with st.expander("רשימה שחורה"):
            blacklist_editor()
        with st.expander("הוספת תיבה"):
            add_mailbox_form()

addressing = info.get("addressing", config.DEMO_ADDRESSING if name == config.DEMO_MAILBOX else "")
contacts = Contacts(config.mailbox_paths(name)["contacts"])
owner = ", ".join(f"{(c['canonical'] or (c['names'] or [a])[0])} <{a}>"   # מי מדבר עם הצ'אט: בעל התיבה
                  for a in info.get("my_addresses", []) if (c := contacts.data.get(a, {"canonical": "", "names": []})))
col = store.collection(name)
if not col.count():
    st.info(f"התיבה עוד לא אונדקסה. הריצו: python indexer.py --name {name}")
    st.stop()


# ---------------------------------------------------------------- הצגת תור בשיחה
def gmail_link(message_id: str) -> str:
    """קישור שלנו (לא מתוך המייל) לחיפוש ההודעה ב-Gmail לפי Message-ID, בחשבון של התיבה."""
    account = (info.get("my_addresses") or [""])[0]
    return f"https://mail.google.com/mail/?authuser={quote(account)}#search/rfc822msgid:{quote(message_id.strip('<>'))}"


def source_card(t: int, i: int, h, full: bool) -> None:
    m = h.node.metadata
    att = f" · 📎 {m['attachment_name']}" if m["node_type"] == "attachment" else ""
    with st.expander(f"[{i}] {fmt(m['date'])} · {m['from_name'] or m['from_email']} · {m['subject'] or '(ללא נושא)'}{att}",
                     expanded=full):
        if name != config.DEMO_MAILBOX:   # לתיבת הדמו אין Gmail
            st.link_button("פתיחה ב-Gmail", gmail_link(m["message_id"]))
        thread = get_thread(col, m["thread_id"])
        if full:   # ההודעה כולה
            st.text("\n".join(r["text"].split("\n\n", 1)[-1] for r in thread if r["meta"]["message_id"] == m["message_id"]))
        else:
            st.text(h.node.get_content().split("\n\n", 1)[-1][:800])   # st.text: בלי קישורים לחיצים
        if st.toggle("הצג את כל השרשור", key=f"thread{t}_{i}"):
            for row in thread:
                rm = row["meta"]
                st.markdown(f"**{fmt(rm['date'])} · {rm['from_name'] or rm['from_email']}**")
                st.text(row["text"].split("\n\n", 1)[-1])


def save_feedback(t: int) -> None:
    turn, rating = chat[t], st.session_state.get(f"fb{t}")
    path = config.mailbox_paths(name)["root"] / "feedback.jsonl"   # בתוך storage/: לא נכנס ל-git
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "question": turn["sq"],
                            "answer": turn.get("ans"), "good": rating == 1}, ensure_ascii=False) + "\n")


def details(t: int, turn: dict, follow: bool) -> None:
    """כל מה שמתחת לטקסט התשובה: אזהרות, שקיפות, מקורות, שאלות המשך (רק בתור האחרון) ומשוב."""
    res, picks = turn["res"], turn["picks"]
    if turn["kind"] == "answer" and is_aggregate(turn["sq"]):
        st.warning("שאלת סכימה או רשימה: החיפוש מחזיר רק את המיילים הרלוונטיים ביותר, ולכן התשובה עלולה להיות חלקית.")
    for i in picks:   # רק מה שצוטט בתשובה / ההודעה שנבחרה
        source_card(t, i, res.hits[i - 1], full=turn["kind"] == "find")
    rest = [i for i in range(1, len(res.hits) + 1) if i not in picks]
    only = f" (רק מה ש-{turn['from_only']} כתב/ה)" if turn.get("from_only") else ""
    st.caption(f"חיפשתי ב-{res.n_messages} מיילים{only}, בטווח {fmt(res.date_min)} עד {fmt(res.date_max)}.")
    if rest and st.toggle(f"תוצאות נוספות שנשלפו ({len(rest)})", key=f"more{t}"):
        for i in rest:
            source_card(t, i, res.hits[i - 1], full=False)
    if turn["flagged"]:
        st.warning(f"⚠️ {len(turn['flagged'])} מיילים חשודים (פונים למערכת ה-AI או מבקשים פרטי אשראי / סיסמה) "
                   "לא נכללו בתשובה. לא ללחוץ על קישורים בהם: " +
                   "; ".join(f"{fmt(h.node.metadata['date'])} · {h.node.metadata['from_email']} · {h.node.metadata['subject']}"
                             for h in turn["flagged"]))
    if follow and turn.get("follow"):
        cols = st.columns(len(turn["follow"]))
        for j, (c, fq) in enumerate(zip(cols, turn["follow"])):
            c.button(fq, key=f"fu{t}_{j}", on_click=queue, args=(fq,), use_container_width=True)
    st.feedback("thumbs", key=f"fb{t}", on_change=save_feedback, args=(t,))


def show_turn(t: int, turn: dict, follow: bool) -> None:
    with st.chat_message("user"):
        st.text(turn["q"])
    with st.chat_message("assistant"):
        if turn["kind"] == "error":
            st.error(turn["ans"])
            with st.expander("פרטים טכניים"):
                st.code(turn["detail"])
            return
        if turn["kind"] == "clarify":
            st.markdown(turn["ans"])
            for j, (label, a) in enumerate(turn["options"].items()):
                st.button(label, key=f"cl{t}_{j}", on_click=queue, args=(turn["q"], a, True))
            return
        if turn["sq"] != turn["q"]:
            st.caption(f"הבנתי את השאלה כך: {turn['sq']}")
        if turn["kind"] == "find":
            st.markdown("**זו ההודעה שחיפשת:**" if turn["picks"] else "לא מצאתי הודעה שמתאימה לבקשה.")
        else:
            st.markdown(safe_markdown(turn["ans"]))
        details(t, turn, follow)


# ---------------------------------------------------------------- תור חדש
def run_turn(job: dict) -> None:
    q = job["q"]
    turn = {"q": q, "sq": q}
    with st.chat_message("user"):
        st.text(q)
    try:
        llm_setup.setup_models(info.get("provider"))
        history = [(x["sq"], x["ans"]) for x in chat if x["kind"] == "answer"]
        base = Filters(address=job.get("address") or address,
                       node_type={"מיילים": "email", "קבצים מצורפים": "attachment"}.get(kind, ""),
                       date_from=as_int(dates[0]) if len(dates) == 2 else 0, date_to=as_int(dates[1]) if len(dates) == 2 else 0)
        with st.spinner("רגע, מחפש במיילים..."):
            p = plan(q, history, owner, contacts, base, llm_setup.fast_llm, job.get("skip_contacts", False))
        turn |= {"sq": p.sq, "from_only": p.from_name}
        sq = p.sq
        if p.ambiguous:   # שם שמתאים לכמה אנשים: המשתמש בוחר
            options = {f"{(c['names'] or [c['canonical']])[0]} ({a})": a for a, c in p.ambiguous} | {"כולם": ""}
            chat.append({**turn, "kind": "clarify", "ans": "השם מתאים לכמה אנשי קשר. למי הכוונה?", "options": options})
            st.rerun()
        with st.spinner("רגע, מחפש במיילים..."):
            res = search(col, p)
            res.hits, flagged = split_suspicious(res.hits)
        turn |= {"res": res, "flagged": flagged}
        if is_find(q):   # "תמצא לי...": ההודעה עצמה, בלי תשובה כתובה
            turn |= {"kind": "find", "ans": "", "picks": find(sq, res.hits)}
            chat.append(turn)
            st.rerun()
        with st.chat_message("assistant"):
            if sq != q:
                st.caption(f"הבנתי את השאלה כך: {sq}")
            out = {}
            st.write_stream(safe_markdown(c) for c in answer_stream(sq, res.hits, addressing, out, owner=owner, history=history))
            body, follow = split_followups(out["full"])
            turn |= {"kind": "answer", "ans": body, "follow": follow, "picks": cited(body, len(res.hits))}
            chat.append(turn)
            details(len(chat) - 1, turn, follow=True)
    except Exception as e:
        if type(e).__name__ in ("RerunException", "StopException"):
            raise
        chat.append({**turn, "kind": "error", "ans": friendly_error(e), "detail": f"{type(e).__name__}: {e}"})
        st.rerun()


# ---------------------------------------------------------------- עמוד
st.title("📬 חיפוש בתיבת המייל")
if not chat:
    st.markdown("אפשר לשאול כל דבר על המיילים, בשפה חופשית: מתי, מה סוכם, מי שלח, או \"תמצא לי את...\".")
    starters = config.STARTERS.get(name, config.STARTERS["default"])
    for c, sq in zip(st.columns(len(starters)), starters):
        c.button(sq, on_click=queue, args=(sq,), use_container_width=True)
typed = st.chat_input("מה תרצו לדעת על המיילים?")
job = st.session_state.pop("queued", None) or ({"q": typed} if typed else None)
for t, turn in enumerate(chat):   # שאלות המשך רק לתור האחרון, וכשאין שאלה חדשה בדרך
    show_turn(t, turn, follow=t == len(chat) - 1 and not job)
if job:
    run_turn(job)
