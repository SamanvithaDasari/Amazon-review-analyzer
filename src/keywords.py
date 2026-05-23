"""
Keyword extraction for review corpus.

Two functions:
  - top_keywords_overall(): top discriminative terms across all reviews
  - top_keywords_by_class(): top terms in positive vs negative reviews
    (useful when the data has rating diversity)

Approach: TF-IDF on lemmatized tokens with bigrams. Generic product
terms (iphone, phone, apple) are filtered out so the surfaced keywords
are actually informative.
"""
from typing import List, Tuple

import spacy
from sklearn.feature_extraction.text import TfidfVectorizer

_nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])

# Generic product/marketplace words to filter out — these appear in
# every review and add no information
PRODUCT_STOPWORDS = {
    "iphone", "phone", "apple", "ios", "12", "product", "amazon",
    "device", "mobile", "buy", "bought", "purchase", "order", "received",
    "got", "one", "thing", "really", "would", "could", "also", "even",
    "lot", "well", "good", "great",  # too common in positive reviews to be informative
}


def _preprocess(texts: List[str]) -> List[str]:
    """
    Lemmatize, lowercase, remove stopwords / punct / short tokens.
    Returns a list of cleaned, space-joined token strings — one per
    input doc, ready for TfidfVectorizer.
    """
    out = []
    for doc in _nlp.pipe(texts, batch_size=64):
        tokens = [
            t.lemma_.lower() for t in doc
            if not t.is_stop
            and not t.is_punct
            and not t.is_space
            and t.lemma_.lower() not in PRODUCT_STOPWORDS
            and len(t.lemma_) > 2
            and t.lemma_.isalpha()
        ]
        out.append(" ".join(tokens))
    return out


def top_keywords_overall(texts: List[str], top_k: int = 15) -> List[Tuple[str, float]]:
    """
    Top keywords/phrases across the entire corpus by mean TF-IDF score.

    Works on any number of documents. Returns list of (term, score) tuples.
    Useful when the corpus doesn't have enough class diversity for
    positive-vs-negative comparison.
    """
    docs = _preprocess(texts)
    docs = [d for d in docs if d.strip()]
    if not docs:
        return []

    # min_df=1 because we may have very few docs (e.g., 8 reviews)
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.95)
    matrix = vec.fit_transform(docs)
    feature_names = vec.get_feature_names_out()

    # Average TF-IDF across all docs — surfaces terms that are
    # collectively important across the corpus
    mean_scores = matrix.mean(axis=0).A1  # type: ignore
    top_idx = mean_scores.argsort()[::-1][:top_k]
    return [(feature_names[i], float(mean_scores[i])) for i in top_idx]


def top_keywords_by_class(
    texts_pos: List[str],
    texts_neg: List[str],
    top_k: int = 15,
) -> dict:
    """
    Top discriminative terms between positive and negative review sets.
    Returns {"positive": [(term, score)], "negative": [(term, score)]}.

    Requires non-trivial size in both classes. If one class is empty,
    returns empty lists for that class.
    """
    docs_pos = [d for d in _preprocess(texts_pos) if d.strip()]
    docs_neg = [d for d in _preprocess(texts_neg) if d.strip()]

    if not docs_pos or not docs_neg:
        return {"positive": [], "negative": []}

    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_df=0.9)
    all_docs = [" ".join(docs_pos), " ".join(docs_neg)]
    matrix = vec.fit_transform(all_docs)
    feature_names = vec.get_feature_names_out()

    pos_scores = matrix[0].toarray()[0]  # type: ignore
    neg_scores = matrix[1].toarray()[0]  # type: ignore

    # Discriminative: high in pos minus neg, vice versa
    diff_pos = pos_scores - neg_scores
    diff_neg = neg_scores - pos_scores

    top_pos_idx = diff_pos.argsort()[::-1][:top_k]
    top_neg_idx = diff_neg.argsort()[::-1][:top_k]

    return {
        "positive": [
            (feature_names[i], float(diff_pos[i]))
            for i in top_pos_idx if diff_pos[i] > 0
        ],
        "negative": [
            (feature_names[i], float(diff_neg[i]))
            for i in top_neg_idx if diff_neg[i] > 0
        ],
    }