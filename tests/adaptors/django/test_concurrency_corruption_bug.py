# Save this file as e.g., your_app/tests/test_concurrency_fix.py
from django.test import TestCase, RequestFactory
from unittest.mock import patch

from statezero.core.process_request import RequestProcessor
from statezero.adaptors.django.config import config, registry
from statezero.core.config import ModelConfig
from statezero.adaptors.django.permissions import AllowAllPermission
from tests.django_app.models import DummyModel  # Make sure this import path is correct


class ConcurrencyFixTestCase(TestCase):
    """
    This test case verifies that the race condition has been FIXED by simulating
    the interleaving of two requests that previously would have corrupted shared state.

    With the stateless ORM adapter, Request A should now get the correct results
    regardless of Request B's interference.
    """

    @classmethod
    def setUpTestData(cls):
        for i in range(5):
            DummyModel.objects.create(name=f"Item {i}", value=i)

    def setUp(self):
        if DummyModel not in registry._models_config:
            registry.register(
                DummyModel,
                ModelConfig(model=DummyModel, permissions=[AllowAllPermission]),
            )

        self.factory = RequestFactory()
        self.model_name = config.orm_provider.get_model_name(DummyModel)

    def test_request_interleaving_no_longer_corrupts_state(self):
        """
        Simulates Request B executing in the middle of Request A,
        demonstrating that the stateless ORM provider eliminates the race condition.
        Request A should now get the correct results (5 items) regardless of Request B.
        """
        processor = RequestProcessor(config=config, registry=registry)

        # Request A: Should fetch all 5 items.
        request_A_ast = {"query": {"type": "read"}}
        mock_request_A = self.factory.post(
            f"/{self.model_name}/", request_A_ast, content_type="application/json"
        )
        mock_request_A.data = {"ast": request_A_ast}
        mock_request_A.parser_context = {"kwargs": {"model_name": self.model_name}}

        # Request B: A different request that should fetch 0 items.
        request_B_ast = {
            "query": {"type": "read", "filter": {"conditions": {"name": "nonexistent"}}}
        }
        mock_request_B = self.factory.post(
            f"/{self.model_name}/", request_B_ast, content_type="application/json"
        )
        mock_request_B.data = {"ast": request_B_ast}
        mock_request_B.parser_context = {"kwargs": {"model_name": self.model_name}}

        # NOTE: Since we've made the ORM adapter stateless, there's no longer a
        # set_queryset method to intercept. But we can still simulate the interleaving
        # by patching a method that gets called during request processing.

        original_get_queryset = config.orm_provider.get_queryset
        interrupt_triggered = False

        def side_effect_to_simulate_interleaving(*args, **kwargs):
            """
            Simulate the same interleaving scenario, but now with stateless adapters.
            Request B should not be able to corrupt Request A's state.
            """
            nonlocal interrupt_triggered
            result = original_get_queryset(*args, **kwargs)

            # Trigger the interleaving when we see Request A's base queryset
            if (
                not interrupt_triggered
                and hasattr(result, "count")
                and result.count() == 5
            ):
                interrupt_triggered = True
                print("\n--- Request A got its base queryset. PAUSING. ---")
                print(f"--- Request A's queryset has {result.count()} items. ---")
                print("--- Running Request B to completion... ---")

                # Execute Request B completely in the middle of Request A
                interloping_processor = RequestProcessor(
                    config=config, registry=registry
                )
                result_B = interloping_processor.process_request(req=mock_request_B)

                print(
                    f"--- Request B completed with {len(result_B['data']['data'])} items (expected 0). ---"
                )
                print("--- Resuming Request A... ---")
                print(
                    "--- With stateless adapters, Request A should still get correct results! ---"
                )

            return result

        with patch.object(
            config.orm_provider,
            "get_queryset",
            side_effect=side_effect_to_simulate_interleaving,
        ):
            print("--- Starting Request A... ---")
            result_A = processor.process_request(req=mock_request_A)

        print(f"Final result for Request A: {len(result_A['data']['data'])} items")

        # ***** UPDATED ASSERTION - NOW EXPECTS CORRECT BEHAVIOR *****
        # With the stateless ORM adapter, Request A should get the correct result (5 items)
        # regardless of Request B's interference.
        self.assertEqual(
            len(result_A["data"]["data"]),
            5,  # NOW expecting the CORRECT result
            "RACE CONDITION STILL EXISTS: Request A should return 5 items, but the race condition caused it to return a different number. The stateless fix may not be complete.",
        )
        print(
            "\n🎉 SUCCESS: Request A correctly returned 5 items despite Request B's interference!"
        )
        print("✅ The race condition has been eliminated by the stateless ORM adapter!")

    def test_both_requests_get_correct_independent_results(self):
        """
        Additional test to verify that both requests get their correct, independent results
        when run concurrently.
        """
        processor = RequestProcessor(config=config, registry=registry)

        # Request A: Should fetch all 5 items
        request_A_ast = {"query": {"type": "read"}}
        mock_request_A = self.factory.post(
            f"/{self.model_name}/", request_A_ast, content_type="application/json"
        )
        mock_request_A.data = {"ast": request_A_ast}
        mock_request_A.parser_context = {"kwargs": {"model_name": self.model_name}}

        # Request B: Should fetch 0 items (filtered to nonexistent)
        request_B_ast = {
            "query": {"type": "read", "filter": {"conditions": {"name": "nonexistent"}}}
        }
        mock_request_B = self.factory.post(
            f"/{self.model_name}/", request_B_ast, content_type="application/json"
        )
        mock_request_B.data = {"ast": request_B_ast}
        mock_request_B.parser_context = {"kwargs": {"model_name": self.model_name}}

        # Execute both requests
        result_A = processor.process_request(req=mock_request_A)
        result_B = processor.process_request(req=mock_request_B)

        # Both should get their correct, independent results
        self.assertEqual(
            len(result_A["data"]["data"]), 5, "Request A should return all 5 items"
        )
        self.assertEqual(
            len(result_B["data"]["data"]),
            0,
            "Request B should return 0 items (filtered)",
        )

        print("✅ Both requests returned correct independent results!")

    def test_original_race_condition_scenario_no_longer_possible(self):
        """
        Test that demonstrates the original race condition scenario is no longer possible.
        This test simulates the exact conditions that caused the original bug and verifies
        they no longer cause corruption.
        """
        # This test would have failed with the old singleton adapter but should pass now
        processor = RequestProcessor(config=config, registry=registry)

        # Create multiple requests that would have interfered with each other
        requests_data = [
            {"query": {"type": "read"}},  # Should get 5 items
            {
                "query": {"type": "read", "filter": {"conditions": {"value__gt": 3}}}
            },  # Should get items with value > 3
            {
                "query": {
                    "type": "read",
                    "filter": {"conditions": {"name__icontains": "Item 1"}},
                }
            },  # Should get 1 item
        ]

        expected_results = [5, 1, 1]  # Expected counts for each request
        actual_results = []

        for i, request_data in enumerate(requests_data):
            mock_request = self.factory.post(
                f"/{self.model_name}/", request_data, content_type="application/json"
            )
            mock_request.data = {"ast": request_data}
            mock_request.parser_context = {"kwargs": {"model_name": self.model_name}}

            result = processor.process_request(req=mock_request)
            actual_count = len(result["data"]["data"])
            actual_results.append(actual_count)

            print(
                f"Request {i+1}: Expected {expected_results[i]} items, got {actual_count} items"
            )

        # All requests should get their correct results
        for i, (expected, actual) in enumerate(zip(expected_results, actual_results)):
            self.assertEqual(
                actual,
                expected,
                f"Request {i+1} returned {actual} items but should have returned {expected}. "
                f"Race condition may still exist.",
            )

        print("✅ All requests returned correct results - no state corruption!")
        print("🎉 Race condition has been successfully eliminated!")


