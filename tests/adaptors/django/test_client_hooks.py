"""
Hook tests: pre/post-hook behaviour verified through the Python client.

Migrated from test_hooks.py, test_hook_field_persistence.py, and
test_hook_field_security.py.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from statezero.client.runtime_template import Model, configure, _field_permissions_cache
from statezero.client.testing import DjangoTestTransport
from statezero.adaptors.django.config import registry
from tests.django_app.models import (
    Order, OrderItem, Product, ProductCategory,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Client model stubs
# ---------------------------------------------------------------------------

class OrderClient(Model):
    _model_name = "django_app.order"
    _pk_field = "id"
    _relations = {}


class OrderItemClient(Model):
    _model_name = "django_app.orderitem"
    _pk_field = "id"
    _relations = {"order": "django_app.order", "product": "django_app.product"}


class ProductClient(Model):
    _model_name = "django_app.product"
    _pk_field = "id"
    _relations = {"category": "django_app.productcategory"}


class ProductCategoryClient(Model):
    _model_name = "django_app.productcategory"
    _pk_field = "id"
    _relations = {}


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class HookTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username="hook_user", password="password", email="hook@test.com"
        )
        cls.admin = User.objects.create_superuser(
            username="hook_admin", password="admin", email="hookadmin@test.com"
        )

    def setUp(self):
        configure(transport=DjangoTestTransport(user=self.user))
        _field_permissions_cache.clear()
        self.category = ProductCategory.objects.create(name="Hook Test Category")


# ===========================================================================
# Order hooks (normalize_email pre-hook, generate_order_number post-hook)
# ===========================================================================

class TestOrderHooks(HookTestBase):

    def test_create_normalizes_email(self):
        result = OrderClient.objects.create(
            customer_name="Test Customer",
            customer_email="TEST.CUSTOMER@EXAMPLE.COM",
            order_number="DUMMY",
            status="pending",
            total="99.99",
        )
        order = Order.objects.get(pk=result.pk)
        self.assertEqual(order.customer_email, "test.customer@example.com")

    def test_create_generates_order_number(self):
        result = OrderClient.objects.create(
            customer_name="Test Customer",
            customer_email="test@example.com",
            order_number="DUMMY",
            status="pending",
            total="99.99",
        )
        order = Order.objects.get(pk=result.pk)
        self.assertNotEqual(order.order_number, "DUMMY")
        self.assertTrue(order.order_number.startswith("ORD-"))

    def test_update_normalizes_email(self):
        order = Order.objects.create(
            customer_name="Update Test",
            customer_email="original@example.com",
            order_number="ORD-update01",
            status="pending",
            total="49.99",
        )
        instance = OrderClient.objects.get(id=order.pk)
        instance.update(customer_email="UPDATED.EMAIL@EXAMPLE.COM")
        order.refresh_from_db()
        self.assertEqual(order.customer_email, "updated.email@example.com")

    def test_update_replaces_dummy_order_number(self):
        order = Order.objects.create(
            customer_name="Update Test",
            customer_email="test@example.com",
            order_number="ORD-original1",
            status="pending",
            total="49.99",
        )
        instance = OrderClient.objects.get(id=order.pk)
        instance.update(order_number="DUMMY")
        order.refresh_from_db()
        self.assertNotEqual(order.order_number, "DUMMY")
        self.assertTrue(order.order_number.startswith("ORD-"))

    def test_update_or_create_creates_with_hooks(self):
        instance, created = OrderClient.objects.update_or_create(
            defaults={
                "customer_email": "UOC.TEST@EXAMPLE.COM",
                "status": "pending",
                "total": "29.99",
                "order_number": "DUMMY",
            },
            customer_name="UOC-Hooks-Test",
        )
        self.assertTrue(created)
        order = Order.objects.get(pk=instance.pk)
        self.assertEqual(order.customer_email, "uoc.test@example.com")
        self.assertTrue(order.order_number.startswith("ORD-"))

    def test_update_or_create_creates_with_hooks(self):
        instance, created = OrderClient.objects.update_or_create(
            defaults={
                "customer_email": "UOC@EXAMPLE.COM",
                "order_number": "DUMMY",
                "status": "pending",
                "total": "29.99",
            },
            customer_name="UOC-New",
        )
        self.assertTrue(created)
        order = Order.objects.get(pk=instance.pk)
        # pre-hook normalized email
        self.assertEqual(order.customer_email, "uoc@example.com")
        # post-hook generated order number
        self.assertTrue(order.order_number.startswith("ORD-"))


# ===========================================================================
# Hook field persistence — hooks can inject fields not in the allowed set
# ===========================================================================

class TestHookFieldPersistence(HookTestBase):
    """Pre-hooks can add DB fields that aren't in the user-allowed fields."""

    def _restrict_orderitem(self, hook):
        """Temporarily restrict OrderItem fields and add a pre-hook."""
        cfg = registry.get_config(OrderItem)
        self._orig_hooks = cfg.pre_hooks
        self._orig_fields = cfg.fields
        cfg.fields = {"id", "product", "quantity", "price"}
        cfg.pre_hooks = [hook]
        return cfg

    def _restore_orderitem(self, cfg):
        cfg.pre_hooks = self._orig_hooks
        cfg.fields = self._orig_fields

    def _make_fixtures(self):
        product = Product.objects.create(
            name="Persist Product", description="d",
            price=Decimal("99.99"), category=self.category,
        )
        order = Order.objects.create(
            order_number="PERSIST-001",
            customer_name="Persist Customer",
            customer_email="persist@example.com",
            total=Decimal("99.99"),
        )
        return product, order

    def test_create_persists_hook_field(self):
        product, order = self._make_fixtures()

        def add_order(data, request=None):
            data = data.copy()
            data["order"] = order.id
            return data

        cfg = self._restrict_orderitem(add_order)
        try:
            result = OrderItemClient.objects.create(
                product=product.pk, quantity=2, price="99.99",
            )
            saved = OrderItem.objects.get(pk=result.pk)
            self.assertEqual(saved.order_id, order.id)
            self.assertEqual(saved.quantity, 2)
        finally:
            self._restore_orderitem(cfg)

    def test_bulk_create_persists_hook_field(self):
        product, order = self._make_fixtures()

        def add_order(data, request=None):
            data = data.copy()
            data["order"] = order.id
            return data

        cfg = self._restrict_orderitem(add_order)
        try:
            results = OrderItemClient.objects.bulk_create([
                {"product": product.pk, "quantity": 1, "price": "49.99"},
                {"product": product.pk, "quantity": 2, "price": "99.99"},
                {"product": product.pk, "quantity": 3, "price": "149.99"},
            ])
            self.assertEqual(len(results), 3)
            for r in results:
                saved = OrderItem.objects.get(pk=r.pk)
                self.assertEqual(saved.order_id, order.id)
        finally:
            self._restore_orderitem(cfg)

    def test_update_instance_persists_hook_field(self):
        product, order = self._make_fixtures()
        item = OrderItem.objects.create(
            order=order, product=product, quantity=1, price=Decimal("99.99"),
        )

        def modify_price(data, request=None):
            data = data.copy()
            data["price"] = "999.99"
            return data

        cfg = self._restrict_orderitem(modify_price)
        try:
            instance = OrderItemClient.objects.get(id=item.pk)
            instance.update(quantity=5)
            item.refresh_from_db()
            self.assertEqual(item.quantity, 5)
            self.assertEqual(str(item.price), "999.99")
        finally:
            self._restore_orderitem(cfg)

    def test_update_persists_hook_field(self):
        product, order = self._make_fixtures()
        item1 = OrderItem.objects.create(
            order=order, product=product, quantity=1, price=Decimal("99.99"),
        )
        item2 = OrderItem.objects.create(
            order=order, product=product, quantity=2, price=Decimal("99.99"),
        )

        def modify_price(data, request=None):
            data = data.copy()
            data["price"] = "888.88"
            return data

        cfg = self._restrict_orderitem(modify_price)
        try:
            # Filter by product (an allowed field) instead of order (restricted)
            OrderItemClient.objects.filter(product=product.pk).update(quantity=10)
            item1.refresh_from_db()
            item2.refresh_from_db()
            self.assertEqual(item1.quantity, 10)
            self.assertEqual(item2.quantity, 10)
            self.assertEqual(str(item1.price), "888.88")
            self.assertEqual(str(item2.price), "888.88")
        finally:
            self._restore_orderitem(cfg)

    def test_get_or_create_persists_hook_field(self):
        product, order = self._make_fixtures()

        def add_order(data, request=None):
            data = data.copy()
            data["order"] = order.id
            return data

        cfg = self._restrict_orderitem(add_order)
        try:
            instance, created = OrderItemClient.objects.get_or_create(
                defaults={"price": "79.99"},
                product=product.pk, quantity=2,
            )
            self.assertTrue(created)
            saved = OrderItem.objects.get(pk=instance.pk)
            self.assertEqual(saved.order_id, order.id)

            # Second call should get, not create
            instance2, created2 = OrderItemClient.objects.get_or_create(
                defaults={"price": "79.99"},
                product=product.pk, quantity=2,
            )
            self.assertFalse(created2)
            self.assertEqual(instance2.pk, instance.pk)
        finally:
            self._restore_orderitem(cfg)

    def test_update_or_create_persists_hook_field(self):
        product, order = self._make_fixtures()

        def add_order(data, request=None):
            data = data.copy()
            data["order"] = order.id
            return data

        cfg = self._restrict_orderitem(add_order)
        try:
            # Create path
            instance, created = OrderItemClient.objects.update_or_create(
                defaults={"quantity": 1, "price": "89.99"},
                product=product.pk,
            )
            self.assertTrue(created)
            saved = OrderItem.objects.get(pk=instance.pk)
            self.assertEqual(saved.order_id, order.id)

            # Update path
            instance2, created2 = OrderItemClient.objects.update_or_create(
                defaults={"quantity": 3, "price": "89.99"},
                product=product.pk,
            )
            self.assertFalse(created2)
            self.assertEqual(instance2.pk, instance.pk)
            saved.refresh_from_db()
            self.assertEqual(saved.quantity, 3)
        finally:
            self._restore_orderitem(cfg)


