"""Expected red test on the planted leak. Fix Agent should make it green."""

import unittest

import recommendation_server as service


class RecommendationTests(unittest.TestCase):
    def test_recommendation_response(self):
        self.assertEqual(len(service.get_recommendations(["PRODUCT-1"])), 5)

    def test_memory_is_bounded(self):
        start = service.seen_count()
        for i in range(5000):
            service.get_recommendations([f"PRODUCT-{i % 20}"])
        self.assertLess(service.seen_count() - start, 1000)