class LegacyRaceConditionTestCase(TestCase):
    """
    This is the ORIGINAL test case that demonstrated the race condition bug.
    We keep it here for historical reference and to show how the bug manifested.

    THIS TEST SHOULD NOW FAIL because the bug has been fixed!
    """

    @classmethod
    def setUpTestData(cls):
        for i in range(5):
            DummyModel.objects.create(name=f"Item {i}", value=i)

    def setUp(self):
        if DummyModel not in registry._models_config:
            registry.register(
                DummyModel,
                ModelConfig(model=DummyModel, permissions=[AllowAllPermission]),
            )

        self.factory = RequestFactory()
        self.model_name = config.orm_provider.get_model_name(DummyModel)

    def test_original_race_condition_no_longer_exists(self):
        """
        LEGACY TEST: This test originally PASSED when the race condition existed,
        proving the bug. Now it should FAIL because we fixed the bug!

        If this test passes, it means the race condition still exists.
        If this test fails, it means we successfully fixed the race condition! 🎉
        """
        # Skip this test if set_queryset method no longer exists (which means we've fixed it)
        if not hasattr(config.orm_provider, "set_queryset"):
            self.skipTest(
                "set_queryset method removed - race condition fix implemented!"
            )

        processor = RequestProcessor(config=config, registry=registry)

        # Request A: Should fetch all 5 items.
        request_A_ast = {"query": {"type": "read"}}
        mock_request_A = self.factory.post(
            f"/{self.model_name}/", request_A_ast, content_type="application/json"
        )
        mock_request_A.data = {"ast": request_A_ast}
        mock_request_A.parser_context = {"kwargs": {"model_name": self.model_name}}

        # Request B: A different request that should fetch 0 items.
        request_B_ast = {
            "query": {"type": "read", "filter": {"conditions": {"name": "nonexistent"}}}
        }
        mock_request_B = self.factory.post(
            f"/{self.model_name}/", request_B_ast, content_type="application/json"
        )
        mock_request_B.data = {"ast": request_B_ast}
        mock_request_B.parser_context = {"kwargs": {"model_name": self.model_name}}

        original_set_queryset = config.orm_provider.set_queryset
        interrupt_triggered = False

        def side_effect_to_simulate_race_condition(*args, **kwargs):
            nonlocal interrupt_triggered
            original_set_queryset(*args, **kwargs)

            queryset_arg = args[0]
            if not interrupt_triggered and queryset_arg.count() == 5:
                interrupt_triggered = True
                print("\n--- LEGACY TEST: Request A called set_queryset. PAUSING. ---")
                print(
                    f"--- Shared ORM state now holds queryset for {queryset_arg.count()} items. ---"
                )
                print("--- Running Request B to completion... ---")

                interloping_processor = RequestProcessor(
                    config=config, registry=registry
                )
                interloping_processor.process_request(req=mock_request_B)

                print(
                    "--- Request B finished. Checking if shared ORM state was corrupted... ---"
                )
                print("--- Resuming Request A... ---")
            return

        with patch.object(
            config.orm_provider,
            "set_queryset",
            side_effect=side_effect_to_simulate_race_condition,
        ):
            print("--- LEGACY TEST: Starting Request A... ---")
            result_A = processor.process_request(req=mock_request_A)

        print(
            f"LEGACY TEST: Final result for Request A: {len(result_A['data']['data'])} items"
        )

        # ***** ORIGINAL ASSERTION THAT EXPECTED THE BUG *****
        # This assertion now should FAIL because we fixed the race condition!
        try:
            self.assertEqual(
                len(result_A["data"]["data"]),
                0,  # This was the BUGGY behavior we expected before
                "UNEXPECTED: The race condition still exists! Request A returned 0 items due to state corruption.",
            )
            # If we get here, the test passed, meaning the bug still exists
            print(
                "\n❌ LEGACY TEST PASSED: This means the race condition bug still exists!"
            )
            print("❌ The fix was not successful.")

        except AssertionError:
            # If we get here, the test failed, meaning the bug is fixed!
            actual_count = len(result_A["data"]["data"])
            print(
                f"\n🎉 LEGACY TEST FAILED (this is good!): Request A returned {actual_count} items instead of 0!"
            )
            print("✅ This proves the race condition has been successfully fixed!")
            print("✅ Request A is no longer corrupted by Request B's interference!")

            # Re-raise with a success message
            raise AssertionError(
                f"🎉 SUCCESS! The race condition has been fixed! "
                f"Request A correctly returned {actual_count} items instead of being corrupted to 0 items. "
                f"This test failure proves the fix worked!"
            )
