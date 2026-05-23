"""SQLite database layer: schema, connection management, and CRUD helpers."""
import sqlite3
from contextlib import contextmanager
from typing import Optional, List, Dict, Tuple

from .config import DB_PATH

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    review_title        TEXT,
    review_text         TEXT    NOT NULL,
    rating              INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    storage_variant     TEXT,
    color               TEXT,
    verified_purchase   INTEGER NOT NULL DEFAULT 0,
    review_date         TEXT,
    source              TEXT    NOT NULL,
    variant_inferred    INTEGER NOT NULL DEFAULT 0,
    sentiment_label     TEXT,
    sentiment_score     REAL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_color_storage_rating
    ON reviews(color, storage_variant, rating);
CREATE INDEX IF NOT EXISTS idx_rating    ON reviews(rating);
CREATE INDEX IF NOT EXISTS idx_sentiment ON reviews(sentiment_label);
"""


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------
@contextmanager
def get_conn():
    """
    Context manager that yields a SQLite connection.

    - Sets row_factory to sqlite3.Row so we can access columns by name.
    - Commits on successful exit; closes always.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the database file (if missing) and apply the schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def insert_review(conn: sqlite3.Connection, review: dict) -> int:
    """
    Insert one review and return its new id.

    `review` is a dict; missing optional keys default to None / 0.
    """
    cur = conn.execute(
        """
        INSERT INTO reviews (
            review_title, review_text, rating,
            storage_variant, color, verified_purchase,
            review_date, source, variant_inferred,
            sentiment_label, sentiment_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review.get("review_title"),
            review["review_text"],
            review["rating"],
            review.get("storage_variant"),
            review.get("color"),
            int(review.get("verified_purchase", False)),
            review.get("review_date"),
            review["source"],
            int(review.get("variant_inferred", False)),
            review.get("sentiment_label"),
            review.get("sentiment_score"),
        ),
    )
    return cur.lastrowid


def query_reviews(
    conn: sqlite3.Connection,
    *,
    color: Optional[str] = None,
    storage: Optional[str] = None,
    rating: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[Dict], int]:
    """
    Return (rows, total_count) matching the given filters.

    Filters are case-insensitive on color/storage. None means "any".
    """
    where, params = [], []
    if color:
        where.append("LOWER(color) = LOWER(?)")
        params.append(color)
    if storage:
        where.append("LOWER(storage_variant) = LOWER(?)")
        params.append(storage)
    if rating is not None:
        where.append("rating = ?")
        params.append(rating)

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""

    # Page of results
    sql = f"SELECT * FROM reviews{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?"
    rows = conn.execute(sql, (*params, limit, offset)).fetchall()

    # Total count for pagination
    count_sql = f"SELECT COUNT(*) FROM reviews{where_clause}"
    total = conn.execute(count_sql, params).fetchone()[0]

    return [dict(r) for r in rows], total


def count_reviews(conn: sqlite3.Connection) -> int:
    """Total number of rows in the reviews table."""
    return conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]