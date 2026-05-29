"""Train the JARVIS heuristic intent classifier.

Reads `data/intent_classifier/intent_training.jsonl` and produces:

  * `model.onnx`      — TfidfVectorizer + LogisticRegression pipeline.
  * `labels.json`     — {intent: idx} mapping, sorted by index.
  * `patterns.json`   — Aho-Corasick patterns extracted from the corpus.

Run:
    python scripts/train_intent_classifier.py

Optional flags:
    --data PATH       override training jsonl
    --out  DIR        override output directory
    --no-onnx         skip ONNX export (useful for fast iteration)
    --no-patterns     skip pattern extraction
    --top-k INT       max patterns per intent (default 30)
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

DEFAULT_DATA = Path(r"C:\Users\aggel\Jarvis-src\data\intent_classifier\intent_training.jsonl")
DEFAULT_OUT = Path(r"C:\Users\aggel\Jarvis-src\data\intent_classifier")

# Greek + English stop-ish words we do NOT want to mistake for triggers.
# Short discourse particles that appear across many intents.
STOPWORDS_FOR_PATTERNS = {
    # english
    "the", "a", "an", "to", "of", "in", "on", "for", "and", "or", "is",
    "it", "this", "that", "my", "me", "you", "do", "i", "be", "are", "at",
    "with", "as", "by", "what", "please", "hey", "okay", "alright",
    # greek
    "ο", "η", "το", "οι", "τα", "ένα", "μια", "και", "ή", "για", "σε",
    "στη", "στην", "στο", "στα", "από", "με", "που", "πως", "πώς",
    "μου", "σου", "σε", "με", "εγώ", "εσύ", "ναι", "όχι", "λίγο",
    "λίγη", "λίγο", "παρακαλώ", "γεια",
}


def _normalise(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.lower().split())


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  WARN: skipping bad line: {e}", file=sys.stderr)
                continue
            t = rec.get("text", "").strip()
            lab = rec.get("intent", "").strip()
            if t and lab:
                texts.append(_normalise(t))
                labels.append(lab)
    return texts, labels


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def build_pipeline() -> Pipeline:
    """TF-IDF (char + word n-grams via two separate vectorizers would be
    even better, but we keep it to a single word-level vectorizer to make
    ONNX export trivial). For Greek + English the (1,3) word n-grams work
    well in practice."""
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 3),
            max_features=5000,
            sublinear_tf=True,
            # strip_accents=None: KEEP Greek diacritics, they're semantic.
            strip_accents=None,
            lowercase=True,
            # IMPORTANT: \S+ is whitespace-splitting. We must NOT use the
            # default \w pattern because onnxruntime's RE2-based Tokenizer
            # op doesn't fully match Python's Unicode \w → Greek tokens get
            # dropped silently and the ONNX model returns the class prior
            # instead of the real distribution. The training pre-norm has
            # already collapsed whitespace and lowercased, so plain
            # whitespace splitting yields the same vocab as Python's
            # tokenizer for our data.
            token_pattern=r"\S+",
        )),
        ("clf", LogisticRegression(
            C=2.0,
            class_weight="balanced",
            max_iter=1000,
            solver="lbfgs",   # lbfgs handles multinomial multiclass natively
        )),
    ])


def train_and_evaluate(
    texts: list[str], labels: list[str]
) -> tuple[Pipeline, list[str], dict]:
    label_set = sorted(set(labels))
    label_to_idx = {lab: i for i, lab in enumerate(label_set)}

    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels,
        test_size=0.2, random_state=42, stratify=labels,
    )

    pipe = build_pipeline()
    pipe.fit(X_train, y_train)

    y_pred = pipe.predict(X_test)
    report = classification_report(
        y_test, y_pred, digits=3, zero_division=0,
        output_dict=False,
    )
    report_dict = classification_report(
        y_test, y_pred, digits=3, zero_division=0,
        output_dict=True,
    )
    print("\n=== Validation report ===\n")
    print(report)
    return pipe, label_set, report_dict


# ---------------------------------------------------------------------------
# ONNX export
# ---------------------------------------------------------------------------

def export_onnx(pipe: Pipeline, out_path: Path) -> int:
    """Convert the sklearn pipeline to ONNX. Returns bytes written."""
    try:
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import StringTensorType
    except ImportError as e:
        raise SystemExit(
            f"skl2onnx is required for ONNX export: {e}\n"
            "  pip install skl2onnx"
        )

    initial_type = [("input", StringTensorType([None]))]
    # opset 13+ is needed for TfidfVectorizer support.
    onnx_model = convert_sklearn(
        pipe,
        initial_types=initial_type,
        target_opset=15,
        options={id(pipe.named_steps["clf"]): {"zipmap": True}},
    )
    out_path.write_bytes(onnx_model.SerializeToString())
    return out_path.stat().st_size


# ---------------------------------------------------------------------------
# Pattern extraction (Aho-Corasick)
# ---------------------------------------------------------------------------

def extract_patterns(
    texts: list[str], labels: list[str], top_k: int = 30,
) -> dict:
    """Extract per-intent high-frequency word n-grams (1..3) that are
    discriminative (appear in this intent's examples and rarely in others).

    Each pattern entry: {phrase: {"intent": ..., "score": ...}}.
    Scores reflect a simple precision proxy:
        score = clip(0.85 + 0.10 * (precision - 0.5), 0.85, 0.98)
    Higher precision → higher confidence emitted by the AC tier.
    """
    # Per-intent and global n-gram counts (1..3).
    per_intent: dict[str, Counter] = defaultdict(Counter)
    global_count: Counter = Counter()

    for text, lab in zip(texts, labels):
        tokens = [t for t in text.split() if t]
        ngrams: set[str] = set()
        for n in (1, 2, 3):
            for i in range(len(tokens) - n + 1):
                gram = " ".join(tokens[i:i + n])
                if n == 1 and gram in STOPWORDS_FOR_PATTERNS:
                    continue
                if len(gram) < 3:  # ignore single/double chars
                    continue
                ngrams.add(gram)
        for g in ngrams:
            per_intent[lab][g] += 1
            global_count[g] += 1

    patterns: dict[str, dict] = {}
    for intent, counts in per_intent.items():
        # discriminative score: precision = intent_count / global_count
        scored: list[tuple[str, float, int]] = []
        for gram, c in counts.items():
            total = global_count[gram]
            if total < 2:  # too rare to be a stable trigger
                continue
            precision = c / total
            if precision < 0.7:  # appears too often in other intents
                continue
            # weight by recall too — n-gram must cover at least 10% of
            # this intent's examples to be a "trigger"
            n_intent = sum(1 for L in labels if L == intent)
            recall = c / max(1, n_intent)
            if recall < 0.1:
                continue
            scored.append((gram, precision * (0.5 + recall), c))
        # sort by composite then take top_k longest-first (longer wins ties)
        scored.sort(key=lambda x: (x[1], len(x[0].split())), reverse=True)
        chosen = scored[:top_k]
        for gram, composite, _c in chosen:
            patterns[gram] = {
                "intent": intent,
                "score": float(min(0.98, max(0.85, 0.85 + 0.10 * (composite - 0.5)))),
            }

    return {"patterns": patterns}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-onnx", action="store_true")
    parser.add_argument("--no-patterns", action="store_true")
    parser.add_argument("--top-k", type=int, default=30)
    args = parser.parse_args()

    if not args.data.exists():
        print(f"ERROR: training data not found: {args.data}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)

    texts, labels = load_jsonl(args.data)
    print(f"Loaded {len(texts)} examples from {args.data}")
    counts = Counter(labels)
    print("Label distribution:")
    for lab, n in counts.most_common():
        print(f"  {lab:<22s} {n:>4d}")

    pipe, label_set, _ = train_and_evaluate(texts, labels)

    # labels.json
    labels_path = args.out / "labels.json"
    labels_path.write_text(
        json.dumps({lab: i for i, lab in enumerate(label_set)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {labels_path}")

    # model.onnx
    if not args.no_onnx:
        model_path = args.out / "model.onnx"
        nbytes = export_onnx(pipe, model_path)
        print(f"Wrote {model_path}  ({nbytes / 1024:.1f} KB)")

    # patterns.json
    if not args.no_patterns:
        patterns_obj = extract_patterns(texts, labels, top_k=args.top_k)
        patterns_path = args.out / "patterns.json"
        patterns_path.write_text(
            json.dumps(patterns_obj, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        n = len(patterns_obj["patterns"])
        print(f"Wrote {patterns_path}  ({n} patterns)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
