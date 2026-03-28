from flask import Flask, render_template, request
from serpapi import GoogleSearch
import re
import os
import time
import logging
from collections import defaultdict


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
    words = title.split()
    key = " ".join(words[:5])
    return key


def clean_display_title(p):
    title = p.get("title", "").lower()

    m = re.search(r"iphone\s*(\d+)", title)
    model = m.group(1) if m else ""

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

        grouped[key]["offers"].append({
            "store": p.get("store", ""),
            "price": price,
            "link": p.get("link", ""),
        })

    # SORT & PRIORITIZE STORES
    for product in grouped.values():
        preferred = []
        others = []

        for offer in product["offers"]:
            store_name = offer["store"].lower()
            if any(ts in store_name for ts in TRUSTED_STORES):
                preferred.append(offer)
            else:
                others.append(offer)

        preferred.sort(key=lambda x: x["price"])
        others.sort(key=lambda x: x["price"])

        product["offers"] = preferred + others

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

            link = (
                item.get("link")
                or item.get("product_link")
                or (
                    item.get("offers", [{}])[0].get("link")
                    if item.get("offers")
                    else ""
                )
            )

            if link and link.startswith("/"):
                link = "https://www.google.com" + link

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
# RATE LIMITING
# ===============================
@app.before_request
def rate_limit():
    # Skip rate limiting for health check
    if request.path == "/health":
        return None

    ip = get_client_ip()
    now = time.time()

    # Check if IP is currently blocked
    if ip in blocked_ips:
        blocked_until = blocked_ips[ip]
        if now < blocked_until:
            retry_after = int(blocked_until - now)
            logging.warning(f"Blocked IP tried again: {ip}")
            return (
                f"<h2>Too Many Requests</h2>"
                f"<p>You have been temporarily blocked. Try again in {retry_after // 60} min {retry_after % 60} sec.</p>",
                429
            )
        else:
            # Block expired — clear it
            del blocked_ips[ip]
            request_log[ip] = []

    # Clean old requests outside the window
    request_log[ip] = [t for t in request_log[ip] if now - t < WINDOW_SIZE]

    # Check if over limit
    if len(request_log[ip]) >= RATE_LIMIT:
        blocked_ips[ip] = now + BLOCK_TIME
        logging.warning(f"IP blocked for exceeding rate limit: {ip}")
        return (
            "<h2>Too Many Requests</h2>"
            "<p>You have made too many requests. You are blocked for 15 minutes.</p>",
            429
        )

    # Log this request
    request_log[ip].append(now)
    return None


# ===============================
# ROUTES
# ===============================
@app.route("/", methods=["GET", "POST"])
def index():
    products = []
    variants = None
    query = ""

    if request.method == "POST":
        raw_query = request.form.get("product_query", "").strip()
        query = raw_query

        if is_valid_query(query):
            raw = get_product_prices(query)

            filtered = step1_strict_filter(raw, query)
            if not filtered:
                filtered = raw

            variants = step2_group_variants(filtered)
            products = step3_compare_products(variants)
            products = sorted(products, key=lambda x: x["best_price"])

    return render_template(
        "index.html",
        products=products,
        variants=variants
    )


@app.route("/category/<category_name>", methods=["GET", "POST"])
def medicine_filter(products, query):
    if not products:
        return products

    q_words = query.lower().replace("buy online india", "").split()

    # Block non-medicine results
    BLOCK_WORDS = [
        "mobile", "phone", "smartphone", "iphone", "samsung",
        "laptop", "tablet", "headphone", "earphone", "charger",
        "cover", "case", "cable", "watch", "camera",
        "shirt", "shoe", "toy", "book", "furniture"
    ]

    # Must contain at least one medicine keyword
    MEDICINE_KEYWORDS = [
        "tablet", "capsule", "syrup", "drops", "cream", "gel",
        "ointment", "injection", "sachet", "strip", "mg", "ml",
        "medicine", "pharma", "healthcare", "drug", "supplement",
        "vitamin", "protein", "pain", "relief", "antibiotic"
    ]

    filtered = []
    for p in products:
        title = p.get("title", "").lower()
        store = p.get("store", "").lower()

        if not title:
            continue

        # Block if contains non-medicine words
        if any(b in title for b in BLOCK_WORDS):
            continue

        # Allow if store is a pharmacy
        pharmacy_stores = ["1mg", "netmeds", "pharmeasy", "apollo", "medplus", "flipkart health"]
        is_pharmacy = any(ph in store for ph in pharmacy_stores)

        # Allow if title contains medicine keyword OR from pharmacy store
        has_medicine_word = any(k in title for k in MEDICINE_KEYWORDS)

        # Allow if query word appears in title
        query_match = any(w in title for w in q_words if len(w) > 2)

        if (has_medicine_word or is_pharmacy) and query_match:
            filtered.append(p)

    # Fallback — if too strict, return anything from pharmacy stores
    if not filtered:
        filtered = [
            p for p in products
            if any(ph in p.get("store", "").lower()
                   for ph in ["1mg", "netmeds", "pharmeasy", "apollo", "medplus"])
        ]

    return filtered if filtered else products

def category_page(category_name):

    category_rules = {
        "mobiles":   "mobile phone",
        "laptops":   "laptop",
        "fruits":    "fresh fruits",
        "groceries": "grocery items",
        # ── MEDICINE: broad default, specific on search ──
        "medicine":  "medicine online India"
    }

    if category_name not in category_rules:
        return render_template("category.html", category=category_name, products=[])

    base_query = category_rules[category_name]

    if request.method == "POST":
        search_term = request.form.get("search", "").strip()

        # ── Medicine: use search term directly for precise results ──
        if category_name == "medicine" and search_term:
            final_query = f"{search_term} buy online India"
        else:
            final_query = f"{search_term} {base_query}".strip() if search_term else base_query
    else:
        final_query = base_query

    products = get_product_prices(final_query)

    if category_name == "mobiles":
        products = step1_strict_filter(products, final_query)
        products = step2_group_variants(products)
    elif category_name == "medicine":
        products = medicine_filter(products, final_query)

    products = sorted(products, key=extract_price)

    return render_template(
        "category.html",
        category=category_name,
        products=products
    )

@app.route("/api/price-check")
def price_check():
    title = request.args.get("title", "").strip()
    if not title or len(title) < 3:
        return {"error": "Invalid query"}, 400

    products = get_product_prices(title)
    if not products:
        return {"current_price": None, "link": None}

    # Sort by price and return cheapest
    def safe_price(p):
        try:
            return float(p.get("price", "").replace("₹", "").replace(",", ""))
        except:
            return float("inf")

    products_sorted = sorted(products, key=safe_price)
    best = products_sorted[0]

    try:
        price = float(best.get("price", "").replace("₹", "").replace(",", ""))
    except:
        price = None

    return {
        "current_price": price,
        "link": best.get("link", "/"),
        "store": best.get("store", "")
    }
    
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