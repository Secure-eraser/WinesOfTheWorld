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
<html>
<head>
  <meta charset="utf-8">
  <title>Wines of the World — Explorer</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
  :root{
    --bg: #f7f4ef;
    --card: #ffffff;
    --muted: #6d6d6d;
    --accent: #5a0b0b;
    --glass: rgba(255,255,255,0.6);
  }
  [data-theme="dark"]{
    --bg: #0f1113;
    --card: #0e1113;
    --muted: #9fa3a6;
    --accent: #f3c6c6;
    --glass: rgba(255,255,255,0.03);
  }
  *{box-sizing:border-box}
  body{
    margin:24px;
    font-family:Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial;
    background: radial-gradient(1200px 400px at -10% 10%, rgba(90,11,11,0.03), transparent),
                var(--bg);
    color: #e6e6e6;
    transition: background 0.25s ease;
  }
  header{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:14px}
  h1{color:var(--accent);margin:0;font-size:2rem;letter-spacing:-0.6px}
  .sub{color:var(--muted);font-size:0.95rem;margin-top:4px}
  .controls{display:flex;gap:12px;align-items:center}
  .btn{
    background: linear-gradient(180deg,var(--accent), #6b1111);
    border:none;color:white;padding:10px 12px;border-radius:10px;cursor:pointer;font-weight:600;
    box-shadow:0 6px 18px rgba(90,11,11,0.14);transition:transform .14s ease, opacity .14s;
  }
  .btn:active{transform:translateY(1px)}

  form.search-form{
    background:var(--card);
    border-radius:12px;padding:18px;border:1px solid rgba(0,0,0,0.06);
    display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;align-items:end;
    box-shadow:0 10px 30px rgba(2,6,23,0.06);
    color: #111;
    transition: transform .2s ease, box-shadow .2s ease;
  }
  form.search-form:hover{transform:translateY(-3px);box-shadow:0 18px 40px rgba(2,6,23,0.08)}

  label{display:flex;flex-direction:column;gap:6px;font-weight:600;font-size:0.9rem;color:#333}
  input[type="text"], input[type="number"], select{
    padding:10px;border-radius:8px;border:1px solid #e8e2dd;background:transparent;font-size:0.95rem;
  }

  .results-meta{margin-top:18px;margin-bottom:10px;color:var(--muted);display:flex;justify-content:space-between;align-items:center}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-top:10px}

  .wine-card{
    background:var(--card);border-radius:14px;padding:16px;border:1px solid rgba(0,0,0,0.04);
    box-shadow: 0 8px 22px rgba(2,6,23,0.06);
    transform-origin:center;transition:transform .16s ease, box-shadow .16s ease;
    overflow:hidden;
  }
  .wine-card:hover{transform:translateY(-6px);box-shadow:0 20px 44px rgba(2,6,23,0.12)}
  .title{font-weight:700;color:#222;margin-bottom:6px}
  .meta{color:var(--muted);font-size:0.9rem;margin-bottom:8px}
  .tags{font-size:0.85rem;color:#7b4a4a;margin-bottom:8px}
  .desc{color:#333;font-size:0.92rem;line-height:1.35;max-height:5.2em;overflow:hidden}

  /* pagination */
  .pagination{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:20px}
  .page-btn{padding:8px 12px;border-radius:8px;border:1px solid rgba(0,0,0,0.06);background:var(--card);cursor:pointer}
  .page-btn.active{background:var(--accent);color:white;border:none;box-shadow:0 6px 16px rgba(90,11,11,0.12)}

  /* subtle card shimmer when loading */
  .shimmer{animation:shimmer 2s infinite linear;background:linear-gradient(90deg,#f3f3f3 25%, #ececec 37%, #f3f3f3 63%);background-size:1000px 100%;}
  @keyframes shimmer{0%{background-position:-1000px 0}100%{background-position:1000px 0}}

  /* dark theme colors override for text readability */
  [data-theme="dark"] body, [data-theme="dark"] .title{color:#f3f3f3}
  [data-theme="dark"] label{color:#ccc}
  [data-theme="dark"] .desc{color:#ddd}
  [data-theme="dark"] .meta{color:#b8b8b8}
  [data-theme="dark"] .search-form{color:#ddd}

  /* small screens */
  @media (max-width:640px){
    h1{font-size:1.4rem}
    .btn{padding:8px 10px}
    body{margin:12px}
  }
  </style>

</head>
<body>
  <header>
    <div>
      <h1>Wines of the World</h1>
      <div class="sub">Search by country, price, grape, sweetness, or style. Dark mode and animations included.</div>
    </div>
    <div class="controls">
      <button class="btn" id="themeToggle">Toggle Dark</button>
      <form method="POST" style="display:inline;">
        <input type="hidden" name="clear" value="1">
        <button class="btn" style="background:#333">Reset</button>
      </form>
    </div>
  </header>

  <form method="POST" class="search-form" id="searchForm" onsubmit="">
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

    <div style="display:flex;gap:8px;align-items:center">
      <button class="btn" type="submit">Search</button>
      <div style="font-size:0.9rem;color:var(--muted)">Showing <strong>{{ total }}</strong> results</div>
    </div>
  </form>

  <div class="results-meta">
    <div style="color:var(--muted)">{{ WINES_CACHE_rows }} loaded into memory · page {{ page }} / {{ total_pages }}</div>
    <div style="color:var(--muted)">Tip: try "Riesling" + sweetness=Sweet</div>
  </div>

  <main>
    <div class="grid">
      {% if results %}
        {% for w in results %}
          <article class="wine-card" role="article" aria-label="{{ w.title }}">
            <div class="title">{{ w.title }}</div>
            <div class="meta">{{ w.variety or 'Unknown variety' }} · {{ w.country or 'Unknown country' }} · {{ (w.price or '?')|e }} · {{ (w.points or '') }} pts · Sweetness: {{ w.sweetness_cat }}</div>
            <div class="tags">Style: {{ w.style_tags or '—' }}</div>
            <div class="desc">{{ w.description_wrapped|safe }}</div>
          </article>
        {% endfor %}
      {% else %}
        <div style="padding:30px;background:var(--card);border-radius:12px">No results. Try broadening filters.</div>
      {% endif %}
    </div>

    <div class="pagination" role="navigation" aria-label="Pagination">
      {% if page > 1 %}
        <a class="page-btn" href="?page={{ page-1 }}" onclick="submitWithPage({{page-1}})">Prev</a>
      {% endif %}
      {% for p in range(1, total_pages+1) %}
        {% if p <= 3 or p > total_pages-3 or (p>=page-2 and p<=page+2) %}
          <button class="page-btn {% if p==page %}active{% endif %}" onclick="submitWithPage({{p}})">{{ p }}</button>
        {% elif p==4 and page>6 %}
          <span style="padding:8px 10px;color:var(--muted)">…</span>
        {% elif p==total_pages-3 and page<total_pages-5 %}
          <span style="padding:8px 10px;color:var(--muted)">…</span>
        {% endif %}
      {% endfor %}
      {% if page < total_pages %}
        <a class="page-btn" href="?page={{ page+1 }}" onclick="submitWithPage({{page+1}})">Next</a>
      {% endif %}
    </div>
  </main>

<script>
  // theme toggle
  function setTheme(theme){
    if(theme==="dark") document.documentElement.setAttribute("data-theme","dark");
    else document.documentElement.removeAttribute("data-theme");
    localStorage.setItem("theme", theme);
  }
  document.getElementById("themeToggle").addEventListener("click", function(e){
    const cur = localStorage.getItem("theme") === "dark" ? "dark" : "light";
    setTheme(cur === "dark" ? "light" : "dark");
  });
  (function(){
    const saved = localStorage.getItem("theme") || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setTheme(saved);
  })();

  // helper to submit current filters but change page param
  function submitWithPage(p){
    const form = document.getElementById("searchForm");
    // add or update hidden page input
    let inp = form.querySelector('input[name="page"]');
    if(!inp){ inp = document.createElement('input'); inp.type='hidden'; inp.name='page'; form.appendChild(inp); }
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
