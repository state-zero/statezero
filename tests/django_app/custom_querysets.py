from statezero.core.interfaces import AbstractCustomQueryset
from tests.django_app.models import Product, Order

class ActiveProductsQuerySet(AbstractCustomQueryset):
    """Queryset that returns only in-stock products"""
    def get_queryset(self, **kwargs):
        return Product.objects.filter(in_stock=True).order_by('-created_at')

class PricingQuerySet(AbstractCustomQueryset):
    """Queryset that filters products by price range"""
    def get_queryset(self, min_price=0, max_price=None, **kwargs):
        qs = Product.objects.filter(price__gte=min_price)
        if max_price is not None:
            qs = qs.filter(price__lte=max_price)
        return qs.order_by('price')

class RecentOrdersQuerySet(AbstractCustomQueryset):
    """Queryset that returns orders from the last 30 days"""
    def get_queryset(self, days=30, **kwargs):
        from django.utils import timezone
        import datetime
        cutoff_date = timezone.now() - datetime.timedelta(days=days)
        return Order.objects.filter(created_at__gte=cutoff_date).order_by('-created_at')

class OrderStatusQuerySet(AbstractCustomQueryset):
    """Queryset that filters orders by status"""
    def get_queryset(self, status=None, **kwargs):
        if status:
            return Order.objects.filter(status=status).order_by('-created_at')
        return Order.objects.all().order_by('-created_at')