"""Unit tests for AnyOf / AllOf permission compositors."""
import unittest
from statezero.core.interfaces import AbstractActionPermission
from statezero.core.permissions import AnyOf, AllOf


class AlwaysAllow(AbstractActionPermission):
    def has_permission(self, request, action_name: str) -> bool:
        return True

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        return True


class AlwaysDeny(AbstractActionPermission):
    def has_permission(self, request, action_name: str) -> bool:
        return False

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        return False


class AllowIfAdmin(AbstractActionPermission):
    """Passes only when request.is_admin is True."""
    def has_permission(self, request, action_name: str) -> bool:
        return getattr(request, "is_admin", False)

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        return getattr(request, "is_admin", False)


class _FakeRequest:
    def __init__(self, is_admin=False):
        self.is_admin = is_admin


# ---------------------------------------------------------------------------
# AnyOf tests
# ---------------------------------------------------------------------------

class TestAnyOf(unittest.TestCase):
    def test_passes_if_any_child_passes(self):
        perm = AnyOf(AlwaysDeny, AlwaysAllow)
        self.assertTrue(perm.has_permission(None, "act"))

    def test_fails_if_all_children_fail(self):
        perm = AnyOf(AlwaysDeny, AlwaysDeny)
        self.assertFalse(perm.has_permission(None, "act"))

    def test_single_child_pass(self):
        perm = AnyOf(AlwaysAllow)
        self.assertTrue(perm.has_permission(None, "act"))

    def test_single_child_fail(self):
        perm = AnyOf(AlwaysDeny)
        self.assertFalse(perm.has_permission(None, "act"))

    def test_empty_returns_false(self):
        perm = AnyOf()
        self.assertFalse(perm.has_permission(None, "act"))

    def test_has_action_permission_any(self):
        perm = AnyOf(AlwaysDeny, AlwaysAllow)
        self.assertTrue(perm.has_action_permission(None, "act", {}))

    def test_has_action_permission_none(self):
        perm = AnyOf(AlwaysDeny, AlwaysDeny)
        self.assertFalse(perm.has_action_permission(None, "act", {}))

    def test_has_action_permission_empty(self):
        perm = AnyOf()
        self.assertFalse(perm.has_action_permission(None, "act", {}))

    def test_accepts_instances_as_children(self):
        perm = AnyOf(AlwaysDeny(), AlwaysAllow())
        self.assertTrue(perm.has_permission(None, "act"))

    def test_mixed_classes_and_instances(self):
        perm = AnyOf(AlwaysDeny, AlwaysAllow())
        self.assertTrue(perm.has_permission(None, "act"))


# ---------------------------------------------------------------------------
# AllOf tests
# ---------------------------------------------------------------------------

class TestAllOf(unittest.TestCase):
    def test_passes_if_all_children_pass(self):
        perm = AllOf(AlwaysAllow, AlwaysAllow)
        self.assertTrue(perm.has_permission(None, "act"))

    def test_fails_if_any_child_fails(self):
        perm = AllOf(AlwaysAllow, AlwaysDeny)
        self.assertFalse(perm.has_permission(None, "act"))

    def test_single_child_pass(self):
        perm = AllOf(AlwaysAllow)
        self.assertTrue(perm.has_permission(None, "act"))

    def test_single_child_fail(self):
        perm = AllOf(AlwaysDeny)
        self.assertFalse(perm.has_permission(None, "act"))

    def test_empty_returns_false(self):
        perm = AllOf()
        self.assertFalse(perm.has_permission(None, "act"))

    def test_has_action_permission_all(self):
        perm = AllOf(AlwaysAllow, AlwaysAllow)
        self.assertTrue(perm.has_action_permission(None, "act", {}))

    def test_has_action_permission_fail(self):
        perm = AllOf(AlwaysAllow, AlwaysDeny)
        self.assertFalse(perm.has_action_permission(None, "act", {}))

    def test_has_action_permission_empty(self):
        perm = AllOf()
        self.assertFalse(perm.has_action_permission(None, "act", {}))

    def test_accepts_instances_as_children(self):
        perm = AllOf(AlwaysAllow(), AlwaysAllow())
        self.assertTrue(perm.has_permission(None, "act"))

    def test_mixed_classes_and_instances(self):
        perm = AllOf(AlwaysAllow, AlwaysDeny())
        self.assertFalse(perm.has_permission(None, "act"))


# ---------------------------------------------------------------------------
# Nesting tests
# ---------------------------------------------------------------------------

class TestNesting(unittest.TestCase):
    def test_anyof_with_nested_allof(self):
        # AnyOf(AllOf(Allow, Allow), Deny) -> True (first branch passes)
        perm = AnyOf(AllOf(AlwaysAllow, AlwaysAllow), AlwaysDeny)
        self.assertTrue(perm.has_permission(None, "act"))

    def test_anyof_with_nested_allof_fails(self):
        # AnyOf(AllOf(Allow, Deny), Deny) -> False (both branches fail)
        perm = AnyOf(AllOf(AlwaysAllow, AlwaysDeny), AlwaysDeny)
        self.assertFalse(perm.has_permission(None, "act"))

    def test_allof_with_nested_anyof(self):
        # AllOf(AnyOf(Allow, Deny), Allow) -> True
        perm = AllOf(AnyOf(AlwaysAllow, AlwaysDeny), AlwaysAllow)
        self.assertTrue(perm.has_permission(None, "act"))

    def test_allof_with_nested_anyof_fails(self):
        # AllOf(AnyOf(Deny, Deny), Allow) -> False
        perm = AllOf(AnyOf(AlwaysDeny, AlwaysDeny), AlwaysAllow)
        self.assertFalse(perm.has_permission(None, "act"))

    def test_deep_nesting(self):
        # AnyOf(AllOf(AllowIfAdmin, Allow), AllOf(Deny, Allow))
        # With admin request -> True via first branch
        req = _FakeRequest(is_admin=True)
        perm = AnyOf(
            AllOf(AllowIfAdmin, AlwaysAllow),
            AllOf(AlwaysDeny, AlwaysAllow),
        )
        self.assertTrue(perm.has_permission(req, "act"))

    def test_deep_nesting_non_admin(self):
        # Same structure, non-admin -> False (both branches fail)
        req = _FakeRequest(is_admin=False)
        perm = AnyOf(
            AllOf(AllowIfAdmin, AlwaysAllow),
            AllOf(AlwaysDeny, AlwaysAllow),
        )
        self.assertFalse(perm.has_permission(req, "act"))

    def test_nested_has_action_permission(self):
        perm = AnyOf(AllOf(AlwaysAllow, AlwaysAllow), AlwaysDeny)
        self.assertTrue(perm.has_action_permission(None, "act", {}))


# ---------------------------------------------------------------------------
# isinstance checks — compositors are AbstractActionPermission
# ---------------------------------------------------------------------------

class TestIsInstance(unittest.TestCase):
    def test_anyof_is_abstract_action_permission(self):
        self.assertIsInstance(AnyOf(), AbstractActionPermission)

    def test_allof_is_abstract_action_permission(self):
        self.assertIsInstance(AllOf(), AbstractActionPermission)


if __name__ == "__main__":
    unittest.main()
