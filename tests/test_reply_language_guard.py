"""The reply-language translation pass must never DEGRADE the reply.

Live failure: a price reply went through the English-enforcement rewrite and
came back truncated — "The current price of Bitcoin is \\$6" spoken instead
of $63,551.38. The pass checked only "no non-Latin letters" before accepting
the rewrite; it must also verify the rewrite preserves the reply's substance
(every significant number survives, length is sane) and strip markdown
escaping artefacts, otherwise the ORIGINAL reply is kept (fail-open).
"""

from jarvis.reply.engine import _translation_acceptable, _clean_translation


class TestTranslationAcceptable:
    def test_good_translation_is_accepted(self):
        orig = "Η τιμή του Bitcoin είναι 63,551.38 δολάρια αυτή τη στιγμή, Boss."
        new = "Bitcoin is at $63,551.38 right now, Boss."
        assert _translation_acceptable(orig, new)

    def test_truncated_number_is_rejected(self):
        orig = "Η τιμή του Bitcoin είναι 63,551.38 δολάρια αυτή τη στιγμή, Boss."
        new = "The current price of Bitcoin is $6"
        assert not _translation_acceptable(orig, new)

    def test_degenerate_short_output_is_rejected(self):
        orig = "Λυπάμαι, δεν κατάφερα να ολοκληρώσω το αίτημα γιατί το εργαλείο απέτυχε με σφάλμα στα πεδία."
        new = "Sorry."
        assert not _translation_acceptable(orig, new)

    def test_still_greek_is_rejected(self):
        orig = "Η τιμή είναι 100 δολάρια."
        new = "The price is 100 δολάρια."
        assert not _translation_acceptable(orig, new)

    def test_empty_translation_is_rejected(self):
        assert not _translation_acceptable("κάτι είπε", "")
        assert not _translation_acceptable("κάτι είπε", None)

    def test_no_numbers_passes_on_length_alone(self):
        orig = "Λυπάμαι, δεν κατάφερα να ολοκληρώσω το αίτημά σου αυτή τη φορά."
        new = "Sorry, I could not complete your request this time."
        assert _translation_acceptable(orig, new)


class TestCleanTranslation:
    def test_strips_latex_dollar_escapes(self):
        assert _clean_translation("price is \\$63,551.38") == "price is $63,551.38"

    def test_strips_bold_markdown(self):
        assert _clean_translation("**Done** — Spotify is left") == "Done — Spotify is left"

    def test_plain_text_untouched(self):
        assert _clean_translation("Bitcoin is at $63,551.38.") == "Bitcoin is at $63,551.38."
