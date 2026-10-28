from benchmarks.metrics import ErrorCounts, edit_distance, normalize, score


def test_normalize_ignores_case_punctuation_and_titles():
    assert normalize("Dr. Patel said: “Hello, World!”") == "doctor patel said hello world"
    assert normalize("Don’t  stop—now") == "don't stop now"


def test_edit_distance():
    assert edit_distance("kitten", "sitting") == 3
    assert edit_distance(["a", "b", "c"], ["a", "c"]) == 1
    assert edit_distance([], ["x", "y"]) == 2


def test_perfect_and_imperfect_transcripts():
    assert score("Hello there, friend.", "hello there friend").wer == 0.0
    s = score("the quick brown fox", "the quick fox jumps")  # 1 deletion + 1 insertion
    assert s.word_errors == 2 and s.wer == 0.5


def test_corpus_counts_add_up():
    total = score("a b c d", "a b c d") + score("e f", "e g")
    assert total == ErrorCounts(word_errors=1, words=6, char_errors=1, chars=10)
    assert round(total.wer, 4) == 0.1667
