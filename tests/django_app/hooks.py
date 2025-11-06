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
    import uuid
    if 'order_number' not in data or not data['order_number'] or "DUMMY" in data['order_number']:
        # Generate a unique order number using UUID
        unique_id = str(uuid.uuid4())[:8]  # Use first 8 chars of UUID for brevity
        data['order_number'] = f"ORD-{unique_id}"
    return data
