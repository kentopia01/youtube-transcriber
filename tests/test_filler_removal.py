"""Tests for the clean_filler_words() function in transcription service."""

from app.services.transcription import clean_filler_words


class TestCleanFillerWords:
    def test_removes_um(self):
        assert clean_filler_words("I um think so") == "I think so"

    def test_removes_uh(self):
        assert clean_filler_words("uh we should go") == "we should go"

    def test_removes_uhm(self):
        assert clean_filler_words("uhm that is correct") == "that is correct"

    def test_removes_umm(self):
        assert clean_filler_words("well umm okay") == "well okay"

    def test_removes_you_know(self):
        assert clean_filler_words("it was you know really good") == "it was really good"

    def test_removes_i_mean(self):
        assert clean_filler_words("I mean the result is fine") == "the result is fine"

    def test_removes_basically(self):
        assert clean_filler_words("basically it works") == "it works"

    def test_removes_kind_of(self):
        assert clean_filler_words("it is kind of broken") == "it is broken"

    def test_removes_sort_of(self):
        assert clean_filler_words("that sort of makes sense") == "that makes sense"

    def test_removes_like_before_comma(self):
        result = clean_filler_words("like, we need to go")
        assert "like" not in result.lower().split()
        assert "we need to go" in result

    def test_removes_like_before_pronoun(self):
        assert clean_filler_words("like I said before") == "I said before"

    def test_preserves_like_in_normal_context(self):
        assert clean_filler_words("I like pizza") == "I like pizza"

    def test_collapses_double_spaces(self):
        assert clean_filler_words("hello  world") == "hello world"

    def test_cleans_space_before_punctuation(self):
        assert clean_filler_words("hello , world") == "hello, world"

    def test_empty_string(self):
        assert clean_filler_words("") == ""

    def test_no_fillers(self):
        text = "The quick brown fox jumps over the lazy dog."
        assert clean_filler_words(text) == text

    def test_multiple_fillers(self):
        result = clean_filler_words("um so uh basically it works")
        assert "um" not in result.lower().split()
        assert "uh" not in result.lower().split()
        assert "basically" not in result.lower()
        assert "works" in result

    def test_case_insensitive(self):
        assert "Um" not in clean_filler_words("Um I think so")
        assert "UH" not in clean_filler_words("UH we should go")
