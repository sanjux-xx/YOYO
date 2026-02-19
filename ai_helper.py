from transformers import pipeline
import re

# Lightweight spell + text correction model
spell_corrector = pipeline(
    "text2text-generation",
    model="google/flan-t5-small"
)

def ai_clean_query(query: str) -> str:
    if not query:
        return query

    query = query.lower().strip()

    # remove junk symbols
    query = re.sub(r"[^a-z0-9\s]", "", query)

    prompt = f"Correct spelling and normalize this product name: {query}"

    try:
        result = spell_corrector(prompt, max_length=50)
        corrected = result[0]["generated_text"]
        return corrected.lower().strip()
    except Exception:
        # fallback (never break search)
        return query