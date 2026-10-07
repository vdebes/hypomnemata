"""Paragraph breaks for dictated text, found by meaning rather than by a writing model.

A small writing model cannot tell where an idea ends in a long dictation.
An embedding model gives each sentence a vector of meaning; the code then
compares the few sentences before and after each possible break, and cuts
where the meaning shifts the most. No text is generated: words cannot
change, only line breaks are added.

The user's own paragraph breaks are kept: only long blocks are split.
"""

import math
import re

from hypomnemata.core.llm import Embedder

TARGET_CHARS = 900  # aimed paragraph length: the number of breaks follows from it
MIN_SENTENCES = 3  # no paragraph shorter than this (unless the block itself is)
WINDOW = 3  # sentences compared on each side of a possible break

# A sentence starting with one of these answers the previous one: never open a paragraph
# with it. Checked on the first one or two words, lowercased.
CONNECTORS = {
    "alors", "car", "cependant", "donc", "et", "mais", "ni", "or", "ou", "pourtant",
    "puis", "sauf que", "du coup", "parce que", "en plus",
}  # fmt: skip


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?…])\s+", " ".join(text.split())) if s]


def opens_with_connector(sentence: str) -> bool:
    first = re.findall(r"\w+", sentence.lower())[:2]
    return bool(first) and (first[0] in CONNECTORS or " ".join(first) in CONNECTORS)


def _mean(vectors: list[list[float]]) -> list[float]:
    return [sum(values) / len(vectors) for values in zip(*vectors, strict=True)]


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def _depths(similarities: list[float]) -> list[float]:
    """How deep each similarity sits between the peaks around it (TextTiling)."""
    depths = []
    for i, value in enumerate(similarities):
        left = i
        while left > 0 and similarities[left - 1] >= similarities[left]:
            left -= 1
        right = i
        while right < len(similarities) - 1 and similarities[right + 1] >= similarities[right]:
            right += 1
        depths.append(similarities[left] - value + similarities[right] - value)
    return depths


def breaks(parts: list[str], vectors: list[list[float]], target: int = TARGET_CHARS) -> list[int]:
    """Indices of the sentences that open a new paragraph, in order."""
    count = len(parts)
    similarities = [
        _cosine(_mean(vectors[max(0, gap - WINDOW) : gap]), _mean(vectors[gap : gap + WINDOW]))
        for gap in range(1, count)
    ]
    depths = _depths(similarities)
    wanted = round(sum(map(len, parts)) / target) - 1
    chosen: list[int] = []
    for gap in sorted(range(len(depths)), key=lambda i: depths[i], reverse=True):
        if len(chosen) >= wanted:
            break
        start = gap + 1  # the gap just before sentence `start`
        fits = MIN_SENTENCES <= start <= count - MIN_SENTENCES
        if fits and not opens_with_connector(parts[start]):
            if all(abs(start - other) >= MIN_SENTENCES for other in chosen):
                chosen.append(start)
    return sorted(chosen)


def split_paragraphs(text: str, embedder: Embedder, target: int = TARGET_CHARS) -> str:
    """`text` with long blocks split into paragraphs. Words and their order are unchanged."""
    blocks = [block for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    out = []
    for block in blocks:
        parts = sentences(block)
        if len(block) < target * 1.5 or len(parts) < 2 * MIN_SENTENCES:
            out.append(" ".join(block.split()))
            continue
        cuts = [0, *breaks(parts, embedder.embed(parts), target), len(parts)]
        out.extend(" ".join(parts[a:b]) for a, b in zip(cuts, cuts[1:], strict=False))
    return "\n\n".join(out)
