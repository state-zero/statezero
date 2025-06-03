from statezero.adaptors.django.config import config, registry
from statezero.core.config import ModelConfig
from tests.django_app.models import (ComprehensiveModel, CustomPKModel,
                                     DeepModelLevel1, DeepModelLevel2,
                                     DeepModelLevel3, DummyModel,
                                     DummyRelatedModel,
                                     ModelWithCustomPKRelation,
                                     NameFilterCustomPKModel, Product,
                                     ProductCategory, Order, OrderItem, FileTest)

from tests.django_app.hooks import set_created_by, normalize_email, generate_order_number
from statezero.core.classes import AdditionalField
from statezero.adaptors.django.permissions import AllowAllPermission
from django.db import models

# Register DummyRelatedModel
registry.register(
    DummyRelatedModel,
    ModelConfig(
        model=DummyRelatedModel,
        filterable_fields={"name"},
        searchable_fields={"name"},
        ordering_fields={"name"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
    ),
)

# Register DummyModel
registry.register(
    DummyModel,
    ModelConfig(
        model=DummyModel,
        filterable_fields={"name", "value"},
        searchable_fields={"name"},
        ordering_fields={"value"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
    ),
)

registry.register(
    FileTest,
    ModelConfig(
        model=FileTest,
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"]
    )
)

# Register DeepModelLevel3
registry.register(
    DeepModelLevel3,
    ModelConfig(
        model=DeepModelLevel3,
        filterable_fields={"name"},
        searchable_fields={"name"},
        ordering_fields={"name"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
    ),
)

# Register DeepModelLevel2
registry.register(
    DeepModelLevel2,
    ModelConfig(
        model=DeepModelLevel2,
        filterable_fields={"name"},
        searchable_fields={"name"},
        ordering_fields={"name"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
    ),
)

# Register DeepModelLevel1
registry.register(
    DeepModelLevel1,
    ModelConfig(
        model=DeepModelLevel1,
        filterable_fields={"name"},
        searchable_fields={"name"},
        ordering_fields={"name"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
    ),
)

# Register ComprehensiveModel
registry.register(
    ComprehensiveModel,
    ModelConfig(
        model=ComprehensiveModel,
        filterable_fields={"char_field", "int_field"},
        searchable_fields={"char_field", "text_field"},
        ordering_fields={"int_field"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
    ),
)

# Register CustomPKModel
registry.register(
    CustomPKModel,
    ModelConfig(
        model=CustomPKModel,
        filterable_fields={"name", "custom_pk"},
        searchable_fields={"name"},
        ordering_fields={"name", "custom_pk"},
        # Use ReadOnlyPermission to test that we can't modify this model
        permissions=["tests.django_app.permissions.ReadOnlyPermission"],
    ),
)

# Register ModelWithCustomPKRelation
registry.register(
    ModelWithCustomPKRelation,
    ModelConfig(
        model=ModelWithCustomPKRelation,
        filterable_fields={"name", "custom_pk_related"},
        searchable_fields={"name"},
        ordering_fields={"name"},
        # Use RestrictedFieldsPermission to test field-level permissions
        permissions=["tests.django_app.permissions.RestrictedFieldsPermission"],
    ),
)

# Register NameFilterCustomPKModel with NameFilterPermission
registry.register(
    NameFilterCustomPKModel,
    ModelConfig(
        model=NameFilterCustomPKModel,
        filterable_fields={"name", "custom_pk"},
        searchable_fields={"name"},
        ordering_fields={"name", "custom_pk"},
        permissions=["tests.django_app.permissions.NameFilterPermission"],
    ),
)

# Register ProductCategory
registry.register(
    ProductCategory,
    ModelConfig(
        model=ProductCategory,
        filterable_fields="__all__",
        searchable_fields={"name"},
        ordering_fields={"name"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
    ),
)

# Register Product with additional fields and custom querysets
registry.register(
    Product,
    ModelConfig(
        model=Product,
        filterable_fields="__all__",
        searchable_fields={"name", "description"},
        ordering_fields={"name", "price", "created_at"},
        permissions=[AllowAllPermission],
        # Add additional computed fields
        additional_fields=[
            AdditionalField(
                name="price_with_tax",
                field=models.DecimalField(max_digits=10, decimal_places=2),
                title="Price (incl. tax)"
            ),
            AdditionalField(
                name="display_name",
                field=models.CharField(max_length=150),
                title="Display Name"
            )
        ],
        # Add pre-processing hooks
        pre_hooks=[set_created_by],
        # Add custom querysets here
        custom_querysets={
            'active_products': "tests.django_app.custom_querysets.ActiveProductsQuerySet",
            'by_price_range': "tests.django_app.custom_querysets.PricingQuerySet"
        }
    ),
)

# Register Order with hooks
registry.register(
    Order,
    ModelConfig(
        model=Order,
        filterable_fields="__all__",
        searchable_fields={"order_number", "customer_name"},
        ordering_fields={"created_at", "total"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
        # Use pre and post hooks
        pre_hooks=[normalize_email],
        post_hooks=[generate_order_number],
        # Add custom querysets here
        custom_querysets={
            'recent_orders': "tests.django_app.custom_querysets.RecentOrdersQuerySet",
            'orders_by_status': "tests.django_app.custom_querysets.OrderStatusQuerySet"
        }
    ),
)

# Register OrderItem
registry.register(
    OrderItem,
    ModelConfig(
        model=OrderItem,
        filterable_fields="__all__",
        searchable_fields={},
        ordering_fields={"price", "quantity"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
        # Add additional computed field
        additional_fields=[
            AdditionalField(
                name="subtotal",
                field=models.DecimalField(max_digits=10, decimal_places=2),
                title="Subtotal"
            )
        ],
    ),
)