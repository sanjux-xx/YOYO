from flask import Flask, render_template, request
from serpapi import GoogleSearch
import re
import os

# ✅ IMPORT FOOD BACKEND (Blueprint)
from food_backend import food_bp

# ===============================
# CREATE FLASK APP FIRST
# ===============================
app = Flask(__name__)

# ===============================
# REGISTER FOOD BLUEPRINT
# ===============================
app.register_blueprint(food_bp)

# ===============================
# HELPERS (SERP PRODUCT SEARCH)
# ===============================

def weight_in_title(title, weight):
    if not weight:
        return True
    pattern = re.escape(weight.lower()).replace("kg", r"\s*-?\s*kg")
    return re.search(pattern, title.lower()) is not None

def extract_price(product):
    try:
        return float(product['price'].replace('₹', '').replace(',', '').strip())
    except:
        return float('inf')

def get_product_prices(query):
    params = {
        "engine": "google_shopping",
        "q": query,
        "location": "India",
        "hl": "en",
        "gl": "in",
        "api_key": "e8de0bc4634c1ad9ebad6b60a681178b0b6ea9dd3bb6880156ca15cdc7b15c19"
    }

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
            "link": link,
            "store": item.get("source", ""),
            "image": item.get("thumbnail", "")
        })

    return products

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

        if query:
            products = get_product_prices(query)
            if weight:
                products = [p for p in products if weight_in_title(p["title"], weight)]

            products = sorted(products, key=extract_price)

    return render_template("index.html", products=products)

# ===============================
# CATEGORY PAGE (NON-FOOD)
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

    products = get_product_prices(final_query)
    products = sorted(products, key=extract_price)

    return render_template("category.html", category=category_name, products=products)

# ===============================
# RUN SERVER
# ===============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)