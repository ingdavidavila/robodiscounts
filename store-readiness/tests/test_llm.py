import unittest

from storecheck import llm_selftest


class GuardrailTests(unittest.TestCase):
    def test_every_guardrail_holds(self):
        failed = [n for n, ok in llm_selftest.run() if not ok]
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
