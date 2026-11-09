"""
אחזור: חיפוש וקטורי ב-Chroma עם סינון אופציונלי, ודירוג מחדש עם העדפה קטנה למיילים חדשים.
סינון לפי כתובת: Chroma לא מחפש תת-מחרוזת ב-metadata, אז מוצאים ב-Python את ה-Nodes של הכתובת
ומעבירים ל-Chroma רשימת מזהים. כך הסינון מלא ומדויק, ולא רק על המועמדים שנשלפו.
"""
from dataclasses import dataclass
from datetime import date

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore, TextNode

import config
import store


@dataclass
class Filters:
    address: str = ""
    date_from: int = 0     # YYYYMMDD
    date_to: int = 0
    node_type: str = ""    # "email" / "attachment" / "" = הכל
    from_only: bool = False   # רק מה שהכתובת כתבה ("מה חדש משמעון"), בלי מיילים שנשלחו אליה
    person: str = ""          # איש קשר שהוזכר בשאלה: המיילים שלו נשלפים בנפרד ומקבלים עדיפות, בלי לסנן את השאר


@dataclass
class SearchResult:
    hits: list[NodeWithScore]   # ממוינים לפי תאריך
    n_messages: int             # כמה מיילים נכללו בחיפוש (אחרי הסינון)
    date_min: int
    date_max: int


def _involves(meta: dict, address: str, from_only: bool = False) -> bool:
    return address in meta.get("participants", "").split("|") + ([] if from_only else meta.get("recipients", "").split("|"))


def _where(f: Filters, metas: list[dict]) -> dict | None:
    conds = []
    if f.date_from:
        conds.append({"date": {"$gte": f.date_from}})
    if f.date_to:
        conds.append({"date": {"$lte": f.date_to}})
    if f.node_type:
        conds.append({"node_type": f.node_type})
    if f.address:
        ids = sorted({m["message_id"] for m in metas if _involves(m, f.address.lower(), f.from_only)})
        conds.append({"message_id": {"$in": ids or ["<none>"]}})
    return None if not conds else conds[0] if len(conds) == 1 else {"$and": conds}


