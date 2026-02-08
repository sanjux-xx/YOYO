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
# LOGGING
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
# IP HELPERS
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
        del blocked_ips[ip]

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
    if not q:
        return False

    q = q.strip()
    if len(q) < 3 or len(q) > 100:
        return False

    blocked_patterns = ["<script", "\"", ";", "--", "/*", "*/", " or ", " and "]
    lower_q = q.lower()

    return not any(b in lower_q for b in blocked_patterns)

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
        return float(
            product.get("price", "")
            .replace("₹", "")
            .replace(",", "")
            .strip()
        )
    except:
        return float("inf")

def is_query_abused(query):
    now = time.time()
    query_counter[query] = [t for t in query_counter[query] if now - t < 3600]
    query_counter[query].append(now)
    return len(query_counter[query]) > 20

# ===============================
# SERPAPI FETCH
# ===============================
def get_product_prices(query):
    ip = get_client_ip()

    # Rate-limit & abuse protection
    if is_rate_limited(ip) or is_query_abused(query):
        return []

    cache_key = f"search:{query.lower().strip()}"
    now = time.time()

    # Cache hit
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
                title = item.get("title", "")
                link = (
                    "https://www.google.com/search?q="
                    + re.sub(r"\s+", "+", title)
                )

            # Product object
            products.append({
                "title": item.get("title", ""),
                "price": item.get("price", ""),
                "rating": item.get("rating"),
                "store": item.get("source", ""),
                "image": item.get("thumbnail", ""),
                "link": link
            })

        # Save to cache
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
    products = None

    if request.method == "POST":
        query = request.form.get("product_query", "").strip()

        if is_valid_query(query):
            products = sorted(get_product_prices(query), key=extract_price)
        else:
            products = []

    return render_template("index.html", products=products)

@app.route("/category/<category_name>", methods=["GET", "POST"])
def category_page(category_name):
    category_map = {
        "mobiles": "mobile phone",
        "laptops": "laptop",
        "fruits": "fresh fruits",
        "groceries": "grocery items"
    }

    # If unknown category → 404 (prevents Sentry spam)
    if category_name not in category_map:
        return "Category not found", 404

    base_query = category_map[category_name]

    # 🔎 If user searches inside a category
    if request.method == "POST":
        search_term = request.form.get("search", "").strip()
        final_query = f"{search_term} {base_query}".strip()
    else:
        final_query = base_query

    products = sorted(
        get_product_prices(final_query),
        key=extract_price
    )

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
def add_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

# ===============================
# SAFE ERROR HANDLER
# ===============================
@app.errorhandler(Exception)
def handle_all_errors(e):
    sentry_sdk.capture_exception(e)
    return "Internal Server Error", 500

# ===============================
# RUN
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)