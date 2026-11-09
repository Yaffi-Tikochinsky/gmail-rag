"""
הגדרת ה-LLM ומודל ה-embedding של LlamaIndex, לפי הספק של התיבה (config.PROVIDER כברירת מחדל).
כל שאר הקוד משתמש רק ב-Settings.llm וב-Settings.embed_model, ולא יודע איזה ספק פעיל.
(הועתק מ-llm/shidduch והותאם. לא מייבאים משם.)
"""
from llama_index.core import Settings

fast_llm = None   # לניסוח מחדש של השאלה: בלי חשיבה, כי זה בכל שאלה

import config


def setup_models(provider: str | None = None) -> None:
    global fast_llm
    provider = provider or config.PROVIDER
    api_key, m = config.get_api_key(provider), config.MODELS[provider]

    if provider == "gemini":
        from llama_index.embeddings.google_genai import GoogleGenAIEmbedding
        from llama_index.llms.google_genai import GoogleGenAI

        Settings.llm = GoogleGenAI(
            model=m["llm"], api_key=api_key, temperature=config.LLM_TEMPERATURE
        )
        Settings.embed_model = GoogleGenAIEmbedding(
            model_name=m["embed"], api_key=api_key
        )
        fast_llm = Settings.llm

    elif provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.llms.openai import OpenAI

        Settings.llm = OpenAI(
            model=m["llm"], api_key=api_key, temperature=config.LLM_TEMPERATURE, reasoning_effort=m.get("reasoning")
        )
        Settings.embed_model = OpenAIEmbedding(model=m["embed"], api_key=api_key)
        fast_llm = OpenAI(model=m["llm"], api_key=api_key, temperature=config.LLM_TEMPERATURE, reasoning_effort="none")

    else:
        raise ValueError(f"ספק לא מוכר: {provider}")


def collection_name(strategy: str | None = None, provider: str | None = None) -> str:
    # אוסף נפרד לכל ספק: וקטורים של מודלי embedding שונים לא ניתנים להשוואה,
    # ואסור שיתערבבו באותו אוסף.
    # אוסף נפרד גם לכל אסטרטגיית chunking, כדי שאפשר להשוות ביניהן על אותה תיבה.
    strategy = strategy or config.CHUNKING_STRATEGY
    return f"{config.CHROMA_COLLECTION}_{strategy}_{provider or config.PROVIDER}"


def patient(fn, *args, tries: int = 4, **kwargs):
    """לסקריפטים שמריצים הרבה שאלות ברצף (הערכה, מלכודות): על מכסת דקה (429) ממתינים דקה ומנסים שוב.
    במסלול החינמי של gemini-3.5-flash-lite מותרות 15 קריאות בדקה, וכל שאלה היא 2 קריאות."""
    import time
    for i in range(tries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if "429" not in str(e) or i == tries - 1:
                raise
            print("  מכסת הדקה נוצלה. ממתין 60 שניות...", flush=True)
            time.sleep(60)
