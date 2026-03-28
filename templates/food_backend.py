from flask import Blueprint, render_template, request
from serpapi import GoogleSearch
import os
import time
import logging

# ===============================
# BLUEPRINT
# ===============================
food_bp = Blueprint("food", __name__, url_prefix="/food")

# ===============================
# CACHE
# ===============================
food_cache = {}
FOOD_CACHE_TTL = 30 * 60  # 30 minutes

# ===============================
# MENU DATA
# Real items + base official prices (₹)
# ===============================
FOOD_DATA = {
    "mcdonalds": {
        "name": "McDonald's",
        "menu": {
            "Burgers": [
                "McAloo Tikki",
                "McVeggie",
                "McChicken",
                "Maharaja Mac",
                "McSpicy Paneer",
                "McSpicy Chicken",
                "Big Spicy Paneer Wrap",
            ],
            "Sides & Snacks": [
                "French Fries (Small)",
                "French Fries (Medium)",
                "French Fries (Large)",
                "Chicken McNuggets (6pc)",
                "Chicken McNuggets (9pc)",
                "Veg Pizza McPuff",
            ],
            "Beverages": [
                "Coke (Small)",
                "Coke (Medium)",
                "Coke (Large)",
                "McCafe Cappuccino",
                "McCafe Latte",
                "Shamrock Shake",
            ],
            "Desserts": [
                "McFlurry Oreo",
                "Soft Serve Cone",
                "Chocolate Shake",
            ],
            "Meals": [
                "McAloo Tikki Meal",
                "McChicken Meal",
                "Maharaja Mac Meal",
            ],
        },
        "prices": {
            "McAloo Tikki":           {"official": 45,  "swiggy": 55,  "zomato": 52},
            "McVeggie":               {"official": 129, "swiggy": 139, "zomato": 135},
            "McChicken":              {"official": 139, "swiggy": 149, "zomato": 145},
            "Maharaja Mac":           {"official": 229, "swiggy": 249, "zomato": 239},
            "McSpicy Paneer":         {"official": 179, "swiggy": 199, "zomato": 189},
            "McSpicy Chicken":        {"official": 189, "swiggy": 209, "zomato": 199},
            "Big Spicy Paneer Wrap":  {"official": 169, "swiggy": 189, "zomato": 179},
            "French Fries (Small)":   {"official": 59,  "swiggy": 69,  "zomato": 65},
            "French Fries (Medium)":  {"official": 99,  "swiggy": 109, "zomato": 105},
            "French Fries (Large)":   {"official": 129, "swiggy": 139, "zomato": 135},
            "Chicken McNuggets (6pc)":{"official": 179, "swiggy": 199, "zomato": 189},
            "Chicken McNuggets (9pc)":{"official": 259, "swiggy": 279, "zomato": 269},
            "Veg Pizza McPuff":       {"official": 49,  "swiggy": 59,  "zomato": 55},
            "Coke (Small)":           {"official": 49,  "swiggy": 59,  "zomato": 55},
            "Coke (Medium)":          {"official": 69,  "swiggy": 79,  "zomato": 75},
            "Coke (Large)":           {"official": 89,  "swiggy": 99,  "zomato": 95},
            "McCafe Cappuccino":      {"official": 129, "swiggy": 149, "zomato": 139},
            "McCafe Latte":           {"official": 119, "swiggy": 139, "zomato": 129},
            "Shamrock Shake":         {"official": 99,  "swiggy": 119, "zomato": 109},
            "McFlurry Oreo":          {"official": 119, "swiggy": 139, "zomato": 129},
            "Soft Serve Cone":        {"official": 49,  "swiggy": 59,  "zomato": 55},
            "Chocolate Shake":        {"official": 129, "swiggy": 149, "zomato": 139},
            "McAloo Tikki Meal":      {"official": 149, "swiggy": 169, "zomato": 159},
            "McChicken Meal":         {"official": 229, "swiggy": 249, "zomato": 239},
            "Maharaja Mac Meal":      {"official": 319, "swiggy": 339, "zomato": 329},
        },
        "buy_links": {
            "official": "https://mcdelivery.co.in",
            "swiggy":   "https://www.swiggy.com/restaurants/mcdonalds",
            "zomato":   "https://www.zomato.com/mcdonalds",
        }
    },

    "pizzahut": {
        "name": "Pizza Hut",
        "menu": {
            "Pizzas (Personal)": [
                "Margherita Personal",
                "Cheese & Tomato Personal",
                "Veggie Supreme Personal",
                "Chicken Supreme Personal",
                "Pepperoni Personal",
            ],
            "Pizzas (Medium)": [
                "Margherita Medium",
                "Double Cheese Margherita Medium",
                "Veggie Supreme Medium",
                "Chicken Supreme Medium",
                "BBQ Chicken Medium",
            ],
            "Pizzas (Large)": [
                "Margherita Large",
                "Veggie Supreme Large",
                "Chicken Supreme Large",
                "BBQ Chicken Large",
            ],
            "Sides": [
                "Garlic Bread",
                "Stuffed Garlic Bread",
                "Chicken Wings (6pc)",
                "Potato Wedges",
                "Coleslaw",
            ],
            "Beverages": [
                "Pepsi (300ml)",
                "Pepsi (500ml)",
                "7UP (300ml)",
            ],
            "Desserts": [
                "Choco Lava Cake",
                "Mango Cheesecake",
            ],
        },
        "prices": {
            "Margherita Personal":          {"official": 149, "swiggy": 169, "zomato": 159},
            "Cheese & Tomato Personal":     {"official": 169, "swiggy": 189, "zomato": 179},
            "Veggie Supreme Personal":      {"official": 199, "swiggy": 219, "zomato": 209},
            "Chicken Supreme Personal":     {"official": 229, "swiggy": 249, "zomato": 239},
            "Pepperoni Personal":           {"official": 249, "swiggy": 269, "zomato": 259},
            "Margherita Medium":            {"official": 299, "swiggy": 329, "zomato": 319},
            "Double Cheese Margherita Medium": {"official": 349, "swiggy": 379, "zomato": 369},
            "Veggie Supreme Medium":        {"official": 399, "swiggy": 429, "zomato": 419},
            "Chicken Supreme Medium":       {"official": 449, "swiggy": 479, "zomato": 469},
            "BBQ Chicken Medium":           {"official": 469, "swiggy": 499, "zomato": 489},
            "Margherita Large":             {"official": 449, "swiggy": 489, "zomato": 469},
            "Veggie Supreme Large":         {"official": 549, "swiggy": 589, "zomato": 569},
            "Chicken Supreme Large":        {"official": 649, "swiggy": 689, "zomato": 669},
            "BBQ Chicken Large":            {"official": 699, "swiggy": 739, "zomato": 719},
            "Garlic Bread":                 {"official": 99,  "swiggy": 119, "zomato": 109},
            "Stuffed Garlic Bread":         {"official": 149, "swiggy": 169, "zomato": 159},
            "Chicken Wings (6pc)":          {"official": 199, "swiggy": 219, "zomato": 209},
            "Potato Wedges":                {"official": 99,  "swiggy": 119, "zomato": 109},
            "Coleslaw":                     {"official": 59,  "swiggy": 79,  "zomato": 69},
            "Pepsi (300ml)":                {"official": 49,  "swiggy": 59,  "zomato": 55},
            "Pepsi (500ml)":                {"official": 69,  "swiggy": 79,  "zomato": 75},
            "7UP (300ml)":                  {"official": 49,  "swiggy": 59,  "zomato": 55},
            "Choco Lava Cake":              {"official": 99,  "swiggy": 119, "zomato": 109},
            "Mango Cheesecake":             {"official": 129, "swiggy": 149, "zomato": 139},
        },
        "buy_links": {
            "official": "https://www.pizzahut.co.in",
            "swiggy":   "https://www.swiggy.com/restaurants/pizza-hut",
            "zomato":   "https://www.zomato.com/pizza-hut",
        }
    },

    "dominos": {
        "name": "Domino's",
        "menu": {
            "Pizzas (Regular)": [
                "Margherita Regular",
                "Double Cheese Margherita Regular",
                "Peppy Paneer Regular",
                "Chicken Dominator Regular",
                "Keema Do Pyaza Regular",
            ],
            "Pizzas (Medium)": [
                "Margherita Medium",
                "Double Cheese Margherita Medium",
                "Peppy Paneer Medium",
                "Chicken Dominator Medium",
                "Farmhouse Medium",
            ],
            "Pizzas (Large)": [
                "Margherita Large",
                "Peppy Paneer Large",
                "Chicken Dominator Large",
                "Farmhouse Large",
                "Veg Extravaganza Large",
            ],
            "Sides": [
                "Garlic Breadsticks",
                "Stuffed Garlic Bread",
                "Chicken Wings",
                "Pasta Italiana White",
                "Pasta Italiana Red",
            ],
            "Beverages": [
                "Coke (300ml)",
                "Coke (500ml)",
                "Sprite (300ml)",
                "Fanta (300ml)",
            ],
            "Desserts": [
                "Choco Lava Cake",
                "Butterscotch Mousse Cake",
            ],
        },
        "prices": {
            "Margherita Regular":               {"official": 149, "swiggy": 169, "zomato": 159},
            "Double Cheese Margherita Regular": {"official": 199, "swiggy": 219, "zomato": 209},
            "Peppy Paneer Regular":             {"official": 219, "swiggy": 239, "zomato": 229},
            "Chicken Dominator Regular":        {"official": 269, "swiggy": 289, "zomato": 279},
            "Keema Do Pyaza Regular":           {"official": 249, "swiggy": 269, "zomato": 259},
            "Margherita Medium":                {"official": 249, "swiggy": 279, "zomato": 269},
            "Double Cheese Margherita Medium":  {"official": 299, "swiggy": 329, "zomato": 319},
            "Peppy Paneer Medium":              {"official": 349, "swiggy": 379, "zomato": 369},
            "Chicken Dominator Medium":         {"official": 399, "swiggy": 429, "zomato": 419},
            "Farmhouse Medium":                 {"official": 379, "swiggy": 409, "zomato": 399},
            "Margherita Large":                 {"official": 399, "swiggy": 439, "zomato": 419},
            "Peppy Paneer Large":               {"official": 549, "swiggy": 589, "zomato": 569},
            "Chicken Dominator Large":          {"official": 649, "swiggy": 689, "zomato": 669},
            "Farmhouse Large":                  {"official": 599, "swiggy": 639, "zomato": 619},
            "Veg Extravaganza Large":           {"official": 649, "swiggy": 689, "zomato": 669},
            "Garlic Breadsticks":               {"official": 99,  "swiggy": 119, "zomato": 109},
            "Stuffed Garlic Bread":             {"official": 149, "swiggy": 169, "zomato": 159},
            "Chicken Wings":                    {"official": 179, "swiggy": 199, "zomato": 189},
            "Pasta Italiana White":             {"official": 149, "swiggy": 169, "zomato": 159},
            "Pasta Italiana Red":               {"official": 149, "swiggy": 169, "zomato": 159},
            "Coke (300ml)":                     {"official": 49,  "swiggy": 59,  "zomato": 55},
            "Coke (500ml)":                     {"official": 69,  "swiggy": 79,  "zomato": 75},
            "Sprite (300ml)":                   {"official": 49,  "swiggy": 59,  "zomato": 55},
            "Fanta (300ml)":                    {"official": 49,  "swiggy": 59,  "zomato": 55},
            "Choco Lava Cake":                  {"official": 109, "swiggy": 129, "zomato": 119},
            "Butterscotch Mousse Cake":         {"official": 99,  "swiggy": 119, "zomato": 109},
        },
        "buy_links": {
            "official": "https://www.dominos.co.in",
            "swiggy":   "https://www.swiggy.com/restaurants/dominos",
            "zomato":   "https://www.zomato.com/dominos",
        }
    },
}


