"""Unit tests for voix_worker.audio.text_processing."""

from voix_worker.audio.text_processing import (
    chunk_sentence,
    normalize_text,
    prepare_chunks,
    split_sentences,
)


def test_normalize_text_collapses_whitespace():
    assert normalize_text("Hello    world\n\n") == "Hello world"


def test_normalize_text_expands_abbreviations():
    result = normalize_text("Dr. Smith met Mr. Jones.")
    assert "Doctor Smith" in result
    assert "Mister Jones" in result


def test_split_sentences_basic():
    text = "Hello there. How are you? I am fine!"
    sentences = split_sentences(text)
    assert sentences == ["Hello there.", "How are you?", "I am fine!"]


def test_split_sentences_empty():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_chunk_sentence_short_passthrough():
    sentence = "Short sentence."
    assert chunk_sentence(sentence, max_chars=250) == [sentence]


def test_chunk_sentence_splits_long_sentence():
    clause = "this is a clause that repeats, " * 20
    chunks = chunk_sentence(clause.strip(), max_chars=100)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 100 or " " not in c  # allow single unsplittable words


def test_prepare_chunks_indexing():
    text = "First sentence. Second sentence. Third sentence."
    chunks = prepare_chunks(text)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].text == "First sentence."


def test_prepare_chunks_drops_unspeakable_chunks():
    assert prepare_chunks("... !!! ???") == []
    assert prepare_chunks("?! ... ;") == []
    # stray punctuation attached to real words is fine: the chunk is still speakable
    assert [c.text for c in prepare_chunks("Hello. Bye!")] == ["Hello.", "Bye!"]
