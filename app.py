from flask import Flask, request
import csv
import textwrap

import os
import requests

def download_wine_csv():
    url = f'https://drive.google.com/uc?export=download&id=164v84UzMXctzMiL-KPJQpH6visSWwN8S'
    dest = 'winemag-data-130k-v2.csv'
    # Download only if not present
    print("Downloading CSV from Google Drive...")
    resp = requests.get(url)
    with open(dest, 'wb') as f:
        f.write(resp.content)
    print("Download complete.")

app = Flask(__name__)

CSV_FILE = "winemag-data-130k-v2.csv"  # Kaggle wine reviews file


def sweetness_from_desc(text: str) -> str:
    if not text:
        return "Medium"
    t = text.lower()

    dry_words = [
        "bone-dry", "bone dry", "very dry", "crisp", "taut",
        "zesty", "racy acidity", "high acidity", "bracing acidity",
        "lean", "minerally", "chalky", "steely"
    ]
    medium_words = [
        "off-dry", "off dry", "hint of sweetness", "touch of sweetness",
        "slightly sweet", "trace of sweetness", "kiss of sweetness",
        "ripe fruit", "lush", "round and fruity"
    ]
    sweet_words = [
        "dessert wine", "dessert-style", "late harvest", "ice wine",
        "port", "sauternes", "moscato", "sticky",
        "honeyed", "very sweet", "syrupy", "unctuous"
    ]

    has_dry = any(w in t for w in dry_words)
    has_med = any(w in t for w in medium_words)
    has_sweet = any(w in t for w in sweet_words)

    if has_sweet:
        if has_dry or has_med:
            return "Medium"
        return "Sweet"

    if has_dry and not has_med:
        return "Dry"

    if has_med:
        return "Medium"

    if "dry" in t:
        return "Dry"

    return "Medium"


def style_tags_from_desc(text: str):
    tags = set()
    if not text:
        return tags

    t = text.lower()

    fruity_words = [
        "fruit", "berries", "berry", "plum", "peach", "apple", "pear",
        "cherry", "citrus", "orange", "lemon", "lime", "grapefruit",
        "tropical", "mango", "pineapple"
    ]
    spicy_words = ["spice", "spicy", "pepper", "clove", "cinnamon", "nutmeg", "anise"]
    floral_words = ["floral", "flower", "violet", "rose", "jasmine", "honeysuckle"]
    earthy_words = ["earthy", "earth", "mushroom", "forest floor", "leather", "tobacco"]

    if any(w in t for w in fruity_words):
        tags.add("Fruity")
    if any(w in t for w in spicy_words):
        tags.add("Spicy")
    if any(w in t for w in floral_words):
        tags.add("Floral")
    if any(w in t for w in earthy_words):
        tags.add("Earthy")

    return tags



def load_wines(limit=3000):
    wines = []
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("price") or not row.get("title"):
                continue

            desc = row.get("description") or ""
            sweetness = sweetness_from_desc(desc)
            tags = style_tags_from_desc(desc)

            row["sweetness_cat"] = sweetness
            row["style_tags"] = ", ".join(sorted(tags))

            # ensure numeric fields as strings we can cast later
            row["price"] = row.get("price")
            row["points"] = row.get("points")  # Wine Enthusiast score

            wines.append(row)

            if len(wines) >= limit:
                break
    return wines


