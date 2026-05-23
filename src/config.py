"""Project-wide configuration: paths and constants."""
from pathlib import Path

# Base directory of the project (one level up from src/)
BASE_DIR = Path(__file__).resolve().parent.parent

# Data files
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "reviews.db"
RAW_SCRAPED_JSON = DATA_DIR / "raw_scraped.json"
RAW_MANUAL_CSV = DATA_DIR / "raw_manual.csv"
MANUAL_LABELS_CSV = DATA_DIR / "manual_labels.csv"

# Source product
PRODUCT_URL = "https://www.amazon.in/Apple-New-iPhone-12-128GB/dp/B08L5TNJHG/"
PRODUCT_NAME = "Apple iPhone 12"
DEFAULT_STORAGE = "128GB"
DEFAULT_COLOR = "Blue"

# Sentiment model identifier on Hugging Face
HF_SENTIMENT_MODEL = "distilbert-base-uncased-finetuned-sst-2-english"