"""
בניית Nodes מהודעה: Node לגוף (מפוצל ב-SentenceSplitter אם ארוך), ו-Node לכל קובץ מצורף.
הטקסט מתחיל בכותרת קצרה ("נושא | מאת | תאריך"). ה-metadata לא נכנס ל-embedding ולא ל-LLM: הכותרת כבר מכילה אותו.
"""
import re

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode

import config
from attachments import AttachmentText
from body_cleaner import CleanResult
from email_parser import Attachment, ParsedEmail

_splitter = SentenceSplitter(chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP)


def _who(name: str, addr: str) -> str:
    return name or addr


def header_line(mail: ParsedEmail, clean: CleanResult) -> str:
    parts = [f"נושא: {mail.subject or '(ללא נושא)'}", f"מאת: {_who(mail.from_name, mail.from_email)}"]
    if clean.forwarded_from:   # מי כתב כל הודעה מועברת: בתווית שלה בגוף
        parts.append("הודעות מועברות מאת: " + ", ".join(_who(n, a) for n, a in clean.forwarded_from))
    if mail.direction == "outgoing":   # בשביל "מה הבטחתי ל..."
        parts.append("אל: " + ", ".join(_who(n, a) for n, a in mail.to + mail.cc))
    if mail.date:
        parts.append(mail.date.strftime("%d.%m.%Y"))
    return " | ".join(parts)


def base_metadata(mail: ParsedEmail, clean: CleanResult) -> dict:
    participants = [mail.from_email] + [a for _, a in clean.forwarded_from]
    return {
        "message_id": mail.message_id,
        "thread_id": mail.thread_id,
        "date": mail.date_int,
        "ts": int(mail.date.timestamp()) if mail.date else 0,   # סדר בתוך יום
        "from_email": mail.from_email,
        "from_name": mail.from_name,
        "subject": mail.subject,
        "participants": "|".join(dict.fromkeys(a for a in participants if a)),
        "recipients": "|".join(dict.fromkeys(a for _, a in mail.to + mail.cc)),   # לסינון "מה שלחתי ל..."
        "direction": mail.direction,
        "fwd_writers": ", ".join(_who(n, a) for n, a in clean.forwarded_from),
        "labels": ",".join(mail.labels),
        "has_attachments": bool(mail.attachments),
    }


def _node(node_id: str, text: str, meta: dict) -> TextNode:
    keys = list(meta)
    return TextNode(id_=node_id, text=text, metadata=meta,
                    excluded_embed_metadata_keys=keys, excluded_llm_metadata_keys=keys)


LABEL = re.compile(r"^\[הודעה מועברת \d+ \|.*\]$", re.M)


def _with_labels(text: str, chunks: list[str]) -> list[str]:
    """קטע מאמצע הודעה מועברת מקבל את התווית שלה (מי כתב), אחרת אין דרך לדעת מי כתב אותו."""
    out, pos = [], 0
    for chunk in chunks:
        pos = max(text.find(chunk[:80], pos), pos)
        label = next((m.group(0) for m in reversed(list(LABEL.finditer(text))) if m.start() <= pos), "")
        out.append(f"{label[:-1]} | המשך]\n{chunk}" if label and not chunk.startswith(label) else chunk)
    return out


def build_nodes(mail: ParsedEmail, clean: CleanResult,
                atts: list[tuple[Attachment, AttachmentText]]) -> list[TextNode]:
    head = header_line(mail, clean)
    meta = base_metadata(mail, clean)
    nodes = []

    if clean.text or not atts:   # מייל ריק עם קובץ מצורף: רק ה-Node של הקובץ
        for i, chunk in enumerate(_with_labels(clean.text, _splitter.split_text(clean.text)) or [""]):
            nodes.append(_node(f"{mail.message_id}#body{i}", f"{head}\n\n{chunk}".strip(),
                               {**meta, "node_type": "email", "chunk": i}))

    context = clean.text[:300]   # לקובץ בלי טקסט: הקשר מגוף המייל ("מצרף צילום של החשבונית")
    for i, (att, ext) in enumerate(atts):
        content = ext.text or f"(קובץ {ext.kind}, התוכן לא נקרא)\n{context}".strip()
        for j, chunk in enumerate(_splitter.split_text(content)):
            nodes.append(_node(f"{mail.message_id}#att{i}.{j}", f"קובץ מצורף: {att.filename} | {head}\n\n{chunk}",
                               {**meta, "node_type": "attachment", "attachment_name": att.filename,
                                "attachment_type": ext.kind, "chunk": j}))
    return nodes
