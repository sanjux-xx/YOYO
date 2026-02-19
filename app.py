from flask import Flask, render_template, request
from serpapi import GoogleSearch
import re
import os
import time
import logging
from collections import defaultdict
from ai_helper import ai_clean_query

TRUSTED_STORES = [
    "amazon", "flipkart",
    "reliance", "croma",
    "tatacliq", "vijaysales"
]

# ===============================
# SENTRY
# ===============================
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[FlaskIntegration()],
    traces_sample_rate=0.2,
    send_default_pii=False
)

# ===============================
# FOOD BACKEND
# ===============================
from food_backend import food_bp

# ===============================
# APP
# ===============================
app = Flask(__name__)
app.register_blueprint(food_bp)

# ===============================
# SECURITY / RATE LIMIT
# ===============================
RATE_LIMIT = 10
WINDOW_SIZE = 60
BLOCK_TIME = 15 * 60
CACHE_TTL = 20 * 60

request_log = defaultdict(list)
blocked_ips = {}
cache = {}
query_counter = defaultdict(list)

# ===============================
# LOGGING
# ===============================
logging.basicConfig(level=logging.INFO)

# ===============================
# HELPERS
# ===============================
def get_client_ip():
    return request.headers.get("CF-Connecting-IP") or request.remote_addr

def extract_price(p):
    try:
        return float(p.get("price", "").replace("₹", "").replace(",", ""))
    except:
        return float("inf")
    
    

def is_valid_query(q):
    if not q:
        return False
    q = q.strip()
    return 3 <= len(q) <= 100

# ===============================
# STEP 1 – SAFE FILTER
# ===============================
def step1_strict_filter(products, query):
    if not products:
        return products

    q_words = query.lower().split()

    BLOCK_WORDS = [
    # accessories
    "case", "cover", "back cover", "skin",
    "tempered", "glass", "screen protector",
    "charger", "cable", "adapter",
    "holder", "stand", "mount",

    # resale / fake listings
    "sell", "selling", "used", "second hand",
    "refurbished", "pre owned", "exchange",

    # non-phone junk
    "sports", "jersey", "tshirt", "toy",
    "dummy", "model", "poster", "display"
]

    filtered = []

    for p in products:
        title = p.get("title", "").lower()
        if not title:
            continue

        # Remove obvious accessories
        if any(b in title for b in BLOCK_WORDS):
            continue
# Must be an actual phone
        PHONE_KEYWORDS = ["iphone", "mobile", "smartphone"]

        if not any(k in title for k in PHONE_KEYWORDS):
           continue        

        # SOFT match: at least ONE query word must appear
        if any(w in title for w in q_words):
            filtered.append(p)

    # CRITICAL fallback to avoid empty results
    return filtered if filtered else products

# ===============================
# STEP 2 – VARIANT GROUPING
# ===============================
def step2_group_variants(products):
    for p in products:
        title = p.get("title", "").lower()

        if "pro max" in title:
            p["variant"] = "Pro Max"
        elif "pro" in title and "pro max" not in title:
            p["variant"] = "Pro"
        elif "mini" in title:
            p["variant"] = "Mini"
        else:
            p["variant"] = "Base"

    return products
# ===============================
# STEP 3 – COMPARE & PICK BEST PRICE
# ===============================
def normalize_title(title):
    t = title.lower()
    t = re.sub(r"\(.*?\)", "", t)
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def build_product_key(p):
    title = normalize_title(p.get("title", ""))

    # detect iphone model number (12, 13, 14, etc.)
    m = re.search(r"iphone\s*(\d+)", title)
    model = m.group(1) if m else "unknown"

    # detect variant
    if "pro max" in title:
        variant = "pro max"
    elif "pro" in title:
        variant = "pro"
    elif "mini" in title:
        variant = "mini"
    else:
        variant = "base"

    return f"iphone-{model}-{variant}"

def clean_display_title(p):
    title = p.get("title", "").lower()

    # detect iphone model number
    m = re.search(r"iphone\s*(\d+)", title)
    model = m.group(1) if m else ""

    # detect variant
    if "pro max" in title:
        variant = "Pro Max"
    elif "pro" in title:
        variant = "Pro"
    elif "mini" in title:
        variant = "Mini"
    else:
        variant = ""

    if model:
        return f"iPhone {model} {variant}".strip()
    return p.get("title", "")


def step3_compare_products(products):
    grouped = {}

    from ai_offer_ranker import ai_score_offer  

    for p in products:
        key = build_product_key(p)
        price = extract_price(p)

        if price == float("inf"):
            continue

        if key not in grouped:
            grouped[key] = {
                "title": clean_display_title(p),
                "variant": p.get("variant", "Base"),
                "best_price": price,
                "best_store": p.get("store", ""),
                "best_link": p.get("link", ""),
                "image": p.get("image", ""),
                "offers": []
            }

        # ✅ AI score 
        offer_score = ai_score_offer(
            p.get("title", ""),
            p.get("store", ""),
            price
        )

        # ✅ append ONCE
        grouped[key]["offers"].append({
            "store": p.get("store", ""),
            "price": price,
            "link": p.get("link", ""),
            "ai_score": offer_score
        })
        