def _recency_bonus(date_int: int, today: date) -> float:
    if not date_int:
        return 0.0
    d = date(date_int // 10000, date_int // 100 % 100, date_int % 100)
    return config.RECENCY_WEIGHT * 0.5 ** (max((today - d).days, 0) / config.RECENCY_HALF_LIFE_DAYS)


def scope(metas: list[dict], f: Filters) -> tuple[int, int, int]:
    """כמה מיילים ובאיזה טווח תאריכים החיפוש כיסה, בשביל שורת השקיפות בממשק."""
    ok = [m for m in metas
          if (not f.date_from or m["date"] >= f.date_from) and (not f.date_to or m["date"] <= f.date_to)
          and (not f.node_type or m["node_type"] == f.node_type) and (not f.address or _involves(m, f.address.lower(), f.from_only))]
    dates = [m["date"] for m in ok if m["date"]]
    return len({m["message_id"] for m in ok}), min(dates, default=0), max(dates, default=0)


def _merge(group: list[NodeWithScore]) -> NodeWithScore:
    """מייל אחד = מקור אחד: כל החלקים שנשלפו (גוף וקבצים מצורפים) תחת הכותרת של החלק הטוב ביותר.
    לא זורקים חלקים: לפעמים המידע נמצא רק בקובץ המצורף, גם כשהגוף קיבל ציון גבוה יותר."""
    top = group[0]
    if len(group) == 1:
        return top
    parts = sorted(group, key=lambda c: (c.node.metadata["node_type"] == "attachment", c.node.node_id))
    head = parts[0].node.get_content().split("\n\n", 1)[0]
    body = "\n\n".join(p.node.get_content().split("\n\n", 1)[-1] for p in parts)
    node = TextNode(id_=top.node.node_id, text=f"{head}\n\n{body}", metadata=dict(top.node.metadata),
                    excluded_embed_metadata_keys=top.node.excluded_embed_metadata_keys,
                    excluded_llm_metadata_keys=top.node.excluded_llm_metadata_keys)
    return NodeWithScore(node=node, score=top.score)


def retrieve(col, query: str, f: Filters, top_k: int = config.TOP_K, today: date | None = None,
             topic: str = "") -> SearchResult:
    """topic: הנושא בלבד ("השתלמות, קורס"). שאלה ארוכה עם שמות והקשר מטביעה את הנושא, אז מחפשים גם אותו לבד.
    ציון של שאילתה קצרה נמוך יותר, ולכן לתוצאות הטובות שלו שמורים מקומות (TOPIC_SLOTS), ולא רק מיזוג לפי ציון
    (problems_log 24)."""
    metas = col.get(include=["metadatas"])["metadatas"]
    index = VectorStoreIndex.from_vector_store(store.vector_store(col))

    def search(q, flt: Filters, bonus: float = 0.0) -> list[NodeWithScore]:
        r = index.as_retriever(similarity_top_k=config.CANDIDATE_K, vector_store_kwargs={"where": _where(flt, metas)})
        hits = r.retrieve(q)
        for h in hits:
            h.score = (h.score or 0.0) + bonus
        return hits

    hits = search(query, f)
    if f.person and not f.address:
        # בלי זה, "לאה" לא מוצאת את המיילים של Leah Weiss באנגלית. אבל לא מסננים: מדברים על אנשים גם במיילים של אחרים
        hits += search(query, Filters(**{**f.__dict__, "address": f.person, "person": ""}), config.PERSON_BOOST)
    on_topic = search(topic, f) if topic else []
    reserved = list(dict.fromkeys(h.node.metadata["message_id"] for h in on_topic))[:config.TOPIC_SLOTS]
    hits += on_topic
    best_by_id: dict[str, NodeWithScore] = {}
    for h in hits:
        if h.node.node_id not in best_by_id or h.score > best_by_id[h.node.node_id].score:
            best_by_id[h.node.node_id] = h
    candidates = list(best_by_id.values())
    today = today or date.today()
    for c in candidates:   # מייל חדש מקבל יתרון קטן על פני מייל ישן ודומה באותה מידה
        c.score = (c.score or 0.0) + _recency_bonus(c.node.metadata.get("date", 0), today)
    groups: dict[str, list[NodeWithScore]] = {}
    for c in sorted(candidates, key=lambda c: c.score, reverse=True):
        groups.setdefault(c.node.metadata["message_id"], []).append(c)
    order = list(groups)
    keep = [m for m in reserved if m in groups]
    keep += [m for m in order if m not in keep][:top_k - len(keep)]
    best = [_merge(groups[m]) for m in order if m in keep]
    # לפי תאריך, והודעות מאותו שרשור ברצף: רואים מי הציע, מי ענה ומה הוחלט
    first: dict[str, int] = {}
    for c in sorted(best, key=lambda c: c.node.metadata.get("ts", 0)):
        first.setdefault(c.node.metadata.get("thread_id", ""), c.node.metadata.get("ts", 0))
    best.sort(key=lambda c: (first[c.node.metadata.get("thread_id", "")], c.node.metadata.get("ts", 0)))
    return SearchResult(best, *scope(metas, f))


def get_thread(col, thread_id: str) -> list[dict]:
    """כל גופי ההודעות בשרשור, לפי סדר, לכפתור "הצג את כל השרשור"."""
    res = col.get(where={"$and": [{"thread_id": thread_id}, {"node_type": "email"}]}, include=["documents", "metadatas"])
    rows = sorted(zip(res["metadatas"], res["documents"]), key=lambda r: (r[0]["ts"], r[0]["chunk"]))
    return [{"meta": m, "text": t} for m, t in rows]
