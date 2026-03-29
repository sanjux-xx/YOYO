from flask import Flask, render_template, request
from serpapi import GoogleSearch
import re
import os
import time
import logging
from collections import defaultdict


TRUSTED_STORES = [
    # E-commerce
    "amazon", "flipkart",
    "tatacliq", "vijaysales",
    "myntra", "meesho",
    "snapdeal", "shopsy",

    # Electronics
    "croma", "reliance digital",
    "vijay sales", "ezone",

    # Quick commerce
    "blinkit", "zepto",
    "swiggy instamart", "dunzo",
    "bigbasket", "jiomart",
    "instamart",

    # Pharmacy
    "1mg", "netmeds", "pharmeasy",
    "apollo pharmacy", "medplus",

    # Fashion
    "ajio", "nykaa", "nykaafashion",

    # Other
    "boat", "noise", "samsung shop",
    "apple", "mi store", "oneplus",
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
RATE_LIMIT = 50
WINDOW_SIZE = 60
BLOCK_TIME = 2 * 60
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
        "case", "cover", "back cover", "skin",
        "tempered", "glass", "screen protector",
        "charger", "cable", "adapter",
        "holder", "stand", "mount",
        "sell", "selling", "used", "second hand",
        "refurbished", "pre owned", "exchange",
        "sports", "jersey", "tshirt", "toy",
        "dummy", "model", "poster", "display"
    ]

    filtered = []

    for p in products:
        title = p.get("title", "").lower()
        if not title:
            continue

        if any(b in title for b in BLOCK_WORDS):
            continue

        PHONE_KEYWORDS = ["iphone", "mobile", "smartphone"]
        if not any(k in title for k in PHONE_KEYWORDS):
            continue

        if any(w in title for w in q_words):
            filtered.append(p)

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
            logging.info(f"best_link: {best['link']}")  # ← ADD THIS LINE

    return list(grouped.values())


# ===============================
# SERPAPI
# ===============================
def get_merchant_link(product_id):
    """2nd API call to get direct merchant link from product ID"""
    try:
        params = {
            "engine":     "google_product",
            "product_id": product_id,
            "api_key":    os.getenv("SERPAPI_KEY")
        }
        result = GoogleSearch(params).get_dict()
        sellers = result.get("sellers_results", {}).get("online_sellers", [])
        
        # Find trusted store first
        for seller in sellers:
            store = seller.get("name", "").lower()
            link  = seller.get("link", "")
            if any(ts in store for ts in TRUSTED_STORES) and link:
                return link
        
        # Fallback to first available seller
        if sellers and sellers[0].get("link"):
            return sellers[0]["link"]
            
    except Exception as e:
        logging.error(f"Merchant link fetch error: {e}")
    return ""


def get_product_prices(query):
    cache_key = query.lower().strip()
    now = time.time()

    if cache_key in cache:
        data, ts = cache[cache_key]
        if now - ts < CACHE_TTL:
            return data

    params = {
        "engine":   "google_shopping",
        "q":        query,
        "location": "India",
        "hl":       "en",
        "gl":       "in",
        "api_key":  os.getenv("SERPAPI_KEY")
    }

    try:
        results = GoogleSearch(params).get_dict()
        products = []

        for item in results.get("shopping_results", []):
            title      = item.get("title", "")
            product_id = item.get("product_id", "")
            logging.info(f"title: {title} | product_id: {product_id}")  # ← ADD THIS LINE ONLY

            # Step 1 — get basic link
            link = (
                item.get("link")
                or item.get("product_link")
                or (item.get("offers", [{}])[0].get("link") if item.get("offers") else "")
                or ""
            )

            # Step 2 — always fetch direct merchant link via product_id
            if product_id:
                logging.info(f"Fetching direct merchant link for: {title}")
                direct = get_merchant_link(product_id)
                if direct:
                    link = direct

            # Final fallback
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
                "link":  link
            })

        cache[cache_key] = (products, now)
        return products

    except Exception as e:
        sentry_sdk.capture_exception(e)
        return []


