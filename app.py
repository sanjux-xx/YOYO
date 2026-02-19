from flask import Flask, render_template, request
from serpapi import GoogleSearch
import re
import os
import time
import logging
from collections import defaultdict

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
        "case", "cover", "back cover",
        "charger", "cable", "adapter",
        "tempered", "glass", "screen protector",
        "skin", "holder", "stand", "mount"
    ]

    filtered = []

    for p in products:
        title = p.get("title", "").lower()
        if not title:
            continue

        # Remove obvious accessories
        if any(b in title for b in BLOCK_WORDS):
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
        else:
            p["variant"] = "Base"

    return products

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
    variants = None   # ✅ FIX: define it explicitly

    if request.method == "POST":
        query = request.form.get("product_query", "").strip()

        if is_valid_query(query):
            raw = get_product_prices(query)

            # STEP 1
            filtered = step1_strict_filter(raw, query)
            if not filtered:
                filtered = raw

            # STEP 2
            products = step2_group_variants(filtered)

            products = sorted(products, key=extract_price)

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