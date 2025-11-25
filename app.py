# app.py
from flask import Flask, request, redirect, url_for, render_template_string
import csv, textwrap, os, requests, threading, time, math

app = Flask(__name__)

CSV_FILE = "winemag-data-130k-v2.csv"
CSV_DRIVE_URL = ("https://drive.google.com/uc?export=download&id="
                 "164v84UzMXctzMiL-KPJQpH6visSWwN8S")
# tune how many rows to load into memory for fast response (lower if you want)
LOAD_LIMIT = 5000

# simple in-memory cache
WINES_CACHE = {"loading": False, "loaded": False, "wines": [], "rows": 0, "last_error": None}

# ---------- CSV download + load helpers ----------
def download_wine_csv():
    """Download CSV from google drive to local file (sync)."""
    try:
        WINES_CACHE["loading"] = True
        WINES_CACHE["last_error"] = None
        url = CSV_DRIVE_URL
        dest = CSV_FILE
        app.logger.info("Downloading CSV from Google Drive...")
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)
        app.logger.info("CSV download complete.")
    except Exception as e:
        WINES_CACHE["last_error"] = str(e)
        app.logger.exception("Download failed")
    finally:
        WINES_CACHE["loading"] = False

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

def safe_float(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except:
        return default

def load_wines(limit=LOAD_LIMIT):
    wines = []
    if not os.path.exists(CSV_FILE):
        return wines

    with open(CSV_FILE, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # require at least title and a price or points to be useful
            if not row.get("title"):
                continue

            desc = row.get("description") or ""
            sweetness = sweetness_from_desc(desc)
            tags = style_tags_from_desc(desc)

            # sanitize
            price_str = row.get("price", "").strip()
            points_str = row.get("points", "").strip()

            row["sweetness_cat"] = sweetness
            row["style_tags"] = ", ".join(sorted(tags))
            row["price"] = price_str
            row["points"] = points_str

            wines.append(row)

            if len(wines) >= limit:
                break
    return wines

def ensure_wines_loaded():
    """Ensure wines are downloaded+loaded. Synchronous call; caches result."""
    if WINES_CACHE["loaded"]:
        return

    # If file missing, download synchronously (blocking) so the user can use the app.
    if not os.path.exists(CSV_FILE):
        app.logger.info("CSV not found locally — downloading now...")
        download_wine_csv()
        # if download failed, WINES_CACHE["last_error"] will be set

    # Load into memory (cache)
    wines = load_wines()
    WINES_CACHE["wines"] = wines
    WINES_CACHE["rows"] = len(wines)
    WINES_CACHE["loaded"] = True

# ---------- Flask routes ----------
@app.route("/", methods=["GET", "POST"])
def index():
    # ensure CSV is present & wines loaded
    ensure_wines_loaded()
    if WINES_CACHE["last_error"]:
        return f"<h2>Download error:</h2><pre>{WINES_CACHE['last_error']}</pre><p>Check logs or try again.</p>"

    wines = WINES_CACHE["wines"]

    # form fields
    country = request.form.get("country", "").strip()
    max_price = request.form.get("max_price", "").strip()
    variety = request.form.get("variety", "").strip()
    sweetness = request.form.get("sweetness", "").strip()
    style = request.form.get("style", "").strip()
    sort = request.form.get("sort", "").strip()
    page = int(request.values.get("page", 1))
    per_page = 12

    filtered = list(wines)  # shallow copy

    # filters
    if country:
        filtered = [w for w in filtered if w.get("country") and country.lower() in w["country"].lower()]

    if variety:
        v = variety.lower()
        def variety_match(w):
            wv = (w.get("variety") or "").lower()
            # match partials (e.g., "sparkling" should match "sparkling rosé")
            return v in wv
        filtered = [w for w in filtered if variety_match(w)]

    if max_price:
        try:
            p = float(max_price)
            filtered = [w for w in filtered if safe_float(w.get("price")) is not None and safe_float(w.get("price")) <= p]
        except ValueError:
            pass

    if sweetness:
        filtered = [w for w in filtered if w.get("sweetness_cat") and w["sweetness_cat"].lower() == sweetness.lower()]

    if style:
        filtered = [w for w in filtered if w.get("style_tags") and style in w["style_tags"].split(", ")]

    # sorting
    if sort == "price_asc":
        filtered = sorted(filtered, key=lambda w: safe_float(w.get("price"), 10**9))
    elif sort == "price_desc":
        filtered = sorted(filtered, key=lambda w: safe_float(w.get("price"), -1), reverse=True)
    elif sort == "points_desc":
        filtered = sorted(filtered, key=lambda w: safe_float(w.get("points"), 0), reverse=True)

    total = len(filtered)
    total_pages = max(1, math.ceil(total / per_page))
    if page < 1: page = 1
    if page > total_pages: page = total_pages

    start = (page - 1) * per_page
    results = filtered[start:start + per_page]

    # render page using a single template string (pasteable)
    template = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Wines of the World — Explorer</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #f7f4ef;
      --card: #fff8f6;
      --muted: #7c7171;
      --accent: #943232;
      --accent2: #5a2130;
      --divider: #eddad5;
    }
    [data-theme="dark"]{
      --bg: #181319;
      --card: #232024;
      --muted: #cebdbc;
      --accent: #e6b198;
      --accent2: #a87362;
      --divider: #3a2836;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial;
      background: var(--bg);
      color: #24110a;
    }
    .centered {
      text-align: center;
      margin-top: 32px;
      margin-bottom: 16px;
    }
    h1 {
      color: var(--accent2);
      font-size: 2.35rem;
      font-weight: 700;
      margin: 0 0 0.5em 0;
      letter-spacing: -1px;
      text-shadow: 0 3px 24px rgba(90,33,48, 0.18);
      text-align: center;
    }
    .sub {
      color: var(--muted);
      font-size: 1.07rem;
      margin-bottom: 18px;
      text-align: center;
    }
    form.search-form {
      background: var(--card);
      border-radius: 18px;
      padding: 30px 24px 18px 24px;
      border: 1px solid var(--divider);
      display: grid;
      grid-template-columns: repeat(auto-fit,minmax(220px,1fr));
      gap: 22px;
      align-items: end;
      box-shadow: 0 10px 30px rgba(90,33,48,0.08);
      color: #432218;
      margin-bottom: 10px;
      max-width: 100vw;
    }
    label { font-weight: 600; font-size: 1rem; color: var(--accent2); }
    input[type="text"], input[type="number"], select {
      padding: 10px;
      border-radius: 9px;
      border: 1px solid #e7d1c5;
      background: #fff8f6;
      font-size: 1rem;
      width: 100%;
      margin-top: 7px;
      color: #432218;
      transition: border .18s;
    }
    input[type="text"]:focus, input[type="number"]:focus, select:focus {
      border-color: var(--accent2);
      outline: none;
    }
    .search-btn-row {
      grid-column: 1/-1;
      display: flex;
      justify-content: center;
      margin-top: 12px;
      margin-bottom: 4px;
    }
    .btn {
      background: linear-gradient(180deg,var(--accent),var(--accent2));
      border: none;
      color: white;
      padding: 12px 36px;
      border-radius: 12px;
      cursor: pointer;
      font-weight: 700;
      font-size: 1.08rem;
      letter-spacing:1px;
      box-shadow:0 6px 18px rgba(90,33,48,0.14);
      transition: background .19s, box-shadow .14s;
      margin-bottom:2px;
    }
    .btn:active { background: #d47a78; }

    .results-meta {
      margin-top: 10px;
      margin-bottom: 10px;
      color: var(--muted);
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.98rem;
      padding: 0 24px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit,minmax(300px,1fr));
      gap: 24px;
      margin: 20px 0;
      padding: 0 18px;
    }
    .wine-card {
      background: var(--card);
      border-radius: 17px;
      padding: 18px 15px 16px 15px;
      border: 1px solid var(--divider);
      box-shadow: 0 8px 24px rgba(90,33,48,0.06);
      transition: transform .16s, box-shadow .16s;
      overflow: visible;
      min-height: 180px;
      word-break: break-word;
      display: flex;
      flex-direction: column;
    }
    .wine-card:hover {transform:translateY(-2px) scale(1.01);box-shadow:0 16px 40px rgba(90,33,48,0.12);}
    .title { font-weight:700; color: var(--accent2); margin-bottom:7px; font-size:1.22rem; text-align:left;}
    .meta { color:var(--muted); font-size:1rem; margin-bottom:8px; }
    .tags { font-size:0.93rem; color:#a87362; margin-bottom:9px; }
    .desc { color:#32221a; font-size:1rem; line-height:1.38; margin-top:2px; white-space:pre-line; word-break:break-word; }
    .pagination {
      display:flex; gap:10px; align-items:center; justify-content:center; margin:24px 0 36px 0;
    }
    .page-btn {
      padding:8px 14px;
      border-radius:8px;
      border:1px solid var(--divider);
      background:var(--card);
      cursor:pointer;
      font-size:1rem;
      color: var(--accent2);
    }
    .page-btn.active {
      background: var(--accent);
      color: white;
      border:none;
      box-shadow:0 6px 16px rgba(90,11,11,0.13);
    }
    @media (max-width:650px){
      h1{font-size:1.4rem;}
      .search-form{padding:16px 3px;}
      .grid{grid-template-columns:1fr;padding:0 2px;}
      .wine-card{padding:14px 4px; font-size:0.96rem;}
      .results-meta{padding:0 7px;}
    }
    [data-theme="dark"] body { color: #f7f4ef; background: var(--bg);}
    [data-theme="dark"] h1 { color: #e6b198;text-shadow: 0 3px 14px #482619a9;}
    [data-theme="dark"] .sub { color: #cebdbc;}
    [data-theme="dark"] .search-form,
    [data-theme="dark"] .wine-card {background: var(--card);}
    [data-theme="dark"] label{ color: #e6b198; }
    [data-theme="dark"] input, [data-theme="dark"] select {background: #232024; color: #e6b198; border-color: #a87362;}
    [data-theme="dark"] .title{color:#e6b198;}
    [data-theme="dark"] .desc{color:#ecdccb;}
    [data-theme="dark"] .meta{color:#cebdbc;}
    [data-theme="dark"] .tags{color:#e6b198;}
    [data-theme="dark"] .btn{background:linear-gradient(180deg,#e6b198,#a87362);}
    [data-theme="dark"] .page-btn{background:#31222a;color:#e6b198;}
    [data-theme="dark"] .page-btn.active{background:#943232;color:#fff;}
  </style>
</head>
<body>
  <div class="centered">
    <h1>Wines of the World Explorer</h1>
    <div class="sub">Discover, filter, and browse world wines by taste, style, country, and price. Try dark mode!</div>
  </div>

  <form method="POST" class="search-form" id="searchForm">
    <label>Country
      <input type="text" name="country" value="{{ country }}">
    </label>
    <label>Variety
      <select name="variety">
        <option value="">Any</option>
        {% for v in ["Cabernet Sauvignon","Merlot","Pinot Noir","Syrah","Chardonnay","Sauvignon Blanc","Riesling","Pinot Grigio","Zinfandel","Malbec","Sparkling"] %}
          <option value="{{v}}" {% if v==variety %}selected{% endif %}>{{ v }}</option>
        {% endfor %}
      </select>
    </label>
    <label>Max price ($)
      <input type="number" name="max_price" step="1" value="{{ max_price }}">
    </label>
    <label>Sweetness
      <select name="sweetness">
        <option value="">Any</option>
        <option value="Dry" {% if sweetness == "Dry" %}selected{% endif %}>Dry</option>
        <option value="Medium" {% if sweetness == "Medium" %}selected{% endif %}>Medium</option>
        <option value="Sweet" {% if sweetness == "Sweet" %}selected{% endif %}>Sweet</option>
      </select>
    </label>
    <label>Style
      <select name="style">
        <option value="">Any</option>
        <option value="Fruity" {% if style=="Fruity" %}selected{% endif %}>Fruity</option>
        <option value="Spicy" {% if style=="Spicy" %}selected{% endif %}>Spicy</option>
        <option value="Floral" {% if style=="Floral" %}selected{% endif %}>Floral</option>
        <option value="Earthy" {% if style=="Earthy" %}selected{% endif %}>Earthy</option>
      </select>
    </label>
    <label>Sort
      <select name="sort">
        <option value="">Default</option>
        <option value="price_asc" {% if sort=="price_asc" %}selected{% endif %}>Price: Low → High</option>
        <option value="price_desc" {% if sort=="price_desc" %}selected{% endif %}>Price: High → Low</option>
        <option value="points_desc" {% if sort=="points_desc" %}selected{% endif %}>Top-rated</option>
      </select>
    </label>
    <div class="search-btn-row">
      <button class="btn" type="submit">Search</button>
    </div>
  </form>

  <div class="results-meta">
    <span>{{ WINES_CACHE_rows }} loaded · page {{ page }} / {{ total_pages }}</span>
    <span>Tip: try “Riesling” + sweetness=Sweet or “Pinot Noir” + style=Earthy</span>
  </div>

  <div class="grid">
    {% if results %}
      {% for w in results %}
        <article class="wine-card" aria-label="{{ w.title }}">
          <div class="title">{{ w.title }}</div>
          <div class="meta">{{ w.variety or 'Unknown variety' }} · {{ w.country or 'Unknown country' }} · ${{ (w.price or '?')|e }} · {{ (w.points or '') }} pts · Sweetness: {{ w.sweetness_cat }}</div>
          <div class="tags">Style: {{ w.style_tags or '—' }}</div>
          <div class="desc">{{ w.description }}</div>
        </article>
      {% endfor %}
    {% else %}
      <div style="padding:30px;background:var(--card);border-radius:14px;text-align:center">No results. Try broadening filters.</div>
    {% endif %}
  </div>

  <nav class="pagination" aria-label="Pagination">
    {% if page > 1 %}
      <button class="page-btn" type="button" onclick="submitWithPage({{page-1}})">Prev</button>
    {% endif %}
    {% for p in range(1, total_pages+1) %}
      {% if p <= 2 or p > total_pages-2 or (p>=page-2 and p<=page+2) %}
        <button class="page-btn {% if p==page %}active{% endif %}" type="button" onclick="submitWithPage({{p}})">{{ p }}</button>
      {% elif p==3 and page>6 %}
        <span style="padding:7px 10px;color:var(--muted)">…</span>
      {% elif p==total_pages-2 and page<total_pages-5 %}
        <span style="padding:7px 10px;color:var(--muted)">…</span>
      {% endif %}
    {% endfor %}
    {% if page < total_pages %}
      <button class="page-btn" type="button" onclick="submitWithPage({{page+1}})">Next</button>
    {% endif %}
  </nav>
  <button class="btn" id="themeToggle" style="position:fixed;bottom:18px;right:18px;z-index:22">Toggle Dark Mode</button>
  <script>
    // Theme toggle
    function setTheme(theme){
      if(theme==="dark") document.documentElement.setAttribute("data-theme","dark");
      else document.documentElement.removeAttribute("data-theme");
      localStorage.setItem("theme", theme);
    }
    document.getElementById("themeToggle").onclick = function(){
      const cur = localStorage.getItem("theme") === "dark" ? "dark" : "light";
      setTheme(cur === "dark" ? "light" : "dark");
    };
    (function(){
      const saved = localStorage.getItem("theme") || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      setTheme(saved);
    })();

    // Helper for pagination
    function submitWithPage(p){
      const form = document.getElementById("searchForm");
      let inp = form.querySelector('input[name="page"]');
      if(!inp){ inp = document.createElement('input'); inp.type='hidden'; inp.name='page'; form.appendChild(inp);}
      inp.value = p;
      form.submit();
    }
  </script>
</body>
</html>


    """

    # wrap description safely with line-breaks
    prepared = []
    for w in results:
        desc = w.get("description") or ""
        desc_wrapped = "<br>".join(textwrap.wrap(desc, 120))
        w2 = dict(w)
        w2["description_wrapped"] = desc_wrapped
        prepared.append(w2)

    return render_template_string(template,
                                  country=country, variety=variety, max_price=max_price,
                                  sweetness=sweetness, style=style, sort=sort,
                                  results=prepared, total=total, page=page,
                                  total_pages=total_pages, WINES_CACHE_rows=WINES_CACHE["rows"],
                                  WINES_CACHE=WINES_CACHE)

# a simple admin endpoint to force re-download (optional)
@app.route("/admin/refresh_csv")
def refresh_csv():
    # !!! for local/dev use only. If you deploy, protect this endpoint.
    # Delete file and re-download & reload cache
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    WINES_CACHE.update({"loading": False, "loaded": False, "wines": [], "rows": 0, "last_error": None})
    ensure_wines_loaded()
    return redirect(url_for('index'))

if __name__ == "__main__":
    # On start, just ensure we attempt to load (this will download if missing)
    print("Starting app — if CSV missing, it will download now (this may take some seconds)...")
    ensure_wines_loaded()
    app.run(debug=True, host="0.0.0.0", port=5000)
