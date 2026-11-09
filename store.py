"""אחסון של תיבה: mailbox.json (מקור, הכתובות שלי, האם התוויות נבדקו) ואוסף Chroma."""
import json

import chromadb
from chromadb.config import Settings as ChromaSettings
from llama_index.vector_stores.chroma import ChromaVectorStore

import config
import llm_setup


def load_info(name: str) -> dict | None:
    path = config.mailbox_paths(name)["info"]
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if name == config.DEMO_MAILBOX:   # תיבה מובנית: התוויות שלה ידועות
        info = {"mbox": str(config.DEMO_MBOX_PATH), "my_addresses": config.DEMO_MY_ADDRESSES, "labels_checked": True,
                "addressing": config.DEMO_ADDRESSING}
        save_info(name, info)
        return info
    return None


def save_info(name: str, info: dict) -> None:
    path = config.mailbox_paths(name)["info"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")


def list_mailboxes() -> list[str]:
    names = {p.parent.name for p in config.STORAGE_ROOT.glob("*/mailbox.json")}
    return sorted(names | {config.DEMO_MAILBOX})


def provider(name: str) -> str:
    return (load_info(name) or {}).get("provider", config.PROVIDER)


def collection(name: str, strategy: str | None = None, drop: bool = False, provider_override: str | None = None):
    client = chromadb.PersistentClient(path=str(config.mailbox_paths(name)["chroma"]),
                                       settings=ChromaSettings(anonymized_telemetry=False))
    if drop and llm_setup.collection_name(strategy, provider_override or provider(name)) in [c.name for c in client.list_collections()]:
        client.delete_collection(llm_setup.collection_name(strategy, provider_override or provider(name)))
    # cosine: מרחק לפי כיוון הווקטור, המקובל ל-embeddings של טקסט
    return client.get_or_create_collection(llm_setup.collection_name(strategy, provider_override or provider(name)), metadata={"hnsw:space": "cosine"})


def vector_store(col) -> ChromaVectorStore:
    return ChromaVectorStore(chroma_collection=col)


def indexed_ids(col) -> set[str]:
    """ה-Message-ID שכבר באינדקס, ישירות מ-Chroma: אין קובץ נפרד שיכול לצאת מסנכרון."""
    return {m["message_id"] for m in col.get(include=["metadatas"])["metadatas"]}
