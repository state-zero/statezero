import uuid

from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone
from djmoney.models.fields import MoneyField
from django.contrib.auth import get_user_model
from django.db.models import Max

from simple_history.models import HistoricalRecords

User = get_user_model()

class DummyRelatedModel(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return f"Related: {self.name}"

    def __img__(self):
        return f"/img/related/{self.name}.png"

    class Meta:
        app_label = "django_app"


class DummyModel(models.Model):
    name = models.CharField(max_length=50)
    value = models.IntegerField(default=0, null=True, blank=True)
    related = models.ForeignKey(
        DummyRelatedModel,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="dummy_models",
    )

    def __str__(self):
        return f"DummyModel {self.name}"

    def __img__(self):
        return f"/img/{self.name}.png"

    @property
    def computed(self) -> str:
        return "computed"

    class Meta:
        app_label = "django_app"


class DeepModelLevel3(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"Level3: {self.name}"

    def __img__(self):
        return f"/img/deep/level3_{self.name}.png"

    class Meta:
        app_label = "django_app"


class DeepModelLevel2(models.Model):
    name = models.CharField(max_length=100)
    level3 = models.ForeignKey(
        DeepModelLevel3, on_delete=models.CASCADE, related_name="level2s"
    )

    def __str__(self):
        return f"Level2: {self.name}"

    def __img__(self):
        return f"/img/deep/level2_{self.name}.png"

    class Meta:
        app_label = "django_app"


class DeepModelLevel1(models.Model):
    name = models.CharField(max_length=100)
    level2 = models.ForeignKey(
        DeepModelLevel2, on_delete=models.CASCADE, related_name="level1s"
    )
    # Add a many-to-many field to DummyModel.
    comprehensive_models = models.ManyToManyField(
        "django_app.ComprehensiveModel", blank=True, related_name="deep_models"
    )

    def __str__(self):
        return f"Level1: {self.name}"

    def __img__(self):
        return f"/img/deep/level1_{self.name}.png"

    class Meta:
        app_label = "django_app"


class ComprehensiveModel(models.Model):
    char_field = models.CharField(max_length=100)
    text_field = models.TextField()
    int_field = models.IntegerField()
    bool_field = models.BooleanField(default=True)
    datetime_field = models.DateTimeField(default=timezone.now)
    decimal_field = models.DecimalField(max_digits=10, decimal_places=2)
    json_field = models.JSONField(default=dict)
    money_field = MoneyField(
        max_digits=10, decimal_places=2, default_currency="USD", default=0
    )
    nullable_money_field = MoneyField(
        max_digits=10, decimal_places=2, default_currency="USD", null=True, blank=True
    )
    related = models.ForeignKey(
        "django_app.DeepModelLevel1", on_delete=models.CASCADE, null=True, blank=True
    )

    def __str__(self):
        return f"ComprehensiveModel: {self.char_field}"

    def __img__(self):
        return f"/img/{self.char_field}.png"

    class Meta:
        app_label = "django_app"


class CustomPKModel(models.Model):
    # Use an IntegerField as the primary key and allow it to be edited.
    custom_pk = models.IntegerField(primary_key=True, editable=True, blank=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"CustomPK: {self.name}"

    def __img__(self):
        return f"/img/custom_pk_{self.name}.png"

    class Meta:
        app_label = "django_app"

    def save(self, *args, **kwargs):
        # If no primary key is provided, auto-increment by taking the max existing pk and adding one.
        if self.custom_pk is None:
            max_pk = CustomPKModel.objects.aggregate(Max('custom_pk'))['custom_pk__max'] or 0
            self.custom_pk = max_pk + 1
        super().save(*args, **kwargs)

class ModelWithCustomPKRelation(models.Model):
    name = models.CharField(max_length=100)
    # Relation to a model with custom PK
    custom_pk_related = models.ForeignKey(
        CustomPKModel, on_delete=models.CASCADE, related_name="linked_models"
    )

    def __str__(self):
        return f"RelatesTo: {self.name}"

    def __img__(self):
        return f"/img/relates_to_{self.name}.png"

    class Meta:
        app_label = "django_app"


class NameFilterCustomPKModel(models.Model):
    # Custom primary key field
    custom_pk = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"NameFilterCustomPKModel: {self.name}"

    def __img__(self):
        return f"/img/namefilter_custom_{self.name}.png"

    class Meta:
        app_label = "django_app"

class ProductCategory(models.Model):
    name = models.CharField(max_length=100)
    
    def __str__(self):
        return self.name
    
    def __img__(self):
        return f"/img/category/{self.name}.png"
    
    class Meta:
        app_label = "django_app"


class Product(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.ForeignKey(ProductCategory, on_delete=models.CASCADE, related_name="products")
    in_stock = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    
    def __str__(self):
        return self.name
    
    def __img__(self):
        return f"/img/product/{self.name}.png"
    
    # Additional computed property for testing
    @property
    def price_with_tax(self):
        """Calculate price with 20% tax"""
        return float(self.price) * 1.2
    
    @property
    def display_name(self):
        """Format display name with category"""
        return f"{self.name} ({self.category.name})"
    
    class Meta:
        app_label = "django_app"
        
class FileTest(models.Model):
    """Test model for file upload testing"""
    title = models.CharField(max_length=100)
    document = models.FileField(upload_to='test_documents/', blank=True, null=True)
    image = models.ImageField(upload_to='test_images/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.title

    class Meta:
        app_label = "django_app"

class Order(models.Model):
    order_number = models.CharField(max_length=20, unique=True)
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField()
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled')
    ], default='pending')
    created_at = models.DateTimeField(default=timezone.now)
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Order {self.order_number}"
    
    def __img__(self):
        return f"/img/order/{self.order_number}.png"
    
    class Meta:
        app_label = "django_app"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"

    @property
    def subtotal(self):
        return float(self.price) * self.quantity

    class Meta:
        app_label = "django_app"


class RatePlan(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

    class Meta:
        app_label = "django_app"


class DailyRate(models.Model):
    rate_plan = models.ForeignKey(RatePlan, on_delete=models.CASCADE, related_name="daily_rates")
    date = models.DateField()
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    min_stay_arrival = models.IntegerField(null=True, blank=True)
    min_stay_through = models.IntegerField(null=True, blank=True)
    max_stay = models.IntegerField(null=True, blank=True)
    closed_to_arrival = models.BooleanField(default=False)
    closed_to_departure = models.BooleanField(default=False)
    stop_sell = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.rate_plan.name} - {self.date}"

    class Meta:
        app_label = "django_app"
        indexes = [
            models.Index(fields=["rate_plan", "date"]),
            models.Index(fields=["date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["rate_plan", "date"],
                name="unique_rate_plan_date"
            )
        ]


class RestrictedFieldRelatedModel(models.Model):
    """Related model for testing field-level permissions on nested filter fields."""
    name = models.CharField(max_length=100)
    # Field hidden from ALL users (not in ModelConfig.fields)
    internal_code = models.CharField(max_length=100, default='internal')
    # Field hidden from non-admin users only (via visible_fields permission)
    admin_only_field = models.CharField(max_length=100, default='')

    def __str__(self):
        return f"RestrictedRelated: {self.name}"

    def __img__(self):
        return f"/img/restricted_related_{self.name}.png"

    class Meta:
        app_label = "django_app"


class ModelWithRestrictedFields(models.Model):
    """Model for testing field-level read permissions on filter fields."""
    name = models.CharField(max_length=100)
    # Field hidden from ALL users (not in ModelConfig.fields)
    internal_code = models.CharField(max_length=100, default='internal')
    # Field hidden from non-admin users only (via visible_fields permission)
    admin_only_field = models.CharField(max_length=100, default='')
    # Relation to test nested field restrictions
    restricted_related = models.ForeignKey(
        RestrictedFieldRelatedModel,
        on_delete=models.CASCADE,
        related_name="restricted_models",
        null=True,
        blank=True
    )

    def __str__(self):
        return f"RestrictedModel: {self.name}"

    def __img__(self):
        return f"/img/restricted_{self.name}.png"

    class Meta:
        app_label = "django_app"


# Models for testing deep M2M nesting (M2M -> M2M -> FK)
class M2MDepthTestLevel3(models.Model):
    """Deepest level - has a field and FK for testing M2M -> M2M -> FK traversal"""
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    # FK to test M2M -> M2M -> FK -> field
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="m2m_depth_level3s"
    )

    def __str__(self):
        return f"M2MDepthLevel3: {self.name}"

    class Meta:
        app_label = "django_app"


class M2MDepthTestLevel2(models.Model):
    """Middle level - has M2M to Level3"""
    name = models.CharField(max_length=100)
    level3s = models.ManyToManyField(
        M2MDepthTestLevel3,
        blank=True,
        related_name="level2s"
    )

    def __str__(self):
        return f"M2MDepthLevel2: {self.name}"

    class Meta:
        app_label = "django_app"


class M2MDepthTestLevel1(models.Model):
    """Top level - has M2M to Level2, enabling M2M -> M2M -> field queries"""
    name = models.CharField(max_length=100)
    level2s = models.ManyToManyField(
        M2MDepthTestLevel2,
        blank=True,
        related_name="level1s"
    )

    def __str__(self):
        return f"M2MDepthLevel1: {self.name}"

    class Meta:
        app_label = "django_app"


class HistoryTestModel(models.Model):
    """Model for testing django-simple-history integration with StateZero."""
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    history = HistoricalRecords()

    def __str__(self):
        return f"HistoryTestModel: {self.name}"

    class Meta:
        app_label = "django_app"


# =============================================================================
# Parity Test Models (AllowAll, exhaustive field types)
# =============================================================================

class Author(models.Model):
    name = models.CharField(max_length=100)
    bio = models.TextField(blank=True, default="")
    age = models.IntegerField(null=True, blank=True)
    rating = models.FloatField(default=0.0)
    salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    birth_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    email = models.EmailField(blank=True, default="")
    website = models.URLField(blank=True, default="")
    slug = models.SlugField(blank=True, default="")
    uuid = models.UUIDField(default=uuid.uuid4, editable=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"Author: {self.name}"

    class Meta:
        app_label = "django_app"


class Book(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    pages = models.IntegerField(null=True, blank=True)
    weight = models.FloatField(null=True, blank=True)
    is_published = models.BooleanField(default=False)
    publish_date = models.DateField(null=True, blank=True)
    last_updated = models.DateTimeField(null=True, blank=True)
    isbn = models.CharField(max_length=13, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    author = models.ForeignKey(
        Author, null=True, blank=True, on_delete=models.CASCADE, related_name="books"
    )

    def __str__(self):
        return f"Book: {self.title}"

    class Meta:
        app_label = "django_app"


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(null=True, blank=True)
    is_featured = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    cost = MoneyField(max_digits=10, decimal_places=2, default_currency="USD", default=0)
    books = models.ManyToManyField(Book, blank=True, related_name="tags")

    def __str__(self):
        return f"Tag: {self.name}"

    class Meta:
        app_label = "django_app"


# =============================================================================
# Security Test Models (one model per permission scenario)
# =============================================================================

class ReadOnlyItem(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    secret = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"ReadOnlyItem: {self.name}"

    class Meta:
        app_label = "django_app"


class NoDeleteItem(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    secret = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"NoDeleteItem: {self.name}"

    class Meta:
        app_label = "django_app"


class HFParent(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    secret = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"HFParent: {self.name}"

    class Meta:
        app_label = "django_app"


class HFChild(models.Model):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        HFParent, on_delete=models.CASCADE, related_name="children"
    )

    def __str__(self):
        return f"HFChild: {self.name}"

    class Meta:
        app_label = "django_app"


class RowFilteredItem(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    secret = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"RowFilteredItem: {self.name}"

    class Meta:
        app_label = "django_app"


class RestrictedCreateItem(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    secret = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"RestrictedCreateItem: {self.name}"

    class Meta:
        app_label = "django_app"


class RestrictedEditItem(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    secret = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"RestrictedEditItem: {self.name}"

    class Meta:
        app_label = "django_app"


class ExcludedItem(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    secret = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"ExcludedItem: {self.name}"

    class Meta:
        app_label = "django_app"


class ObjectLevelItem(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    owner = models.CharField(max_length=100)

    def __str__(self):
        return f"ObjectLevelItem: {self.name}"

    class Meta:
        app_label = "django_app"


class ComposedItem(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)
    secret = models.CharField(max_length=100, blank=True, default="")
    owner = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"ComposedItem: {self.name}"

    class Meta:
        app_label = "django_app"


# =============================================================================
# Error Handling Test Models
# =============================================================================

class ErrorTestParent(models.Model):
    """Parent model with a PROTECT FK child to test ProtectedError on delete."""
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"ErrorTestParent: {self.name}"

    class Meta:
        app_label = "django_app"


class ErrorTestProtectedChild(models.Model):
    """Child with PROTECT FK — deleting the parent should raise ProtectedError."""
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        ErrorTestParent, on_delete=models.PROTECT, related_name="protected_children"
    )

    def __str__(self):
        return f"ErrorTestProtectedChild: {self.name}"

    class Meta:
        app_label = "django_app"


class ErrorTestUniqueModel(models.Model):
    """Model with a unique field to test IntegrityError on duplicate."""
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=100)

    def __str__(self):
        return f"ErrorTestUniqueModel: {self.code}"

    class Meta:
        app_label = "django_app"


class ErrorTestOneToOneModel(models.Model):
    """OneToOne to ErrorTestParent — assigning the same parent twice should raise IntegrityError."""
    parent = models.OneToOneField(
        ErrorTestParent, on_delete=models.CASCADE, related_name="one_to_one_child"
    )
    note = models.CharField(max_length=200, blank=True, default="")

    def __str__(self):
        return f"ErrorTestOneToOne for {self.parent}"

    class Meta:
        app_label = "django_app"


class ErrorTestCompoundUnique(models.Model):
    """Model with a compound unique constraint."""
    group = models.CharField(max_length=50)
    rank = models.IntegerField()
    label = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"ErrorTestCompoundUnique: {self.group}/{self.rank}"

    class Meta:
        app_label = "django_app"
        constraints = [
            models.UniqueConstraint(
                fields=["group", "rank"],
                name="unique_group_rank"
            )
        ]
