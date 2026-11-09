"""
אינדוקס של תיבה: reader -> parser -> filters -> cleaner -> node_builder -> Chroma.
עדכון אינקרמנטלי לפי Message-ID: מייל שכבר באינדקס לא נשלח שוב ל-embedding.

  python indexer.py                              # תיבת הדמו
  python indexer.py --name work --mbox <קובץ>    # תיבה חדשה (קודם --list-labels)
  python indexer.py --name work --list-labels    # בדיקת שמות התוויות (חובה לפני אינדוקס ראשון)
  python indexer.py --dry-run                    # הכל חוץ מקריאות API: סטטיסטיקה והיקף
"""
import argparse
from collections import Counter
import sys
import time

from llama_index.core import Settings, VectorStoreIndex

from attachments import extract_attachment_text
from body_cleaner import clean_body
import config
from contacts import Contacts
from email_parser import parse_email
import llm_setup
from mail_filters import decide, index_cutoff, load_blacklist
from node_builder import build_nodes
from readers.mbox_reader import iter_raw_messages
import store

BATCH_NODES = 100
NETFREE_HINT = "אם זו שגיאת SSL, חיבור או חסימה, ייתכן שזה הסינון של נטפרי. לא עוקפים: לבדוק מולם."


def label_stats(info: dict) -> tuple[Counter, list[str], int]:
    """כמה מיילים בכל תווית, והכתובות שלי (שולח של לפחות 5% מהמיילים עם SENT_LABEL)."""
    labels, senders, total = Counter(), Counter(), 0
    for raw in iter_raw_messages(info["mbox"]):
        mail = parse_email(raw.data)
        total += 1
        labels.update(mail.labels)
        if config.SENT_LABEL in mail.labels:
            senders[mail.from_email] += 1
    sent = sum(senders.values())
    return labels, sorted(a for a, n in senders.items() if n / sent >= 0.05), total


def list_labels(name: str, info: dict, extra_addresses: list[str]) -> None:
    labels, mine, total = label_stats(info)
    print(f"{total} הודעות. תוויות:")
    for label, n in labels.most_common():
        mark = "  <- מוחרגת" if label in config.EXCLUDED_LABELS else ("  <- יוצא" if label == config.SENT_LABEL else "")
        print(f"  {n:>7}  {label}{mark}")
    missing = [l for l in [*config.EXCLUDED_LABELS, config.SENT_LABEL] if l not in labels]
    if missing:
        print(f"\nשימו לב: התוויות האלה מ-config לא נמצאו בתיבה: {missing}")

    info["my_addresses"] = sorted(set(mine + extra_addresses))
    print(f"\nהכתובות שלי (מהשולח של מיילים עם {config.SENT_LABEL}): {info['my_addresses']}")
    print("לתיקון: --my-address <כתובת>")

    answer = input("\nהאם EXCLUDED_LABELS ו-SENT_LABEL ב-config.py נכונים לתיבה הזו? (y/n): ")
    info["labels_checked"] = answer.strip().lower() in ("y", "yes", "כ", "כן")
    store.save_info(name, info)
    print("נשמר. אפשר לאנדקס." if info["labels_checked"] else "עדכנו את config.py והריצו שוב.")


def _insert(index, batch, log, tries: int = 5) -> None:
    """מכסה לדקה (במסלול החינמי: 100 embeddings): ממתינים ומנסים שוב. ה-embedding קודם לכתיבה, אז אין כתיבה חלקית."""
    for i in range(tries):
        try:
            return index.insert_nodes(batch)
        except Exception as e:
            if "429" not in str(e) or i == tries - 1:
                raise
            log("  מכסת הדקה נוצלה. ממתין 60 שניות...")
            time.sleep(60)


