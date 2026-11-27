import json
import unittest

from storecheck import measure


class MeasureTests(unittest.TestCase):
    def test_weights_sum_to_100_and_every_dimension_has_a_gate(self):
        self.assertEqual(sum(measure.WEIGHTS.values()), 100)
        self.assertEqual(set(measure.WEIGHTS), set(measure.GATES))
        self.assertEqual(set(measure.WEIGHTS), set(measure.NAMES))

    def test_synthetic_benchmark_has_no_failures(self):
        syn = measure.run_synthetic()
        self.assertEqual(syn["failures"], [], syn["failures"])
        self.assertEqual(syn["crashes"], 0)
        self.assertEqual(syn["recall"], 1.0)
        self.assertEqual(syn["false_positive_rate"], 0.0)

    def test_every_rule_has_a_positive_and_a_negative_case(self):
        self.assertEqual(measure.run_synthetic()["rules_without_both"], [])

    def test_catalog_is_consistent(self):
        d1 = measure.d1_coverage()
        self.assertEqual(d1["broken_refs"], [])
        self.assertLessEqual(d1["excluded_share"], 0.6)

    def test_not_checkable_items_always_state_a_reason(self):
        cat = json.loads((measure.ROOT / "storecheck" / "requirements.json").read_text(encoding="utf-8"))
        for it in cat["items"]:
            if it["class"] == "not_checkable":
                self.assertTrue(it.get("reason"), it["id"])
            self.assertTrue(it["source"].startswith("https://"), it["id"])

    def test_verified_readers_name_a_reference_and_an_existing_test(self):
        for r in json.loads((measure.FW / "readers.json").read_text(encoding="utf-8"))["readers"]:
            if r["status"] == "verified":
                self.assertTrue(r["reference"], r["reader"])
                self.assertTrue((measure.ROOT / r["test"]).exists(), r["reader"])

    def test_recording_a_run_requires_log_and_review(self):
        with self.assertRaises(SystemExit):
            measure.main(["--log", "only a log"])

    def test_unmeasured_corpus_counts_as_zero(self):
        syn = measure.run_synthetic()
        d2 = measure.d2_correctness(syn, None)
        self.assertFalse(d2["real_measured"])
        self.assertAlmostEqual(d2["score"], 0.45 * syn["score"] + 0.10 * d2["readers"]["score"])   # real part is 0


if __name__ == "__main__":
    unittest.main()
