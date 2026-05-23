"""
Flask frontend for the Amazon Review Analyzer.

Three pages:
  /                 — dashboard (calls /api/stats)
  /test-sentiment   — interactive sentiment tester
  /browse-reviews   — filterable review listing

Runs on port 5000 by default. Talks to the FastAPI service on port 8000
via HTTP (configurable via the API_BASE env var).
"""
import os

import requests
from flask import Flask, render_template, request

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")

app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static",
)


@app.route("/")
def index():
    """Dashboard. Pulls aggregated stats from the API."""
    try:
        stats = requests.get(f"{API_BASE}/api/stats", timeout=30).json()
        error = None
    except Exception as e:
        stats = None
        error = f"Could not reach API: {e}"
    return render_template("index.html", stats=stats, error=error)


@app.route("/test-sentiment", methods=["GET", "POST"])
def test_sentiment():
    """Interactive sentiment tester. Posts to the API."""
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
                    error = f"API error: {r.status_code} {r.text}"
            except Exception as e:
                error = f"Could not reach API: {e}"

    return render_template(
        "sentiment.html",
        result=result, text=text, model=model, error=error,
    )


@app.route("/browse-reviews")
def browse_reviews():
    """Filterable review browser. Calls /api/reviews with query params."""
    # Pass through whatever filters the user supplied
    params = {k: v for k, v in request.args.items() if v}
    params.setdefault("limit", "20")

    try:
        r = requests.get(f"{API_BASE}/api/reviews", params=params, timeout=30)
        data = r.json()
        error = None
    except Exception as e:
        data = {"total": 0, "reviews": []}
        error = f"Could not reach API: {e}"

    return render_template(
        "browse.html",
        data=data, filters=request.args, error=error,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)