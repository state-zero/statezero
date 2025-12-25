from statezero.adaptors.django.config import config, registry
from statezero.core.config import ModelConfig
from tests.django_app.models import (ComprehensiveModel, CustomPKModel,
                                     DeepModelLevel1, DeepModelLevel2,
                                     DeepModelLevel3, DummyModel,
                                     DummyRelatedModel,
                                     ModelWithCustomPKRelation,
                                     NameFilterCustomPKModel, Product,
                                     ProductCategory, Order, OrderItem, FileTest,
                                     RatePlan, DailyRate)

from tests.django_app.hooks import set_created_by, normalize_email, generate_order_number
from statezero.core.classes import AdditionalField, DisplayMetadata, FieldGroup, FieldDisplayConfig
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
        # Add display metadata for frontend customization
        display=DisplayMetadata(
            display_title="Product Management",
            display_description="Create and manage products in your catalog",
            field_groups=[
                FieldGroup(
                    display_title="Basic Information",
                    display_description="Essential product details",
                    field_names=["name", "description", "category"]
                ),
                FieldGroup(
                    display_title="Pricing & Availability",
                    display_description="Product pricing and stock information",
                    field_names=["price", "in_stock"]
                ),
                FieldGroup(
                    display_title="Metadata",
                    display_description="System information",
                    field_names=["created_at", "created_by"]
                )
            ],
            field_display_configs=[
                FieldDisplayConfig(
                    field_name="description",
                    display_component="RichTextEditor",
                    display_help_text="Provide a detailed description of the product"
                ),
                FieldDisplayConfig(
                    field_name="category",
                    display_component="CategorySelector",
                    filter_queryset={"name__icontains": ""},
                    display_help_text="Select the product category"
                ),
                FieldDisplayConfig(
                    field_name="price",
                    display_component="CurrencyInput",
                    display_help_text="Enter the product price (tax will be calculated automatically)"
                ),
                FieldDisplayConfig(
                    field_name="in_stock",
                    display_component="StockToggle",
                    display_help_text="Toggle product availability"
                )
            ]
        )
    ),
)

# Register Order with hooks and reverse relationship
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
        # Explicitly declare fields including the reverse relationship "items"
        fields={
            "id", "order_number", "customer_name", "customer_email",
            "total", "status", "created_at", "last_updated",
            "items"  # Reverse relationship from OrderItem
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

# Register RatePlan
registry.register(
    RatePlan,
    ModelConfig(
        model=RatePlan,
        filterable_fields="__all__",
        searchable_fields={"name"},
        ordering_fields={"name"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
    ),
)

# Register DailyRate
registry.register(
    DailyRate,
    ModelConfig(
        model=DailyRate,
        filterable_fields="__all__",
        searchable_fields={},
        ordering_fields={"date", "rate_plan"},
        permissions=["statezero.adaptors.django.permissions.AllowAllPermission"],
    ),
)