# ===========================================================================
# Hook field security — users cannot bypass field filtering
# ===========================================================================

class TestHookFieldSecurity(HookTestBase):
    """Users cannot inject restricted fields; only hooks can."""

    def _restrict_orderitem_no_hook(self):
        """Restrict OrderItem fields WITHOUT a hook."""
        cfg = registry.get_config(OrderItem)
        self._orig_fields = cfg.fields
        cfg.fields = {"id", "product", "quantity", "price"}
        return cfg

    def _restore_orderitem(self, cfg):
        cfg.fields = self._orig_fields

    def _make_fixtures(self):
        product = Product.objects.create(
            name="Security Product", description="d",
            price=Decimal("99.99"), category=self.category,
        )
        order = Order.objects.create(
            order_number="SEC-001",
            customer_name="Security Customer",
            customer_email="sec@example.com",
            total=Decimal("99.99"),
        )
        return product, order

    def test_create_rejects_restricted_field(self):
        """Create should fail when user supplies a required but restricted FK."""
        product, order = self._make_fixtures()
        cfg = self._restrict_orderitem_no_hook()
        try:
            # 'order' is required by DB but not in allowed fields and no hook
            # provides it, so this should fail at DB level
            with self.assertRaises(Exception):
                OrderItemClient.objects.create(
                    product=product.pk, quantity=2, price="99.99",
                    order=order.pk,
                )
        finally:
            self._restore_orderitem(cfg)

    def test_bulk_create_rejects_restricted_field(self):
        """Bulk create should fail when user supplies a required but restricted FK."""
        product, order = self._make_fixtures()
        cfg = self._restrict_orderitem_no_hook()
        try:
            with self.assertRaises(Exception):
                OrderItemClient.objects.bulk_create([
                    {"product": product.pk, "quantity": 1, "price": "49.99", "order": order.pk},
                    {"product": product.pk, "quantity": 2, "price": "99.99", "order": order.pk},
                ])
        finally:
            self._restore_orderitem(cfg)

    def test_update_instance_drops_restricted_field(self):
        """Update should silently drop user-supplied restricted fields."""
        product, order1 = self._make_fixtures()
        order2 = Order.objects.create(
            order_number="SEC-002",
            customer_name="Other",
            customer_email="other@example.com",
            total=Decimal("50.00"),
        )
        item = OrderItem.objects.create(
            order=order1, product=product, quantity=1, price=Decimal("99.99"),
        )
        cfg = self._restrict_orderitem_no_hook()
        try:
            instance = OrderItemClient.objects.get(id=item.pk)
            instance.update(quantity=5, order=order2.pk)
            item.refresh_from_db()
            self.assertEqual(item.quantity, 5)
            # order should NOT have changed
            self.assertEqual(item.order_id, order1.id)
        finally:
            self._restore_orderitem(cfg)

    def test_update_rejects_restricted_field(self):
        """Bulk update should reject user-supplied restricted fields with ValidationError."""
        from statezero.client.runtime_template import ValidationError
        product, order1 = self._make_fixtures()
        order2 = Order.objects.create(
            order_number="SEC-003",
            customer_name="Other",
            customer_email="other@example.com",
            total=Decimal("50.00"),
        )
        item1 = OrderItem.objects.create(
            order=order1, product=product, quantity=1, price=Decimal("99.99"),
        )
        cfg = self._restrict_orderitem_no_hook()
        try:
            with self.assertRaises(ValidationError):
                OrderItemClient.objects.filter(product=product.pk).update(
                    quantity=10, order=order2.pk,
                )
            # Item should be unchanged
            item1.refresh_from_db()
            self.assertEqual(item1.quantity, 1)
            self.assertEqual(item1.order_id, order1.id)
        finally:
            self._restore_orderitem(cfg)

    def test_get_or_create_rejects_restricted_field(self):
        """get_or_create should fail when user supplies a required but restricted FK."""
        product, order = self._make_fixtures()
        cfg = self._restrict_orderitem_no_hook()
        try:
            with self.assertRaises(Exception):
                OrderItemClient.objects.get_or_create(
                    defaults={"price": "79.99", "order": order.pk},
                    product=product.pk, quantity=2,
                )
        finally:
            self._restore_orderitem(cfg)

    def test_update_instance_drops_restricted_field_via_queryset(self):
        """update via queryset should drop user-supplied restricted fields."""
        product, order1 = self._make_fixtures()
        order2 = Order.objects.create(
            order_number="SEC-004",
            customer_name="Other",
            customer_email="other@example.com",
            total=Decimal("50.00"),
        )
        item = OrderItem.objects.create(
            order=order1, product=product, quantity=1, price=Decimal("89.99"),
        )
        cfg = self._restrict_orderitem_no_hook()
        try:
            # Use instance.update() which goes through update_instance
            instance = OrderItemClient.objects.get(id=item.pk)
            instance.update(quantity=5, order=order2.pk)
            item.refresh_from_db()
            self.assertEqual(item.quantity, 5)
            # order should NOT have changed
            self.assertEqual(item.order_id, order1.id)
        finally:
            self._restore_orderitem(cfg)
