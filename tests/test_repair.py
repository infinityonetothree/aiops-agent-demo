import unittest

from aiops.repair import RepairPlan, _validate_and_apply


SOURCE = """def f(product_ids):
    _seen_product_ids.extend(product_ids)
"""


class RepairPolicyTests(unittest.TestCase):
    def test_small_bounded_replacement_is_accepted(self):
        plan = RepairPlan(
            target_file="recommendation_server.py",
            old_text="_seen_product_ids.extend(product_ids)",
            new_text="_seen_product_ids.extend(product_ids)\n    del _seen_product_ids[:-500]",
            rationale="bound retained history",
        )
        repaired = _validate_and_apply(SOURCE, plan)
        self.assertIn("del _seen_product_ids[:-500]", repaired)

    def test_unrelated_replacement_is_rejected(self):
        plan = RepairPlan(
            target_file="recommendation_server.py", old_text="def f(product_ids):",
            new_text="def f(product_ids):", rationale="no-op",
        )
        with self.assertRaisesRegex(ValueError, "unbounded append"):
            _validate_and_apply(SOURCE, plan)

    def test_dangerous_capability_is_rejected(self):
        plan = RepairPlan(
            target_file="recommendation_server.py",
            old_text="_seen_product_ids.extend(product_ids)",
            new_text="_seen_product_ids.extend(product_ids); eval('1')",
            rationale="unsafe",
        )
        with self.assertRaisesRegex(ValueError, "forbidden"):
            _validate_and_apply(SOURCE, plan)

    def test_rebinding_shared_list_is_rejected(self):
        plan = RepairPlan(
            target_file="recommendation_server.py",
            old_text="_seen_product_ids.extend(product_ids)",
            new_text=("_seen_product_ids.extend(product_ids)\n"
                      "_seen_product_ids = _seen_product_ids[-500:]"),
            rationale="unsafe rebinding",
        )
        with self.assertRaisesRegex(ValueError, "rebind"):
            _validate_and_apply(SOURCE, plan)
