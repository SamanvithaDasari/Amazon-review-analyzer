"""
Flask frontend for the Amazon Review Analyzer.

Pages:
  /                 — dashboard
  /test-sentiment   — interactive sentiment tester
  /browse-reviews   — filterable review listing
  /api-docs         — human-friendly API reference

Plus proxy routes to FastAPI: /api/*, /docs, /openapi.json
"""
import os
from urllib.parse import urlencode

import requests
from flask import Flask, render_template, request, Response, redirect

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")

app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static",
)


# ---------------------------------------------------------------------------
# Helpers exposed to Jinja
# ---------------------------------------------------------------------------
@app.template_global()
def filter_url(**overrides):
    """Build a /browse-reviews URL from current filters with overrides applied.

    Pass a kwarg of None to remove that filter.
    Pass a kwarg with a list value to emit multiple URL params.
    """
    # Use getlist semantics — start from the current MultiDict
    pairs = []
    used_keys = set(overrides.keys())
    for k, v in request.args.items(multi=True):
        if k in used_keys:
            continue
        pairs.append((k, v))
    for key, value in overrides.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            for v in value:
                pairs.append((key, v))
        else:
            pairs.append((key, value))
    if not pairs:
        return "/browse-reviews"
    return "/browse-reviews?" + urlencode(pairs)
# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Dashboard."""
    try:
        stats = requests.get(f"{API_BASE}/api/stats", timeout=30).json()
        error = None
    except Exception as e:
        stats = None
        error = f"Could not reach API: {e}"
    return render_template("index.html", stats=stats, error=error)


@app.route("/test-sentiment", methods=["GET", "POST"])
def test_sentiment():
    result = None
    text = ""
    model = "vader"
    error = None

    if request.method == "POST":
        text = request.form.get("review_text", "")
        model = request.form.get("model", "vader")
        if text.strip():
            try:
                r = requests.post(
                    f"{API_BASE}/api/sentiment",
                    json={"review_text": text, "model": model},
                    timeout=60,
                )
                if r.status_code == 200:
                    result = r.json()
                else:
                    error = f"API error {r.status_code}: {r.text[:200]}"
            except Exception as e:
                error = f"Could not reach API: {e}"

    return render_template(
        "sentiment.html",
        result=result, text=text, model=model, error=error,
    )


@app.route("/browse-reviews")
def browse_reviews():
    """Filterable browser. Passes most filters through to the API; sentiment/
    verified/q filters are applied client-side here since the API may not
    accept them yet."""
    rating = request.args.get("rating") or None
    sentiment = request.args.get("sentiment") or None
    verified = request.args.get("verified") or None
    q_list = [s.strip().lower() for s in request.args.getlist("q") if s.strip()]
    color = request.args.get("color") or None
    storage = request.args.get("storage") or None

    # Build params for the upstream API. We pull a generous batch so
    # client-side filters still produce a meaningful result set.
    api_params = {}
    if rating: api_params["rating"] = rating
    if color: api_params["color"] = color
    if storage: api_params["storage"] = storage
    api_params["limit"] = 100

    reviews_all = []
    total_upstream = 0
    error = None
    try:
        # Fetch up to 3 pages (300 reviews) so client-side filters have material
        for offset in (0, 100, 200):
            api_params["offset"] = offset
            r = requests.get(f"{API_BASE}/api/reviews", params=api_params, timeout=30)
            page = r.json()
            total_upstream = page.get("total", 0)
            chunk = page.get("reviews", [])
            reviews_all.extend(chunk)
            if len(chunk) < 100:
                break
    except Exception as e:
        error = f"Could not reach API: {e}"

    data = {"total": total_upstream, "reviews": reviews_all}

    # Client-side filtering for sentiment / verified / q (keyword)
    reviews = data.get("reviews", [])
    if sentiment:
        reviews = [x for x in reviews if x.get("sentiment_label") == sentiment]
    if verified == "true":
        reviews = [x for x in reviews if x.get("verified_purchase")]
    elif verified == "false":
        reviews = [x for x in reviews if not x.get("verified_purchase")]
    for keyword in q_list:
        reviews = [
            x for x in reviews
            if keyword in (x.get("review_text") or "").lower()
            or keyword in (x.get("review_title") or "").lower()
        ]

    # Cap rendered output to 50 for performance; "total" reflects post-filter
    filtered_data = {
        "total": len(reviews),
        "reviews": reviews[:50],
    }

    # Pull top keywords for the search suggestions
    popular_keywords = []
    try:
        stats_resp = requests.get(f"{API_BASE}/api/stats", timeout=10).json()
        # Take top 8 keywords by score
        popular_keywords = [kw["term"] for kw in stats_resp.get("top_keywords", [])[:8]]
    except Exception:
        pass  # Suggestions are optional — page still works without them

    return render_template(
        "browse.html",
        data=filtered_data,
        filters=request.args,
        error=error,
        popular_keywords=popular_keywords,
    )


@app.route("/api-docs")
def api_docs():
    """Human-friendly API documentation page."""
    return render_template("api_docs.html")


# ---------------------------------------------------------------------------
# API proxy routes — expose FastAPI through the public Flask port
# ---------------------------------------------------------------------------
@app.route("/api/<path:subpath>", methods=["GET", "POST"])
def api_proxy(subpath):
    url = f"{API_BASE}/api/{subpath}"
    try:
        if request.method == "GET":
            resp = requests.get(url, params=request.args, timeout=60)
        else:
            resp = requests.post(
                url, json=request.get_json(silent=True), timeout=60
            )
        return Response(
            resp.content,
            status=resp.status_code,
            content_type=resp.headers.get("content-type", "application/json"),
        )
    except Exception as e:
        return Response(
            f'{{"error": "API unreachable: {e}"}}',
            status=503,
            content_type="application/json",
        )


@app.route("/docs")
def docs_proxy():
    """Proxy Swagger UI from FastAPI. Rewrites the openapi.json reference
    so Swagger fetches the spec through our proxy route."""
    try:
        resp = requests.get(f"{API_BASE}/docs", timeout=30)
        html = resp.text.replace("/openapi.json", "/openapi.json")
        return Response(html, status=resp.status_code, content_type="text/html")
    except Exception as e:
        return Response(
            f"<h1>Swagger unavailable</h1><p>API unreachable: {e}</p>",
            status=503,
            content_type="text/html",
        )


@app.route("/openapi.json")
def openapi_spec():
    """Proxy the OpenAPI spec itself."""
    try:
        resp = requests.get(f"{API_BASE}/openapi.json", timeout=30)
        return Response(
            resp.content,
            status=resp.status_code,
            content_type="application/json",
        )
    except Exception as e:
        return Response(
            f'{{"error": "spec unreachable: {e}"}}',
            status=503,
            content_type="application/json",
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