# ===============================
# HELPERS
# ===============================
def slug_to_item(slug):
    """Convert url slug back to item name e.g. mc-aloo-tikki → McAloo Tikki"""
    return slug.replace("-", " ").title()


def item_to_slug(item):
    """Convert item name to url slug"""
    return item.lower().replace(" ", "-")


def get_serpapi_prices(item_name, brand_name):
    """
    Use SerpAPI to fetch live price data for a food item.
    Falls back to None if unavailable.
    """
    cache_key = f"food_{brand_name}_{item_name}".lower().strip()
    now = time.time()

    if cache_key in food_cache:
        data, ts = food_cache[cache_key]
        if now - ts < FOOD_CACHE_TTL:
            return data

    try:
        params = {
            "engine": "google_shopping",
            "q": f"{item_name} {brand_name} India price",
            "location": "India",
            "hl": "en",
            "gl": "in",
            "api_key": os.getenv("SERPAPI_KEY")
        }
        results = GoogleSearch(params).get_dict()
        items = results.get("shopping_results", [])

        live_prices = {"swiggy": None, "zomato": None, "official": None}

        for item in items[:10]:
            source = item.get("source", "").lower()
            price_str = item.get("price", "")
            try:
                price = float(price_str.replace("₹", "").replace(",", "").strip())
            except:
                continue

            if "swiggy" in source and not live_prices["swiggy"]:
                live_prices["swiggy"] = int(price)
            elif "zomato" in source and not live_prices["zomato"]:
                live_prices["zomato"] = int(price)

        food_cache[cache_key] = (live_prices, now)
        return live_prices

    except Exception as e:
        logging.error(f"SerpAPI food error: {e}")
        return None


