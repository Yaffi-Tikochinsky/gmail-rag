"""
חילוץ טקסט מקבצים מצורפים. כל קובץ מצורף הופך ל-Node נפרד (ב-node_builder.py).
שלב 1: PDF עם שכבת טקסט (pypdf), docx (python-docx), ומייל מצורף (eml, דרך email_parser).
לכל שאר הסוגים (PDF סרוק, תמונות, וידאו, xlsx, zip וכו׳): רק שם הקובץ, והקשר המייל מגיע מה-metadata.
שלב 2 (מאוחר): מודל ראייה ל-PDF סרוק ולתמונות.
"""
from dataclasses import dataclass
import io
import logging
from pathlib import PurePath

import config
from email_parser import Attachment

logging.getLogger("pypdf").setLevel(logging.ERROR)   # pypdf מדפיס אזהרות על כל PDF לא מושלם

# סוג הקובץ ל-metadata (attachment_type), לפי סיומת
TYPE_BY_EXT = {
    ".pdf": "pdf", ".docx": "docx", ".doc": "doc", ".eml": "email",
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image", ".heic": "image", ".webp": "image",
    ".mp4": "video", ".mov": "video", ".avi": "video", ".3gp": "video",
    ".mp3": "audio", ".m4a": "audio", ".wav": "audio", ".ogg": "audio", ".opus": "audio",
    ".xlsx": "spreadsheet", ".xls": "spreadsheet", ".csv": "spreadsheet",
    ".zip": "archive", ".rar": "archive", ".7z": "archive",
    ".ics": "calendar", ".txt": "text",
}
# כשאין סיומת (או שהיא לא מוכרת): לפי Content-Type
TYPE_BY_MIME = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "spreadsheet",
    "application/vnd.ms-excel": "spreadsheet",
    "application/zip": "archive", "application/x-zip-compressed": "archive",
    "text/calendar": "calendar", "message/rfc822": "email",
}


@dataclass
class AttachmentText:
    text: str      # הטקסט שחולץ ("" אם אין)
    status: str    # extracted | no_text_layer | name_only | too_large | error
    kind: str      # pdf / docx / image / ... (ל-metadata)


def attachment_kind(att: Attachment) -> str:
    kind = TYPE_BY_EXT.get(PurePath(att.filename).suffix.lower()) or TYPE_BY_MIME.get(att.content_type)
    if kind:
        return kind
    main = att.content_type.split("/")[0]
    return main if main in ("image", "video", "audio") else "other"


def _pdf_text(data: bytes) -> str:
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _docx_text(data: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:   # טבלאות לא נכללות ב-paragraphs
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts).strip()


def _eml_text(data: bytes) -> str:
    # מייל מצורף: מפענחים ומנקים אותו כמו כל מייל, ומוסיפים כותרת קצרה
    from body_cleaner import clean_body
    from email_parser import parse_email
    inner = parse_email(data)
    date = inner.date.strftime("%d.%m.%Y") if inner.date else ""
    sender = f"{inner.from_name} <{inner.from_email}>" if inner.from_name else inner.from_email
    body = clean_body(inner.body, inner.subject).text
    return f"מאת: {sender}\nתאריך: {date}\nנושא: {inner.subject}\n\n{body}".strip()


EXTRACTORS = {"pdf": _pdf_text, "docx": _docx_text, "email": _eml_text}


def extract_attachment_text(att: Attachment) -> AttachmentText:
    kind = attachment_kind(att)
    extractor = EXTRACTORS.get(kind)
    if extractor is None:
        return AttachmentText("", "name_only", kind)
    if att.size > config.MAX_ATTACHMENT_BYTES:
        return AttachmentText("", "too_large", kind)
    try:
        text = extractor(att.data)
    except Exception as e:   # קובץ פגום או מוצפן: לא עוצרים את כל האינדוקס בגלל קובץ אחד
        return AttachmentText("", f"error: {type(e).__name__}", kind)
    if not text:
        return AttachmentText("", "no_text_layer", kind)   # למשל PDF סרוק
    return AttachmentText(text[:config.MAX_ATTACHMENT_CHARS], "extracted", kind)
