"""Project auto-suggest: the policy is the product, so the policy is what's tested.

A suggestion chip that fires on a single off-topic question is noise the user learns to
dismiss without reading, which is worse than never suggesting at all. These tests pin
the restraint: three consecutive agreeing turns, never the current project, never
Scratch, never an auto-move, and silence for the rest of the session once dismissed.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import project_suggest as ps  # noqa: E402

ENG = "The serdes CDR jitter is failing BER at nyquist with this equalizer"
ENG2 = "Check the PLL phase-noise and the CTLE peaking on the high-speed-io channel"
ENG3 = "Layout parasitic capacitance near the LDO bandgap is hurting SNDR"
FIN = "Run a DCF valuation with EBITDA margin and free-cash-flow against the P/E"
FIN2 = "Hedge the portfolio with put-option greeks — delta, vega, implied-vol"
FIN3 = "The earnings-call guidance moved market-cap; check dividend and buyback yield"
ML = "The transformer attention logits need a lower learning-rate to stop overfitting"
ML2 = "Quantization plus LoRA finetune on this dataset-split raised perplexity"
ML3 = "Swap cross-entropy loss-function and tune dropout regularization per epoch"
CHIT = "ok thanks that helps a lot"


class ClassifyTest(unittest.TestCase):
    def test_domains_are_recognised(self):
        self.assertEqual(ps.classify(ENG)[0], "engineering")
        self.assertEqual(ps.classify(FIN)[0], "finance")
        self.assertEqual(ps.classify(ML)[0], "ml")

    def test_small_talk_is_not_a_domain(self):
        self.assertEqual(ps.classify(CHIT)[0], "general")
        self.assertEqual(ps.classify("hi")[0], "general")
        self.assertEqual(ps.classify("")[0], "general")

    def test_generic_words_do_not_trigger(self):
        """'model', 'signal', 'risk' are everywhere — they must not classify."""
        for text in (
            "can you build a model of this signal for me please",
            "what is the risk of doing that in production today",
            "please summarise the document and give me the key points",
        ):
            self.assertEqual(ps.classify(text)[0], "general", text)

    def test_one_marker_is_not_enough(self):
        self.assertEqual(ps.classify("tell me about the transformer in that story")[0], "general")

    def test_ambiguous_turn_needs_a_clear_winner(self):
        """Equal evidence for two domains resolves to no suggestion, not a coin flip."""
        mixed = "the transformer embedding valuation ebitda"
        self.assertEqual(ps.classify(mixed)[0], "general")


class StreakPolicyTest(unittest.TestCase):
    def setUp(self):
        ps.reset()
        self.sid = 4242

    def tearDown(self):
        ps.reset()

    def _observe(self, text, current="general"):
        return ps.observe(self.sid, text, current)

    def test_needs_three_consecutive_turns(self):
        self.assertFalse(self._observe(ENG)["suggest"])
        self.assertFalse(self._observe(ENG2)["suggest"])
        out = self._observe(ENG3)
        self.assertTrue(out["suggest"])
        self.assertEqual(out["category"], "engineering")
        self.assertEqual(out["streak"], 3)

    def test_interruption_resets_the_streak(self):
        self._observe(ENG)
        self._observe(ENG2)
        self.assertFalse(self._observe(CHIT)["suggest"], "small talk must reset")
        self.assertFalse(self._observe(ENG3)["suggest"], "streak restarted at 1")

    def test_switching_domain_restarts_the_count(self):
        self._observe(ENG)
        self._observe(ENG2)
        self._observe(FIN)          # different domain — streak restarts at 1
        self.assertFalse(self._observe(FIN2)["suggest"])
        self.assertTrue(self._observe(FIN3)["suggest"])

    def test_never_suggests_the_current_project(self):
        for text in (ENG, ENG2, ENG3):
            out = ps.observe(self.sid, text, "engineering")
            self.assertFalse(out["suggest"], out)

    def test_dismiss_silences_the_rest_of_the_session(self):
        self._observe(ENG)
        self._observe(ENG2)
        self.assertTrue(self._observe(ENG3)["suggest"])
        ps.dismiss(self.sid)
        for text in (ENG, ENG2, ENG3, ENG, ENG2, ENG3):
            self.assertFalse(self._observe(text)["suggest"], "dismissal must persist")

    def test_accept_clears_streak_so_it_does_not_immediately_renag(self):
        self._observe(ENG)
        self._observe(ENG2)
        self.assertTrue(self._observe(ENG3)["suggest"])
        ps.accepted(self.sid)
        # Now in Engineering; further engineering turns are the current project
        self.assertFalse(ps.observe(self.sid, ENG, "engineering")["suggest"])

    def test_sessions_are_independent(self):
        ps.observe(1, ENG, "general")
        ps.observe(1, ENG2, "general")
        self.assertFalse(ps.observe(2, ENG3, "general")["suggest"], "streak leaked across sessions")

    def test_no_session_id_is_silent(self):
        self.assertFalse(ps.observe(0, ENG, "general")["suggest"])

    def test_general_is_never_suggested(self):
        for _ in range(6):
            out = self._observe(CHIT, "engineering")
            self.assertFalse(out["suggest"])
            self.assertEqual(out["category"], "")


class EndpointContractTest(unittest.TestCase):
    """The handler's shape, without booting the HTTP server."""

    def setUp(self):
        ps.reset()

    def tearDown(self):
        ps.reset()

    def test_observe_result_is_json_safe(self):
        out = ps.observe(9, ENG, "general")
        for key in ("suggest", "category", "project", "confidence"):
            self.assertIn(key, out)
        self.assertIsInstance(out["suggest"], bool)

    def test_project_label_is_human_readable(self):
        ps.observe(9, ENG, "general")
        ps.observe(9, ENG2, "general")
        out = ps.observe(9, ENG3, "general")
        self.assertEqual(out["project"], "Engineering")
        self.assertGreaterEqual(out["confidence"], ps.MIN_CONFIDENCE)

    def test_every_suggestable_category_maps_to_a_real_project_category(self):
        import db

        for cat in ps.SUGGESTABLE:
            self.assertIn(cat, db.MODE_TO_CATEGORY, f"{cat} has no project category")


if __name__ == "__main__":
    unittest.main()
