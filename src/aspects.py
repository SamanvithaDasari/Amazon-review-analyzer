"""
Aspect-based sentiment analysis.

For each predefined aspect (battery, camera, display, etc.):
  1. Find sentences that mention any of the aspect's keywords
  2. Score each such sentence with VADER
  3. Aggregate: positive_count, negative_count, neutral_count, mentions

This gives a per-aspect sentiment breakdown — useful for understanding
*which features* people praise or complain about, beyond just an overall
sentiment score.
"""
from typing import Dict, List

import spacy

from .sentiment import vader_sentiment

_nlp = spacy.load("en_core_web_sm", disable=["ner"])


# Fixed aspect vocabulary. Each aspect maps to a list of keyword variants
# that, if present in a sentence, count as a mention of that aspect.
ASPECT_VOCAB: Dict[str, List[str]] = {
    "battery":     ["battery", "charge", "charging", "backup", "drain"],
    "camera":      ["camera", "photo", "picture", "image", "lens", "video"],
    "display":     ["display", "screen", "resolution", "brightness", "oled", "led"],
    "performance": ["fast", "slow", "lag", "performance", "speed", "smooth", "processor", "chip"],
    "build":       ["build", "design", "weight", "premium", "feel", "body", "haptic"],
    "price":       ["price", "expensive", "cheap", "worth", "money", "value", "overpriced", "cost"],
    "heat":        ["heat", "hot", "warm", "temperature"],
    "delivery":    ["delivery", "shipping", "packaging", "box"],
    "ecosystem":   ["ios", "ecosystem", "icloud", "airdrop", "iphone"],
}


def aspect_sentiments(texts: List[str]) -> Dict[str, dict]:
    """
    Run aspect-based sentiment analysis over a corpus.

    For each sentence in each review, check which aspects it mentions
    (a sentence can mention multiple), then score that sentence with
    VADER and tally the result per aspect.

    Returns a dict like:
      {
        "battery": {"mentions": 5, "positive": 4, "negative": 1, "neutral": 0},
        "camera":  {"mentions": 8, "positive": 8, "negative": 0, "neutral": 0},
        ...
      }
    """
    # Initialize empty result for every aspect (so the output is complete
    # even for aspects with zero mentions)
    results = {
        aspect: {"mentions": 0, "positive": 0, "negative": 0, "neutral": 0}
        for aspect in ASPECT_VOCAB
    }

    for doc in _nlp.pipe(texts, batch_size=64):
        for sent in doc.sents:
            sent_text_lower = sent.text.lower()

            # Check each aspect — a single sentence can mention multiple
            for aspect, keywords in ASPECT_VOCAB.items():
                if any(kw in sent_text_lower for kw in keywords):
                    sentiment = vader_sentiment(sent.text).sentiment
                    results[aspect]["mentions"] += 1
                    results[aspect][sentiment] += 1

    return results


def aspect_summary(results: Dict[str, dict]) -> List[Dict]:
    """
    Convert raw aspect_sentiments output into a sorted, summary-friendly
    list with positive/negative ratios. Useful for printing or charting.
    """
    out = []
    for aspect, counts in results.items():
        mentions = counts["mentions"]
        if mentions == 0:
            continue
        out.append({
            "aspect": aspect,
            "mentions": mentions,
            "positive": counts["positive"],
            "negative": counts["negative"],
            "neutral": counts["neutral"],
            "positive_ratio": counts["positive"] / mentions,
            "negative_ratio": counts["negative"] / mentions,
        })
    # Sort by mention count, most-discussed first
    out.sort(key=lambda x: x["mentions"], reverse=True)
    return out