# ===============================
# BLOCK PAGE HTML TEMPLATES
# ===============================
def render_already_blocked_page(retry_after):
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Blocked — CostShot</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-950 min-h-screen flex items-center justify-center px-4">
  <div class="text-center max-w-md">
    <div class="text-7xl mb-6">⏳</div>
    <h1 class="text-3xl font-bold text-white mb-3">Slow Down!</h1>
    <p class="text-gray-400 mb-6">Too many requests. Try again in:</p>
    <div class="bg-gray-900 border border-gray-800 rounded-2xl px-8 py-5 mb-6">
      <div class="text-4xl font-bold text-orange-400" id="cd">{retry_after // 60}m {retry_after % 60}s</div>
    </div>
    <p class="text-gray-600 text-xs">CostShot limits requests per minute for everyone.</p>
  </div>
  <script>
    let s = {retry_after};
    const e = document.getElementById('cd');
    setInterval(() => {{
      s--;
      if (s <= 0) {{ location.reload(); return; }}
      e.textContent = Math.floor(s/60) + 'm ' + s%60 + 's';
    }}, 1000);
  </script>
</body>
</html>""", 429


def render_newly_blocked_page():
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Blocked — CostShot</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-950 min-h-screen flex items-center justify-center px-4">
  <div class="text-center max-w-md">
    <div class="text-7xl mb-6">🚫</div>
    <h1 class="text-3xl font-bold text-white mb-3">Too Many Requests</h1>
    <p class="text-gray-400 mb-6">You are blocked for 2 minutes.</p>
    <div class="bg-gray-900 border border-gray-800 rounded-2xl px-8 py-5 mb-6">
      <div class="text-4xl font-bold text-red-400" id="cd">2m 0s</div>
    </div>
    <p class="text-gray-600 text-xs">CostShot limits requests per minute for everyone.</p>
  </div>
  <script>
    let s = {BLOCK_TIME};
    const e = document.getElementById('cd');
    setInterval(() => {{
      s--;
      if (s <= 0) {{ location.reload(); return; }}
      e.textContent = Math.floor(s/60) + 'm ' + s%60 + 's';
    }}, 1000);
  </script>
</body>
</html>""", 429


# ===============================
# RATE LIMITING — FIXED
# ===============================
@app.before_request
def rate_limit():
    # Skip rate limiting for health check and static files
    if request.path == "/health":
        return None
    if request.path.startswith("/static"):
        return None

    ip = get_client_ip()
    now = time.time()

    # Check if IP is currently blocked
    if ip in blocked_ips:
        blocked_until = blocked_ips[ip]
        if now < blocked_until:
            retry_after = int(blocked_until - now)
            logging.warning(f"Blocked IP tried again: {ip}")
            return render_already_blocked_page(retry_after)  # ← RETURN here
        else:
            # Block expired — clear it
            del blocked_ips[ip]
            request_log[ip] = []

    # Clean old requests outside the window
    request_log[ip] = [t for t in request_log[ip] if now - t < WINDOW_SIZE]

    # Check if over limit — FIXED: return is now INSIDE this if block
    if len(request_log[ip]) >= RATE_LIMIT:
        blocked_ips[ip] = now + BLOCK_TIME
        logging.warning(f"IP blocked for exceeding rate limit: {ip}")
        return render_newly_blocked_page()  # ← RETURN inside if block

    # Only reached if NOT blocked — log request and allow
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


# ===============================
# MEDICINE FILTER
# ===============================
def medicine_filter(products, query):
    if not products:
        return products

    q_words = query.lower().replace("buy online india", "").split()

    BLOCK_WORDS = [
        "mobile", "phone", "smartphone", "iphone", "samsung",
        "laptop", "tablet", "headphone", "earphone", "charger",
        "cover", "case", "cable", "watch", "camera",
        "shirt", "shoe", "toy", "book", "furniture"
    ]

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

        if any(b in title for b in BLOCK_WORDS):
            continue

        pharmacy_stores = ["1mg", "netmeds", "pharmeasy", "apollo", "medplus", "flipkart health"]
        is_pharmacy = any(ph in store for ph in pharmacy_stores)

        has_medicine_word = any(k in title for k in MEDICINE_KEYWORDS)
        query_match = any(w in title for w in q_words if len(w) > 2)

        if (has_medicine_word or is_pharmacy) and query_match:
            filtered.append(p)

    if not filtered:
        filtered = [
            p for p in products
            if any(ph in p.get("store", "").lower()
                   for ph in ["1mg", "netmeds", "pharmeasy", "apollo", "medplus"])
        ]

    return filtered if filtered else products


# ===============================
# CATEGORY ROUTE
# ===============================
@app.route("/category/<category_name>", methods=["GET", "POST"])
def category_page(category_name):
    category_rules = {
        "mobiles":   "mobile phone",
        "laptops":   "laptop",
        "fruits":    "fresh fruits",
        "groceries": "grocery items",
        "medicine":  "medicine online India"
    }

    if category_name not in category_rules:
        return render_template("category.html", category=category_name, products=[])

    base_query = category_rules[category_name]

    if request.method == "POST":
        search_term = request.form.get("search", "").strip()

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


# ===============================
# API ROUTE
# ===============================
@app.route("/api/price-check")
def price_check():
    title = request.args.get("title", "").strip()
    if not title or len(title) < 3:
        return {"error": "Invalid query"}, 400

    products = get_product_prices(title)
    if not products:
        return {"current_price": None, "link": None}

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


# ===============================
# HEALTH CHECK
# ===============================
@app.route("/health")
def health():
    return {"status": "ok"}

@app.route("/sw.js")
def sw():
    return app.send_static_file("sw.js")

@app.route("/manifest.json")
def manifest():
    return app.send_static_file("manifest.json")

# ===============================
# SECURITY HEADERS
# ===============================
@app.after_request
def add_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp