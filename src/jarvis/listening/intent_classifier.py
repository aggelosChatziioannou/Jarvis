"""Tier 2.5 latency optimization — Heuristic Intent Classifier.

Two-tier cascade that routes the majority of voice-assistant queries in
<2ms, bypassing the 5-7s LLM intent judge:

  1. Aho-Corasick automaton over high-frequency trigger phrases (~0.5ms).
  2. ONNX TF-IDF + Logistic Regression classifier (~2ms).

Confidence routing (caller responsibility):
  - score >= 0.85 → 'high'  → fast path, skip LLM.
  - score >= 0.72 → 'med'   → heuristic accepted, callable still allowed
                                to verify with cheap LLM later.
  - score <  0.72 → 'low'   → fallback to `fused_intent` or `intent_judge`.

This module is standalone — DO NOT import from `listener.py` or
`intent_judge.py`. Integration is handled separately by the orchestrator.

The classifier is multilingual (Greek + English) by virtue of the
training data and character-aware TF-IDF (n-grams 1-3, strip_accents
disabled at train time so Greek glyphs are preserved).

Defensive imports: if `pyahocorasick` or `onnxruntime` are missing, the
classifier degrades gracefully — every `classify()` call returns
`tier='fallback'` with `confidence='low'`, signalling the caller to use
the LLM judge.
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defensive imports — runtime degrades to 'fallback' tier if deps missing.
# ---------------------------------------------------------------------------
try:
    import ahocorasick  # type: ignore
    AHOCORASICK_AVAILABLE = True
except ImportError:  # pragma: no cover
    ahocorasick = None  # type: ignore
    AHOCORASICK_AVAILABLE = False
    logger.warning(
        "pyahocorasick not available — HeuristicIntentClassifier will "
        "always return tier='fallback'. Install with: pip install pyahocorasick"
    )

try:
    import onnxruntime as ort  # type: ignore
    ONNXRUNTIME_AVAILABLE = True
except ImportError:  # pragma: no cover
    ort = None  # type: ignore
    ONNXRUNTIME_AVAILABLE = False
    logger.warning(
        "onnxruntime not available — HeuristicIntentClassifier will "
        "always return tier='fallback'. Install with: pip install onnxruntime"
    )

try:
    import numpy as np  # type: ignore
    NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore
    NUMPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Defaults — match the layout produced by scripts/train_intent_classifier.py.
# ---------------------------------------------------------------------------
_DEFAULT_DATA_DIR = Path(r"C:\Users\aggel\Jarvis-src\data\intent_classifier")
_DEFAULT_MODEL_PATH = _DEFAULT_DATA_DIR / "model.onnx"
_DEFAULT_PATTERNS_PATH = _DEFAULT_DATA_DIR / "patterns.json"
_DEFAULT_LABELS_PATH = _DEFAULT_DATA_DIR / "labels.json"

# Confidence thresholds — keep in sync with caller-side routing logic.
_THRESH_HIGH = 0.85
_THRESH_MED = 0.72


@dataclass
class ClassifierResult:
    """Result of a single classification call.

    Attributes:
        intent: predicted intent label (e.g. 'spotify_play'). 'unknown'
            on fallback.
        confidence: bucketed routing label — 'high' / 'med' / 'low'.
        score: raw probability/strength (0.0-1.0).
        tier: which stage produced the answer —
            'aho_corasick' / 'onnx' / 'fallback'.
        entities: extracted slot fills (currently best-effort; mostly
            empty until the slot extractor is built).
        latency_ms: wall-clock duration of `classify()` in milliseconds.
    """
    intent: str
    confidence: str
    score: float
    tier: str
    entities: dict = field(default_factory=dict)
    latency_ms: float = 0.0


def _normalise(text: str) -> str:
    """Lowercase + unicode NFC normalise. We KEEP Greek diacritics — they
    carry semantic load (e.g. 'τι' vs 'τί' are not stylistic variants in
    user transcripts). Whitespace is collapsed."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.lower().split())


