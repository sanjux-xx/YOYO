from flask import Flask, render_template, request
from serpapi import GoogleSearch
import re

app = Flask(__name__)

# Smart matching for weight variants like "5kg", "5 kg", "5-kg"
def weight_in_title(title, weight):
    if not weight:
        return True
    pattern = re.escape(weight.lower()).replace("kg", r"\s*-?\s*kg")
    return re.search(pattern, title.lower()) is not None

# Convert price to float for sorting
def extract_price(product):
    try:
        return float(product['price'].replace('₹', '').replace(',', '').strip())
    except:
        return float('inf')

# Fetch product data from SerpAPI
def get_product_prices(query):
    params = {
        "engine": "google_shopping",
        "q": query,
        "location": "India",
        "hl": "en",
        "gl": "in",
        "api_key": "e8de0bc4634c1ad9ebad6b60a681178b0b6ea9dd3bb6880156ca15cdc7b15c19"  # ← replace with your real key
    }

    search = GoogleSearch(params)
    results = search.get_dict()

    products = []
    for item in results.get("shopping_results", []):
        products.append({
            "title": item.get("title", ""),
            "price": item.get("price", ""),
            "link": item.get("link", ""),
            "store": item.get("source", ""),
            "image": item.get("thumbnail", "")
        })

    return products

# Main route for search
@app.route("/", methods=["GET", "POST"])
def index():
    products = []

    if request.method == "POST":
        product = request.form.get("product_query", "").strip()
        brand = request.form.get("brand_filter", "").strip()
        weight = request.form.get("weight_filter", "").strip()

        # Combine query terms
        search_query = " ".join([product, brand, weight]).strip()
        print("🔍 Search Query:", search_query)

        if search_query:
            all_products = get_product_prices(search_query)

            # Post-filter products that actually contain the weight in title
            if weight:
                products = [p for p in all_products if weight_in_title(p['title'], weight)]
            else:
                products = all_products

            # Sort results by price (ascending)
            products = sorted(products, key=extract_price)

    return render_template("index.html", products=products)

# ✅ Start Flask app
if __name__ == "__main__":
    app.run(debug=True)