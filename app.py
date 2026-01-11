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
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[FlaskIntegration()],
    traces_sample_rate=0.2,
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
RATE_LIMIT = 10
WINDOW_SIZE = 60
BLOCK_TIME = 15 * 60
CACHE_TTL = 20 * 60

request_log = defaultdict(list)
blocked_ips = {}
cache = {}

# ===============================
# LAYER 4: QUERY ABUSE TRACKING 
# ===============================
query_counter = defaultdict(list)

# ===============================
# LOGGING (RENDER SAFE)
# ===============================
logging.basicConfig(
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
        return request.headers.get("X-Forwarded-For").split(",")[0]
    return request.remote_addr

def is_rate_limited(ip):
    now = time.time()

    if ip in blocked_ips:
        if now < blocked_ips[ip]:
            return True
        else:
            del blocked_ips[ip]

    request_log[ip] = [t for t in request_log[ip] if now - t < WINDOW_SIZE]

    if len(request_log[ip]) >= RATE_LIMIT:
        blocked_ips[ip] = now + BLOCK_TIME
        log_event("RATE_LIMIT_BLOCK", ip, {"count": len(request_log[ip])}, "WARN")
        return True

    request_log[ip].append(now)
    return False

# ===============================
# LAYER 4: STRICT INPUT VALIDATION
# ===============================
def is_valid_query(q):
    if not q:
        return False

    q = q.strip()

    if len(q) < 3 or len(q) > 100:
        return False

    blocked_patterns = [
        "<script",
        "\"",
        ";",
        "--",
        "/*",
        "*/",
        " or ",
        " and "
    ]

    lower_q = q.lower()
    for b in blocked_patterns:
        if b in lower_q:
            return False

    return True

# ===============================
# HELPERS
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
# LAYER 4: QUERY ABUSE PROTECTION
# ===============================
def is_query_abused(query):
    now = time.time()
    query_counter[query] = [t for t in query_counter[query] if now - t < 3600]
    query_counter[query].append(now)
    return len(query_counter[query]) > 20

# ===============================
# SERPAPI FETCH (PROTECTED)
# ===============================
def get_product_prices(query):
    ip = get_client_ip()

    if is_rate_limited(ip):
        log_event("RATE_LIMIT_HIT", ip, {"query": query})
        return []

    if is_query_abused(query):
        log_event("QUERY_ABUSE", ip, {"query": query})
        return []

    now = time.time()
    cache_key = f"search:{query.lower().strip()}"

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
        "api_key": os.getenv("SERPAPI_KEY")
    }

    try:
        log_event("SERPAPI_CALL", ip, {"query": query})
        search = GoogleSearch(params)
        results = search.get_dict()

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
        sentry_sdk.capture_exception(e)
        return []

# ===============================
# ROUTES
# ===============================
@app.route("/", methods=["GET", "POST"])
def index():
    products = None 

    if request.method == "POST":
        product = request.form.get("product_query", "").strip()
        brand = request.form.get("brand_filter", "").strip()
        weight = request.form.get("weight_filter", "").strip()

        query = " ".join([product, brand, weight]).strip()

        if is_valid_query(query):
            products = get_product_prices(query)

            if weight:
                products = [
                    p for p in products
                    if weight_in_title(p["title"], weight)
                ]

            products = sorted(products, key=extract_price)
        else:
            products = []
            log_event("INVALID_QUERY", get_client_ip(), {"query": query})

    return render_template("index.html", products=products)

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

@app.route("/health")
def health():
    return {"status": "ok"}

# ===============================
# LAYER 4: SECURE HEADERS (MODERN)
# ===============================
@app.after_request
def add_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src https: data:; "
        "style-src 'self' 'unsafe-inline'"
    )
    return response

# ===============================
# LAYER 4: GLOBAL ERROR HANDLER
# ===============================
@app.errorhandler(Exception)
def handle_all_errors(e):
    ip = get_client_ip()
    log_event("UNHANDLED_EXCEPTION", ip, {"error": str(e)}, "WARN")
    sentry_sdk.capture_exception(e)
    return render_template("error.html"), 500

# ===============================
# RUN SERVER
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)