class HeuristicIntentClassifier:
    """Two-tier intent classifier: Aho-Corasick + ONNX TF-IDF/LR.

    Thread-safety: an `onnxruntime.InferenceSession` is safe for concurrent
    `run()` calls. The Aho-Corasick automaton is read-only after build.
    Therefore this class is safe to call from multiple threads.

    Typical use::

        clf = HeuristicIntentClassifier()
        r = clf.classify("παίξε λίγο Drake")
        if r.confidence in ("high", "med"):
            # fast path — no LLM call
            handle_directly(r)
        else:
            fallback_to_llm_judge(...)
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        patterns_path: Optional[str] = None,
        labels_path: Optional[str] = None,
    ):
        """Load the ONNX model + Aho-Corasick patterns.

        Any failure leaves the classifier in a degraded state where
        `classify()` always returns `tier='fallback'`. We never raise from
        the constructor — callers should not have to wrap us in try/except
        just to load the assistant.
        """
        self._mp = Path(model_path) if model_path else _DEFAULT_MODEL_PATH
        self._pp = Path(patterns_path) if patterns_path else _DEFAULT_PATTERNS_PATH
        self._lp = Path(labels_path) if labels_path else _DEFAULT_LABELS_PATH

        self._automaton = None
        self._session: Optional[Any] = None
        self._input_name: Optional[str] = None
        self._labels: list[str] = []           # idx -> label
        self._label_to_idx: dict[str, int] = {}

        self._ready_ac = False
        self._ready_onnx = False

        self._load_automaton()
        self._load_onnx()

        debug_msg = (
            f"HeuristicIntentClassifier ready: "
            f"aho_corasick={self._ready_ac} onnx={self._ready_onnx} "
            f"labels={len(self._labels)} patterns={'?' if not self._ready_ac else 'loaded'}"
        )
        logger.info(debug_msg)

    # -- loaders -----------------------------------------------------------

    def _load_automaton(self) -> None:
        if not AHOCORASICK_AVAILABLE:
            return
        if not self._pp.exists():
            logger.warning("patterns.json not found at %s", self._pp)
            return
        try:
            with self._pp.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            # patterns.json schema:
            #   { "patterns": {"<phrase>": {"intent": "...", "score": 0.95}} }
            patterns = raw.get("patterns", raw)  # tolerate flat dict
            A = ahocorasick.Automaton()
            count = 0
            for phrase, meta in patterns.items():
                phrase_norm = _normalise(phrase)
                if not phrase_norm:
                    continue
                if isinstance(meta, dict):
                    intent = meta.get("intent", "unknown")
                    score = float(meta.get("score", 0.92))
                else:
                    # tolerate "{phrase: intent}" flat form too
                    intent = str(meta)
                    score = 0.92
                # Aho-Corasick uses the value attached to the matched word.
                A.add_word(phrase_norm, (intent, score, phrase_norm))
                count += 1
            if count == 0:
                logger.warning("patterns.json had zero usable patterns")
                return
            A.make_automaton()
            self._automaton = A
            self._ready_ac = True
            logger.debug("Aho-Corasick automaton loaded with %d patterns", count)
        except Exception as e:
            logger.warning("Failed to load Aho-Corasick patterns: %s", e)

    def _load_onnx(self) -> None:
        if not ONNXRUNTIME_AVAILABLE or not NUMPY_AVAILABLE:
            return
        if not self._mp.exists() or not self._lp.exists():
            logger.warning(
                "ONNX model or labels file missing — model=%s labels=%s",
                self._mp, self._lp,
            )
            return
        try:
            with self._lp.open("r", encoding="utf-8") as f:
                label_map = json.load(f)
            # labels.json schema: {"intent_name": 0, ...}
            self._label_to_idx = {str(k): int(v) for k, v in label_map.items()}
            ordered = sorted(self._label_to_idx.items(), key=lambda kv: kv[1])
            self._labels = [name for name, _ in ordered]

            # CPU is plenty fast for a tiny TF-IDF+LR model. Disable
            # threading to keep tail-latency tight and avoid stealing CPU
            # from the audio thread.
            so = ort.SessionOptions()
            so.intra_op_num_threads = 1
            so.inter_op_num_threads = 1
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(
                str(self._mp),
                sess_options=so,
                providers=["CPUExecutionProvider"],
            )
            self._input_name = self._session.get_inputs()[0].name
            self._ready_onnx = True
            logger.debug(
                "ONNX model loaded (%s, %d labels, input='%s')",
                self._mp.name, len(self._labels), self._input_name,
            )
        except Exception as e:
            logger.warning("Failed to load ONNX model: %s", e)
            self._session = None
            self._ready_onnx = False

    # -- inference ---------------------------------------------------------

    def classify(self, utterance: str) -> ClassifierResult:
        """Classify a single utterance. Always returns a ClassifierResult."""
        t0 = time.perf_counter()

        # Guard: empty input → fallback.
        text = _normalise(utterance)
        if not text:
            return ClassifierResult(
                intent="unknown", confidence="low", score=0.0,
                tier="fallback", entities={},
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # Guard: nothing loaded → fallback. (Defensive — covers missing
        # deps AND failed file loads.)
        if not self._ready_ac and not self._ready_onnx:
            return ClassifierResult(
                intent="unknown", confidence="low", score=0.0,
                tier="fallback", entities={},
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # ---- Tier 1: Aho-Corasick ---------------------------------------
        if self._ready_ac:
            ac = self._classify_ac(text)
            if ac is not None:
                intent, score, matched = ac
                conf = self._bucket(score)
                # Aho-Corasick matches are strong — only escalate if the
                # match was on a very generic phrase and the bucket fell
                # to 'low'. In practice, the threshold check covers it.
                if conf != "low":
                    return ClassifierResult(
                        intent=intent, confidence=conf, score=score,
                        tier="aho_corasick",
                        entities={"matched_phrase": matched},
                        latency_ms=(time.perf_counter() - t0) * 1000.0,
                    )

        # ---- Tier 2: ONNX TF-IDF + LR -----------------------------------
        if self._ready_onnx:
            onnx_result = self._classify_onnx(text)
            if onnx_result is not None:
                intent, score = onnx_result
                conf = self._bucket(score)
                return ClassifierResult(
                    intent=intent, confidence=conf, score=score,
                    tier="onnx", entities={},
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                )

        # ---- Fallback ----------------------------------------------------
        return ClassifierResult(
            intent="unknown", confidence="low", score=0.0,
            tier="fallback", entities={},
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    # -- internals ---------------------------------------------------------

    def _classify_ac(self, text: str) -> Optional[tuple[str, float, str]]:
        """Return (intent, score, matched_phrase) for the best AC hit, or
        None if nothing matched."""
        best: Optional[tuple[str, float, str]] = None
        # We want the LONGEST match — longer phrases are more specific
        # (e.g. 'play next song' > 'play'). Score ties broken by score.
        for _end, (intent, score, phrase) in self._automaton.iter(text):
            if best is None:
                best = (intent, score, phrase)
                continue
            _bi, _bs, bp = best
            if len(phrase) > len(bp) or (len(phrase) == len(bp) and score > _bs):
                best = (intent, score, phrase)
        return best

    def _classify_onnx(self, text: str) -> Optional[tuple[str, float]]:
        """Run the ONNX classifier; return (intent, prob)."""
        try:
            x = np.array([text], dtype=object)
            outputs = self._session.run(None, {self._input_name: x})
            # skl2onnx convention for a sklearn Pipeline ending in
            # LogisticRegression: outputs[0] = predicted label,
            # outputs[1] = list of dicts {label: prob}.
            probs = outputs[1][0] if len(outputs) >= 2 else None

            if isinstance(probs, dict):
                # pick argmax
                intent, score = max(probs.items(), key=lambda kv: kv[1])
                return str(intent), float(score)

            # Fallback shape: outputs[1] could be a numpy array of probs.
            if probs is None:
                pred = outputs[0]
                # No probabilities — give it neutral medium score.
                label = str(pred[0]) if hasattr(pred, "__getitem__") else str(pred)
                return label, 0.75

            arr = np.asarray(probs)
            idx = int(arr.argmax())
            score = float(arr[idx])
            intent = self._labels[idx] if 0 <= idx < len(self._labels) else "unknown"
            return intent, score
        except Exception as e:
            logger.warning("ONNX inference failed: %s", e)
            return None

    @staticmethod
    def _bucket(score: float) -> str:
        if score >= _THRESH_HIGH:
            return "high"
        if score >= _THRESH_MED:
            return "med"
        return "low"


# Convenience singleton — opt-in. Most callers should build their own
# instance and own the lifetime; we expose this for quick scripts/tests.
_singleton: Optional[HeuristicIntentClassifier] = None


def get_default_classifier() -> HeuristicIntentClassifier:
    """Return a process-wide singleton. Thread-safe for read; first call
    in a process should be from a single thread."""
    global _singleton
    if _singleton is None:
        _singleton = HeuristicIntentClassifier()
    return _singleton


__all__ = [
    "ClassifierResult",
    "HeuristicIntentClassifier",
    "get_default_classifier",
]
