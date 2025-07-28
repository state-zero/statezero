from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone
from djmoney.models.fields import MoneyField
from django.contrib.auth import get_user_model
from django.db.models import Max

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
    value = models.IntegerField(default=0)
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