from flask import Blueprint, render_template, request

food_bp = Blueprint("food", __name__, url_prefix="/food")

# ===============================
# FOOD DATA (STRINGS ONLY)
# ===============================
FOOD_DATA = {
    "dominos": {
        "name": "Domino's",
        "menu": {
            "Pizza Mania": [
                "Classic Veg",
                "Classic Onion Capsicum",
                "Classic Corn",
                "Classic Tomato"
            ]
        }
    },
    "pizzahut": {
        "name": "Pizza Hut",
        "menu": {
            "Pizzas": [
                "Margherita",
                "Veggie Supreme"
            ]
        }
    },
    "mcdonalds": {
        "name": "McDonald's",
        "menu": {
            "Burgers": [
                "McAloo Tikki",
                "McVeggie"
            ]
        }
    }
}

# ===============================
# ROUTES
# ===============================

@food_bp.route("/")
def food_home():
    return render_template("food.html")


@food_bp.route("/<brand>")
def food_brand(brand):
    brand_key = brand.lower()
    brand_data = FOOD_DATA.get(brand_key)

    if not brand_data:
        return "Brand not found", 404

    return render_template(
        "food_brand.html",
        brand_name=brand_data["name"],
        brand_key=brand_key,
        menu=brand_data["menu"]
    )


@food_bp.route("/<brand>/<item_slug>")
def food_item_page(brand, item_slug):
    brand_key = brand.lower()
    brand_data = FOOD_DATA.get(brand_key)

    if not brand_data:
        return "Brand not found", 404

    # -------------------------------
    # SLUG → NAME MATCH (SAFE)
    # -------------------------------
    def slugify(text):
        return text.lower().replace("&", "").replace(" ", "-")

    item_name = None
    for items in brand_data["menu"].values():
        for item in items:
            if slugify(item) == item_slug:
                item_name = item
                break

    if not item_name:
        return "Item not found", 404

    # -------------------------------
    # CITY BASED PRICES (DUMMY)
    # -------------------------------
    city = request.args.get("city", "bangalore").lower()

    PRICE_DATA = {
        "bangalore": {"official": 199, "swiggy": 219, "zomato": 209},
        "mumbai": {"official": 189, "swiggy": 229, "zomato": 215},
        "delhi": {"official": 195, "swiggy": 225, "zomato": 210}
    }

    prices = PRICE_DATA.get(city, PRICE_DATA["bangalore"])

    # -------------------------------
    # BUY LINKS (WORKING)
    # -------------------------------
    official_links = {
        "dominos": "https://www.dominos.co.in",
        "pizzahut": "https://www.pizzahut.co.in",
        "mcdonalds": "https://www.mcdonaldsindia.com"
    }

    return render_template(
        "food_item.html",
        brand=brand_key,
        item_name=item_name,
        city=city,
        prices=prices,
        buy_links={
            "official": official_links.get(brand_key, "#"),
            "swiggy": "https://www.swiggy.com",
            "zomato": "https://www.zomato.com"
        }
    )