@app.route("/", methods=["GET", "POST"])
def index():
    download_wine_csv()
    wines = load_wines()

    country = ""
    max_price = ""
    variety = ""
    sweetness = ""
    style = ""
    sort = ""

    results = []

    if request.method == "POST":
        country = request.form.get("country", "").strip()
        max_price = request.form.get("max_price", "").strip()
        variety = request.form.get("variety", "").strip()
        sweetness = request.form.get("sweetness", "").strip()
        style = request.form.get("style", "").strip()
        sort = request.form.get("sort", "").strip()

        filtered = wines

        if country:
            filtered = [
                w for w in filtered
                if w.get("country") and country.lower() in w["country"].lower()
            ]

        if variety:
            filtered = [
                w for w in filtered
                if w.get("variety") and variety.lower() in w["variety"].lower()
            ]

        if max_price:
            try:
                p = float(max_price)
                filtered = [
                    w for w in filtered
                    if w.get("price") and float(w["price"]) <= p
                ]
            except ValueError:
                pass

        if sweetness:
            filtered = [
                w for w in filtered
                if w.get("sweetness_cat") and w["sweetness_cat"].lower() == sweetness.lower()
            ]

        if style:
            filtered = [
                w for w in filtered
                if w.get("style_tags") and style in w["style_tags"].split(", ")
            ]

        # ---- SORTING LOGIC ----
        if sort == "price_asc":
            filtered = sorted(
                filtered,
                key=lambda w: float(w["price"]) if w.get("price") else 10**9
            )
        elif sort == "price_desc":
            filtered = sorted(
                filtered,
                key=lambda w: float(w["price"]) if w.get("price") else -1,
                reverse=True
            )
        elif sort == "points_desc":  # user recommended = highest rating first
            filtered = sorted(
                filtered,
                key=lambda w: float(w["points"]) if w.get("points") else 0,
                reverse=True
            )

        results = filtered[:80]

    html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Wines of the World Explorer </title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 30px; background: #faf5f0; }}
    h1 {{ color: #5a0b0b; }}
    form {{ margin-bottom: 20px; padding: 10px; background: #fff; border-radius: 8px; }}
    label {{ display: inline-block; margin-right: 15px; margin-bottom: 8px; }}
    input, select {{ padding: 4px 6px; }}
    button {{ padding: 6px 12px; background: #5a0b0b; color: #fff; border: none; border-radius: 4px; cursor: pointer; }}
    button:hover {{ background: #7a1010; }}
    .wine-card {{ background: #fff; margin-bottom: 10px; padding: 10px; border-radius: 8px; border: 1px solid #ddd; }}
    .title {{ font-weight: bold; color: #333; }}
    .meta {{ font-size: 0.9em; color: #555; }}
    .desc {{ margin-top: 5px; font-size: 0.9em; color: #444; }}
    .tags {{ margin-top: 4px; font-size: 0.85em; color: #666; }}
  </style>
</head>
<body>
  <h1>Wines of the World</h1>
  <p>Search real wines by country, price, grape variety, sweetness, style and sort by price or rating.</p>

  <form method="POST">
    <label>
      Country:
      <input type="text" name="country" value="{country}">
    </label>

    <label>
      Variety:
      <select name="variety">
        <option value="">Any</option>
        <option value="Cabernet Sauvignon" {v_cab}>Cabernet Sauvignon</option>
        <option value="Merlot" {v_merlot}>Merlot</option>
        <option value="Pinot Noir" {v_pinot_noir}>Pinot Noir</option>
        <option value="Syrah" {v_syrah}>Syrah / Shiraz</option>
        <option value="Chardonnay" {v_chard}>Chardonnay</option>
        <option value="Sauvignon Blanc" {v_sauv}>Sauvignon Blanc</option>
        <option value="Riesling" {v_ries}>Riesling</option>
        <option value="Pinot Grigio" {v_pg}>Pinot Grigio / Gris</option>
        <option value="Zinfandel" {v_zin}>Zinfandel</option>
        <option value="Malbec" {v_malbec}>Malbec</option>
        <option value="Sparkling" {v_spark}>Any Sparkling</option>
      </select>
    </label>

    <label>
      Max price:
      <input type="number" name="max_price" step="1" value="{max_price}">
    </label>

    <label>
      Sweetness:
      <select name="sweetness">
        <option value="">Any</option>
        <option value="Dry" {s_dry}>Dry</option>
        <option value="Medium" {s_med}>Medium</option>
        <option value="Sweet" {s_sweet}>Sweet</option>
      </select>
    </label>

    <label>
      Style:
      <select name="style">
        <option value="">Any</option>
        <option value="Fruity" {st_fruity}>Fruity</option>
        <option value="Spicy" {st_spicy}>Spicy</option>
        <option value="Floral" {st_floral}>Floral</option>
        <option value="Earthy" {st_earthy}>Earthy</option>
      </select>
    </label>

    <label>
      Sort:
      <select name="sort">
        <option value="">Default</option>
        <option value="price_asc" {sort_p_asc}>Price: Low to High</option>
        <option value="price_desc" {sort_p_desc}>Price: High to Low</option>
        <option value="points_desc" {sort_pts_desc}>User Recommended (Rating)</option>
      </select>
    </label>

    <button type="submit">Search</button>
  </form>

  {results_html}
</body>
</html>
"""

    if results:
        cards = []
        for w in results:
            title = w.get("title", "Unknown wine")
            variety_val = w.get("variety", "Unknown variety")
            country_val = w.get("country", "Unknown country")
            price_val = w.get("price", "?")
            desc = w.get("description", "")
            sweetness_cat = w.get("sweetness_cat", "Medium")
            style_tags = w.get("style_tags", "")
            points = w.get("points", "")

            desc_wrapped = "<br>".join(textwrap.wrap(desc, 120))

            card = f"""
            <div class="wine-card">
              <div class="title">{title}</div>
              <div class="meta">
                {variety_val} – {country_val} – ${price_val} – {points} pts – Sweetness: {sweetness_cat}
              </div>
              <div class="tags">Style: {style_tags}</div>
              <div class="desc">{desc_wrapped}</div>
            </div>
            """
            cards.append(card)

        results_html = f"<h2>Results (showing {len(results)} wines)</h2>" + "".join(cards)
    else:
        results_html = "<p>No results yet. Submit the form to see wines.</p>"

    sweetness_lower = sweetness.lower()

    page = html.format(
        country=country,
        max_price=max_price,
        results_html=results_html,
        s_dry="selected" if sweetness_lower == "dry" else "",
        s_med="selected" if sweetness_lower == "medium" else "",
        s_sweet="selected" if sweetness_lower == "sweet" else "",
        st_fruity="selected" if style == "Fruity" else "",
        st_spicy="selected" if style == "Spicy" else "",
        st_floral="selected" if style == "Floral" else "",
        st_earthy="selected" if style == "Earthy" else "",
        v_cab="selected" if variety == "Cabernet Sauvignon" else "",
        v_merlot="selected" if variety == "Merlot" else "",
        v_pinot_noir="selected" if variety == "Pinot Noir" else "",
        v_syrah="selected" if variety == "Syrah" else "",
        v_chard="selected" if variety == "Chardonnay" else "",
        v_sauv="selected" if variety == "Sauvignon Blanc" else "",
        v_ries="selected" if variety == "Riesling" else "",
        v_pg="selected" if variety == "Pinot Grigio" else "",
        v_zin="selected" if variety == "Zinfandel" else "",
        v_malbec="selected" if variety == "Malbec" else "",
        v_spark="selected" if variety == "Sparkling" else "",
        sort_p_asc="selected" if sort == "price_asc" else "",
        sort_p_desc="selected" if sort == "price_desc" else "",
        sort_pts_desc="selected" if sort == "points_desc" else ""
    )
    return page


if __name__ == "__main__":
    app.run(debug=True)

