def set_created_by(data, request=None):
    """Pre-processing hook that sets the created_by field if not provided"""
    if 'created_by' not in data and request and hasattr(request, 'user') and request.user.is_authenticated:
        data['created_by'] = request.user.username
    elif 'created_by' not in data:
        data['created_by'] = 'system'
    return data

def normalize_email(data, request=None):
    """Pre-processing hook that normalizes email addresses"""
    if 'customer_email' in data:
        data['customer_email'] = data['customer_email'].lower().strip()
    return data

def generate_order_number(data, request=None):
    """Post-processing hook that generates an order number if not provided or if it's a dummy value."""
    from django.utils import timezone
    if 'order_number' not in data or not data['order_number'] or "DUMMY" in data['order_number']:
        # Generate a unique order number based on timestamp
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        data['order_number'] = f"ORD-{timestamp}"
    return data
