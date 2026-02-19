from transformers import pipeline
import re

classifier = pipeline(
    "text-classification",
    model="distilbert-base-uncased-finetuned-sst-2-english"
)

TRUSTED_HINTS = [
    "amazon", "flipkart", "croma",
    "reliance", "tatacliq", "vijay"
]

def ai_score_offer(title, store, price):
    score = 0.5  # base

    text = f"{title} sold by {store}"

    try:
        sentiment = classifier(text)[0]
        if sentiment["label"] == "POSITIVE":
            score += 0.2
        else:
            score -= 0.2
    except:
        pass

    # store name trust
    store_l = store.lower()
    if any(t in store_l for t in TRUSTED_HINTS):
        score += 0.3
    else:
        score -= 0.2

    # price sanity (rough)
    if price <= 0:
        score -= 0.4

    return max(0, min(score, 1))