# AI-based ranking first

    product["offers"].sort(
    key=lambda x: (x["ai_score"], -x["price"]),
    reverse=True
    )
    preferred = []
    others = []

    for offer in product["offers"]:
     store = offer["store"].lower()
     if any(t in store for t in TRUSTED_STORES):
        preferred.append(offer)
     else:
        others.append(offer)

    preferred.sort(key=lambda x: x["price"])
    others.sort(key=lambda x: x["price"])

    product["offers"] = preferred + others
    
    # 🔥 SORT & PRIORITIZE STORES
    for product in grouped.values():
        preferred = []
        others = []

        for offer in product["offers"]:
            store_name = offer["store"].lower()
            if any(ts in store_name for ts in TRUSTED_STORES):
                preferred.append(offer)
            else:
                others.append(offer)

        # sort each group by price
        preferred.sort(key=lambda x: x["price"])
        others.sort(key=lambda x: x["price"])

        # merge back
        product["offers"] = preferred + others

        # force best_* from first offer
        if product["offers"]:
            best = product["offers"][0]
            product["best_price"] = best["price"]
            product["best_store"] = best["store"]
            product["best_link"] = best["link"]

    return list(grouped.values())

# ===============================
# SERPAPI
# ===============================
def get_product_prices(query):
    cache_key = query.lower().strip()
    now = time.time()

    if cache_key in cache:
        data, ts = cache[cache_key]
        if now - ts < CACHE_TTL:
            return data

    params = {
        "engine": "google_shopping",
        "q": query,
        "location": "India",
        "hl": "en",
        "gl": "in",
        "api_key": os.getenv("SERPAPI_KEY")
    }

    try:
        results = GoogleSearch(params).get_dict()
        products = []

        for item in results.get("shopping_results", []):
            title = item.get("title", "")

            # 1️⃣ get best possible link
            link = (
                item.get("link")
                or item.get("product_link")
                or (
                    item.get("offers", [{}])[0].get("link")
                    if item.get("offers")
                    else ""
                )
            )

            # 2️⃣ fix relative google links
            if link and link.startswith("/"):
                link = "https://www.google.com" + link

            # 3️⃣ fallback → GOOGLE SHOPPING (not normal google)
            if not link or not link.startswith("http"):
                link = (
                    "https://www.google.com/search?tbm=shop&q="
                    + re.sub(r"\s+", "+", title)
                )

            products.append({
                "title": title,
                "price": item.get("price", ""),
                "store": item.get("source", ""),
                "image": item.get("thumbnail", ""),
                "link": link
            })

        cache[cache_key] = (products, now)
        return products

    except Exception as e:
        sentry_sdk.capture_exception(e)
        return []

# ===============================
# ROUTES
# ===============================
@app.route("/", methods=["GET", "POST"])
def index():
    products = []
    variants = None   # keep if template expects it

    if request.method == "POST":
       raw_query = request.form.get("product_query", "").strip()
       query = ai_clean_query(raw_query)

    if is_valid_query(query):
            # RAW SERPAPI DATA
            raw = get_product_prices(query)

            # STEP 1 – FILTER
            filtered = step1_strict_filter(raw, query)
            if not filtered:
                filtered = raw

            # STEP 2 – VARIANT GROUPING
            variants = step2_group_variants(filtered)

            # STEP 3 – COMPARE & PICK BEST
            products = step3_compare_products(variants)

            # FINAL SORT (best price first)
            products = sorted(products, key=lambda x: x["best_price"])

    return render_template(
        "index.html",
        products=products,
        variants=variants
    )

@app.route("/category/<category_name>", methods=["GET", "POST"])
def category_page(category_name):

    category_rules = {
        "mobiles": "mobile phone",
        "laptops": "laptop",
        "fruits": "fresh fruits",
        "groceries": "grocery items"
    }

    if category_name not in category_rules:
        return render_template("category.html", category=category_name, products=[])

    base_query = category_rules[category_name]

    if request.method == "POST":
        search_term = request.form.get("search", "").strip()
        final_query = f"{search_term} {base_query}".strip()
    else:
        final_query = base_query

    products = get_product_prices(final_query)

    if category_name == "mobiles":
        # STEP 1
        products = step1_strict_filter(products, final_query)
        # STEP 2
        products = step2_group_variants(products)

    products = sorted(products, key=extract_price)

    return render_template(
        "category.html",
        category=category_name,
        products=products
    )

@app.route("/health")
def health():
    return {"status": "ok"}

# ===============================
# SECURITY HEADERS
# ===============================
@app.after_request
def add_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp

# ===============================
# RUN
# ===============================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000))
    )