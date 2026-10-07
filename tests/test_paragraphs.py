from conftest import topic_embedder

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.format import words
from hypomnemata.core.paragraphs import breaks, opens_with_connector, sentences, split_paragraphs

WORK = [f"Le travail avance mal, point {n}." for n in range(8)]
LIFE = [f"Le soir je lis un roman, page {n}." for n in range(8)]


def vectors(parts: list[str]) -> list[list[float]]:
    return [[1.0, 0.1] if "travail" in part else [0.1, 1.0] for part in parts]


def test_sentences_ignore_line_breaks() -> None:
    assert sentences("Un.\nDeux ?  Trois !") == ["Un.", "Deux ?", "Trois !"]


def test_connectors() -> None:
    assert opens_with_connector("Sauf que ce n'est pas le cas.")
    assert opens_with_connector("Mais bon.")
    assert opens_with_connector("Du coup, voilà.")
    assert not opens_with_connector("Ensuite je lis.")
    assert not opens_with_connector("Sauf erreur, oui.")


def test_cuts_where_the_meaning_shifts() -> None:
    parts = WORK + LIFE
    assert breaks(parts, vectors(parts), target=len(" ".join(parts)) // 2) == [len(WORK)]


def test_never_opens_a_paragraph_with_a_connector() -> None:
    parts = WORK + ["Mais le soir je lis un roman, page 0."] + LIFE[1:]
    cuts = breaks(parts, vectors(parts), target=len(" ".join(parts)) // 2)
    assert cuts and len(WORK) not in cuts


def test_paragraphs_are_never_too_short() -> None:
    parts = WORK[:2] + LIFE + WORK
    for cut in breaks(parts, vectors(parts), target=100):
        assert 3 <= cut <= len(parts) - 3


def test_split_keeps_words_and_short_blocks(audit: AuditLog) -> None:
    calls: list[list[str]] = []
    long_block = " ".join(WORK * 3 + LIFE * 3)
    text = f"Un petit paragraphe à moi.\n\n{long_block}"

    result = split_paragraphs(text, topic_embedder(audit, calls), target=400)

    assert result.startswith("Un petit paragraphe à moi.\n\n")
    assert words(result) == words(text)
    assert result.count("\n\n") > 1
    assert len(calls) == 1  # only the long block was embedded


def test_short_text_is_not_embedded(audit: AuditLog) -> None:
    calls: list[list[str]] = []
    assert split_paragraphs("Court. Très court.", topic_embedder(audit, calls)) == (
        "Court. Très court."
    )
    assert calls == []
