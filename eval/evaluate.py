"""
הערכת האחזור על תיבת הדמו: hit rate ו-MRR, והשוואה בין שתי אסטרטגיות chunking.
  message: כל הודעה היא Node (מה שהמערכת משתמשת בו).
  thread:  כל שרשור הוא מסמך אחד. נבנה כאן מה-Nodes של message, באוסף נפרד (gmail_thread_*).
כדי שההשוואה תהיה הוגנת, ההתאמה בשתיהן היא ברמת השרשור. ב-message נמדדת גם ההודעה המדויקת.
embedding לכל שאלה (ול-thread פעם אחת לבניית האוסף). "המערכת המלאה" כמו בממשק: גם קריאת LLM מהירה לכתיב שמות,
ועדיפות לאיש קשר שהוזכר.
הרצה (מתיקיית gmail_rag, אחרי python indexer.py):  python eval/evaluate.py
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import QueryBundle, TextNode

import config
from indexer import _insert
import llm_setup
from contacts import Contacts
import pipeline
from qa import split_suspicious
from retriever import Filters, retrieve
import store

HERE = Path(__file__).resolve().parent
K = config.TOP_K


def mid(key: str) -> str:
    return f"<{key}@mail.demo.example>"


def thread_collection(msg_col):
    col = store.collection(config.DEMO_MAILBOX, "thread", drop=True)   # תמיד מחדש: אחרת נשאר אוסף של תוכן ישן
    r = msg_col.get(include=["documents", "metadatas"])
    threads, nodes = {}, []
    for d, m in sorted(zip(r["documents"], r["metadatas"]), key=lambda x: (x[1]["ts"], x[1]["chunk"])):
        if m["node_type"] == "email":
            threads.setdefault(m["thread_id"], []).append(d)
        else:   # קבצים מצורפים נשארים Node נפרד, כמו ב-message
            nodes.append(TextNode(text=d, metadata={"thread_id": m["thread_id"]}, excluded_embed_metadata_keys=["thread_id"]))
    splitter = SentenceSplitter(chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP)
    nodes += [TextNode(text=c, metadata={"thread_id": t}, excluded_embed_metadata_keys=["thread_id"])
              for t, docs in threads.items() for c in splitter.split_text("\n\n---\n\n".join(docs))]
    index = VectorStoreIndex.from_vector_store(store.vector_store(col))
    for i in range(0, len(nodes), 90):
        _insert(index, nodes[i:i + 90], print)
    print(f"נבנה אוסף thread: {len(threads)} שרשורים, {len(nodes)} nodes")
    return col


def rank(metas: list[dict], key: str, gold: set) -> int:
    return next((i for i, m in enumerate(metas, 1) if m[key] in gold), 0)


def main() -> None:
    llm_setup.setup_models(store.provider(config.DEMO_MAILBOX))   # האוסף של הספק שהתיבה מוגדרת אליו
    contacts = Contacts(config.mailbox_paths(config.DEMO_MAILBOX)["contacts"])
    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    msg_col = store.collection(config.DEMO_MAILBOX)
    meta = {m["message_id"]: m for m in msg_col.get(include=["metadatas"])["metadatas"]}
    thr_col = thread_collection(msg_col)
    raw = {s: VectorStoreIndex.from_vector_store(store.vector_store(c)).as_retriever(similarity_top_k=K)
           for s, c in [("message", msg_col), ("thread", thr_col)]}

    rows, ranks, checks = [], {k: [] for k in ["message", "thread", "message_exact", "pipeline_exact"]}, []
    for item in questions:
        qb = QueryBundle(item["q"], embedding=llm_setup.patient(Settings.embed_model.get_query_embedding, item["q"]))
        if not item["gold"]:
            if "flagged" in item:
                _, bad = split_suspicious(retrieve(msg_col, qb, Filters()).hits)
                checks.append((item, any(mid(item["flagged"]) == h.node.metadata["message_id"] for h in bad)))
            continue
        gold = {mid(k) for k in item["gold"]}
        gold_threads = {meta[g]["thread_id"] for g in gold}
        r = {s: [h.node.metadata for h in raw[s].retrieve(qb)] for s in raw}
        p = llm_setup.patient(pipeline.plan, item["q"], [], "", contacts, Filters(), llm_setup.fast_llm)   # כמו בממשק
        pipe = sorted(llm_setup.patient(pipeline.search, msg_col, p).hits, key=lambda h: -h.score)   # כולל העדפה לחדש ואיחוד
        row = {"message": rank(r["message"], "thread_id", gold_threads),
               "thread": rank(r["thread"], "thread_id", gold_threads),
               "message_exact": rank(r["message"], "message_id", gold),
               "pipeline_exact": rank([h.node.metadata for h in pipe], "message_id", gold)}
        for k, v in row.items():
            ranks[k].append(v)
        rows.append((item, row))

    names = {"message": "message (שרשור נכון)", "thread": "thread (שרשור נכון)",
             "message_exact": "message (הודעה מדויקת)", "pipeline_exact": "המערכת המלאה (הודעה מדויקת)"}
    out = [f"# תוצאות הערכה ({len(rows)} שאלות עם תשובה, top-{K})", "",
           "| אסטרטגיה | Hit rate | MRR |", "|---|---|---|"]
    out += [f"| {names[k]} | {sum(1 for x in v if x) / len(v):.2f} | {sum(1 / x for x in v if x) / len(v):.2f} |"
            for k, v in ranks.items()]
    out += ["", "| שאלה | סוג | message | thread | מדויק | מערכת |", "|---|---|---|---|---|---|"]
    out += [f"| {it['q']} | {it['type']} | " + " | ".join(str(row[k] or "✗") for k in ranks) + " |" for it, row in rows]
    out += ["", "בדיקות נוספות:"] + [f"- {it['q']} ({it['type']}): {'✓ סומן כחשוד ולא נשלח ל-LLM' if ok else '✗ לא סומן'}"
                                     for it, ok in checks]
    out += ["- שאלות בלי תשובה במאגר נבדקות ברמת התשובה ולא ברמת האחזור (ראו README)."]
    text = "\n".join(out)
    (HERE / "results.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