def get_prices_for_item(brand_key, item_name):
    """
    Get prices for an item — use hardcoded data as base,
    try to enrich with SerpAPI live data.
    """
    brand = FOOD_DATA.get(brand_key, {})
    base_prices = brand.get("prices", {}).get(item_name, {})

    # Start with hardcoded prices
    prices = {
        "official": base_prices.get("official"),
        "swiggy":   base_prices.get("swiggy"),
        "zomato":   base_prices.get("zomato"),
    }

    return prices


# ===============================
# ROUTES
# ===============================

# ── /food — Brand listing page ──
@food_bp.route("/")
def food_home():
    return render_template("food.html")


# ── /food/<brand> — Brand menu page ──
@food_bp.route("/<brand>")
def food_brand_page(brand):
    brand_data = FOOD_DATA.get(brand)

    if not brand_data:
        return render_template(
            "food.html",
            error=f"Brand '{brand}' not found."
        ), 404

    return render_template(
        "food_brand.html",
        brand_name=brand_data["name"],
        brand_key=brand,
        menu=brand_data["menu"],
    )


# ── /food/<brand>/<item_slug> — Item price comparison ──
@food_bp.route("/<brand>/<item_slug>")
def food_item_page(brand, item_slug):
    brand_data = FOOD_DATA.get(brand)

    if not brand_data:
        return render_template("food.html", error="Brand not found."), 404

    # Convert slug back to item name
    item_name = slug_to_item(item_slug)

    # Try to find exact match in menu (case-insensitive)
    all_items = [
        item
        for items in brand_data["menu"].values()
        for item in items
    ]
    matched = next(
        (i for i in all_items if i.lower() == item_name.lower()),
        None
    )

    if not matched:
        return render_template(
            "food_brand.html",
            brand_name=brand_data["name"],
            brand_key=brand,
            menu=brand_data["menu"],
            error=f"Item '{item_name}' not found in menu."
        ), 404

    item_name = matched
    prices = get_prices_for_item(brand, item_name)
    buy_links = brand_data.get("buy_links", {})

    # Get selected city (default: bangalore)
    city = request.args.get("city", "bangalore").lower()

    return render_template(
        "food_item.html",
        item_name=item_name,
        brand=brand,
        brand_name=brand_data["name"],
        prices=prices,
        buy_links=buy_links,
        city=city,
    )