from flask import Flask, render_template, request
from serpapi import GoogleSearch
import re
import os
import time
import logging
from collections import defaultdict

# ===============================
# SENTRY (LAYER 3 - MONITORING)
# ===============================
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),   # from Render env
    integrations=[FlaskIntegration()],
    traces_sample_rate=0.2,        # 20% performance sampling
    send_default_pii=False
)

# ===============================
# IMPORT FOOD BACKEND (Blueprint)
# ===============================
from food_backend import food_bp

# ===============================
# CREATE FLASK APP
# ===============================
app = Flask(__name__)
app.register_blueprint(food_bp)

# ===============================
# MINI SOC CONFIG (LAYER 2)
# ===============================
RATE_LIMIT = 10            # requests per window
WINDOW_SIZE = 60           # seconds
BLOCK_TIME = 15 * 60       # 15 minutes
CACHE_TTL = 20 * 60        # 20 minutes

request_log = defaultdict(list)
blocked_ips = {}
cache = {}

# ===============================
# SECURITY LOGGING (MINI SOC)
# ===============================
logging.basicConfig(
    filename="security.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

def log_event(event, ip, meta=None, level="INFO"):
    logging.log(
        logging.INFO if level == "INFO" else logging.WARNING,
        f"{event} | ip={ip} | meta={meta or {}}"
    )

# ===============================
# IP + RATE LIMIT HELPERS
# ===============================
def get_client_ip():
    if request.headers.get("CF-Connecting-IP"):
        return request.headers.get("CF-Connecting-IP")
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr

def is_rate_limited(ip):
    now = time.time()

    # Temporary block check
    if ip in blocked_ips:
        if now < blocked_ips[ip]:
            return True
        else:
            del blocked_ips[ip]

    # Clean old timestamps
    request_log[ip] = [t for t in request_log[ip] if now - t < WINDOW_SIZE]

    if len(request_log[ip]) >= RATE_LIMIT:
        blocked_ips[ip] = now + BLOCK_TIME
        log_event("RATE_LIMIT_BLOCK", ip, {"count": len(request_log[ip])}, "WARN")
        return True

    request_log[ip].append(now)
    return False

# ===============================
# INPUT VALIDATION
# ===============================
def is_valid_query(q):
    if not q or len(q) < 3 or len(q) > 100:
        return False
    if "<script" in q.lower():
        return False
    return True

# ===============================
# HELPERS (PRODUCT FILTERING)
# ===============================
def weight_in_title(title, weight):
    if not weight:
        return True
    pattern = re.escape(weight.lower()).replace("kg", r"\s*-?\s*kg")
    return re.search(pattern, title.lower()) is not None

def extract_price(product):
    try:
        price = product.get("price", "")
        return float(price.replace("₹", "").replace(",", "").strip())
    except:
        return float("inf")

# ===============================
# SERPAPI FETCH (PROTECTED)
# ===============================
def get_product_prices(query):
    ip = get_client_ip()

    # Rate limit before API call
    if is_rate_limited(ip):
        log_event("RATE_LIMIT_HIT", ip, {"query": query})
        return []

    now = time.time()
    cache_key = f"search:{query.lower()}"

    # Cache check
    if cache_key in cache:
        data, ts = cache[cache_key]
        if now - ts < CACHE_TTL:
            log_event("CACHE_HIT", ip, {"query": query})
            return data

    params = {
        "engine": "google_shopping",
        "q": query,
        "location": "India",
        "hl": "en",
        "gl": "in",
        "api_key": os.getenv("SERPAPI_KEY")  # from Render env
    }

    try:
        log_event("SERPAPI_CALL", ip, {"query": query})

        search = GoogleSearch(params)
        results = search.get_dict(timeout=10)

        products = []
        for item in results.get("shopping_results", []):
            link = (
                item.get("link")
                or item.get("product_link")
                or (item.get("offers", [{}])[0].get("link") if item.get("offers") else "")
            )

            if link and not link.startswith("http"):
                link = "https://www.google.com" + link

            products.append({
                "title": item.get("title", ""),
                "price": item.get("price", ""),
                "rating": item.get("rating"),
                "reviews": item.get("reviews"),
                "link": link,
                "store": item.get("source", ""),
                "image": item.get("thumbnail", "")
            })

        cache[cache_key] = (products, now)
        return products

    except Exception as e:
        log_event("SERPAPI_ERROR", ip, {"error": str(e)}, "WARN")
        raise  # important: let Sentry capture this

# ===============================
# HOME PAGE
# ===============================
@app.route("/", methods=["GET", "POST"])
def index():
    products = []

    if request.method == "POST":
        product = request.form.get("product_query", "").strip()
        brand = request.form.get("brand_filter", "").strip()
        weight = request.form.get("weight_filter", "").strip()

        query = " ".join([product, brand, weight]).strip()

        if is_valid_query(query):
            products = get_product_prices(query)

            if weight:
                products = [p for p in products if weight_in_title(p["title"], weight)]

            products = sorted(products, key=extract_price)
        else:
            log_event("INVALID_QUERY", get_client_ip(), {"query": query})

    return render_template("index.html", products=products)

# ===============================
# CATEGORY PAGE
# ===============================
@app.route("/category/<category_name>", methods=["GET", "POST"])
def category_page(category_name):
    category_map = {
        "mobiles": "mobile phone",
        "laptops": "laptop",
        "fruits": "fresh fruits",
        "groceries": "grocery items"
    }

    base_query = category_map.get(category_name, category_name)

    if request.method == "POST":
        search_term = request.form.get("search", "")
        final_query = f"{search_term} {base_query}"
    else:
        final_query = base_query

    if not is_valid_query(final_query):
        log_event("INVALID_QUERY", get_client_ip(), {"query": final_query})
        return render_template("category.html", category=category_name, products=[])

    products = get_product_prices(final_query)
    products = sorted(products, key=extract_price)

    return render_template("category.html", category=category_name, products=products)

# ===============================
# HEALTH CHECK
# ===============================
@app.route("/health")
def health():
    return {"status": "ok"}

# ===============================
# ===============================
# TEST SENTRY (TEMPORARY)
# ===============================
@app.route("/test-error")
def test_error():
    1 / 0
# RUN SERVER
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)