def index_mailbox(name: str, info: dict, dry_run: bool = False, limit: int | None = None,
                  rebuild: bool = False, log=print, refresh_aliases: bool = False) -> Counter:
    blacklist, cutoff = load_blacklist(), index_cutoff()
    col = None if dry_run else store.collection(name)
    if col is not None and rebuild:   # מוחקים את כל האוסף: מודל embedding חדש יכול להיות במימד אחר
        col = store.collection(name, drop=True)
    indexed = store.indexed_ids(col) if col is not None else set()

    contacts = Contacts(config.mailbox_paths(name)["contacts"])
    contacts.start_rebuild()
    if refresh_aliases:
        for c in contacts.data.values():
            c["canonical"] = ""   # ה-LLM ייצור לכולם שם וכינויים מחדש
    stats, seen, to_remove = Counter(), set(), []
    batches, current, new_count = [], [], 0

    for raw in iter_raw_messages(info["mbox"]):
        mail = parse_email(raw.data, info["my_addresses"], raw.envelope_date)
        if mail.message_id in seen:
            stats["כפילות"] += 1
            continue
        seen.add(mail.message_id)
        decision = decide(mail, blacklist, cutoff)
        if not decision.keep:
            stats[decision.reason.split(" (")[0]] += 1
            if mail.message_id in indexed:   # למשל נוסף לרשימה השחורה אחרי שאונדקס
                to_remove.append(mail.message_id)
            continue
        clean = clean_body(mail.body, mail.subject)
        contacts.add_mail(mail, clean)
        if mail.message_id in indexed:
            stats["כבר באינדקס"] += 1
            continue
        if limit is not None and new_count >= limit:
            stats["נדחה (--limit)"] += 1
            continue
        nodes = build_nodes(mail, clean, [(a, extract_attachment_text(a)) for a in mail.attachments])
        new_count += 1
        stats["חדש"] += 1
        current += nodes   # מייל אחד לא מתפצל בין אצוות: אם הריצה נקטעת, אין מייל שאונדקס חלקית
        if len(current) >= BATCH_NODES:
            batches.append(current)
            current = []
    if current:
        batches.append(current)

    nodes = [n for b in batches for n in b]
    log(f"תיבה: {name} | {sum(stats.values())} הודעות")
    for k, v in stats.most_common():
        log(f"  {v:>6}  {k}")
    log(f"Nodes חדשים: {len(nodes)} (מיילים: {sum(n.metadata['node_type'] == 'email' for n in nodes)}, "
          f"קבצים: {sum(n.metadata['node_type'] == 'attachment' for n in nodes)}), "
          f"{sum(len(n.text) for n in nodes):,} תווים ל-embedding")
    log(f"אנשי קשר: {sum(1 for c in contacts.data.values() if c['count'])}")
    contacts.save()
    if dry_run:
        log("(dry run: לא נשלח כלום ל-API ולא נכתב לאינדקס)")
        return stats

    if to_remove:
        col.delete(where={"message_id": {"$in": to_remove}})
        log(f"הוסרו מהאינדקס {len(to_remove)} מיילים שכבר לא עוברים את הסינון")
    try:
        llm_setup.setup_models(store.provider(name))
        index = VectorStoreIndex.from_vector_store(store.vector_store(col))
        for i, batch in enumerate(batches, 1):
            _insert(index, batch, log)
            log(f"  אצווה {i}/{len(batches)}: {len(batch)} nodes")
        log(f"אנשי קשר שקיבלו שם וכינויים מה-LLM: {contacts.enrich_with_llm(Settings.llm)}")
        contacts.save()
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {e}\n{NETFREE_HINT}") from e
    log(f"באינדקס עכשיו: {col.count()} nodes")
    return stats


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")   # עברית בטרמינל של Windows
    ap = argparse.ArgumentParser(description="אינדוקס תיבת מייל")
    ap.add_argument("--name", default=config.DEMO_MAILBOX)
    ap.add_argument("--mbox", help="קובץ mbox (לתיבה חדשה, או כדי לעדכן נתיב)")
    ap.add_argument("--list-labels", action="store_true")
    ap.add_argument("--my-address", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, help="מקסימום מיילים חדשים בריצה (לבדיקה זולה)")
    ap.add_argument("--rebuild", action="store_true", help="מחיקת האינדקס ובנייה מחדש")
    ap.add_argument("--refresh-aliases", action="store_true", help="יצירת הכינויים של אנשי הקשר מחדש (למשל שמות חיבה)")
    ap.add_argument("--provider", choices=list(config.MODELS), help="ספק לתיבה (תיבה חדשה: openai)")
    args = ap.parse_args()

    info = store.load_info(args.name)
    if args.mbox:
        info = {**(info or {"my_addresses": [], "labels_checked": False, "provider": config.PRIVATE_PROVIDER}),
                "mbox": args.mbox}
        store.save_info(args.name, info)
    if info and args.provider:
        info["provider"] = args.provider
        store.save_info(args.name, info)
    if info is None:
        sys.exit(f"תיבה לא מוכרת: {args.name}. תיבה חדשה: --name {args.name} --mbox <קובץ>")
    if args.my_address and not args.list_labels:
        info["my_addresses"] = sorted(set(info["my_addresses"] + args.my_address))
        store.save_info(args.name, info)

    if args.list_labels:
        list_labels(args.name, info, args.my_address)
    elif not info["labels_checked"]:
        sys.exit(f"קודם בודקים את שמות התוויות: python indexer.py --name {args.name} --list-labels")
    else:
        try:
            index_mailbox(args.name, info, args.dry_run, args.limit, args.rebuild, refresh_aliases=args.refresh_aliases)
        except RuntimeError as e:
            sys.exit(f"שגיאה: {e}")


if __name__ == "__main__":
    main()
