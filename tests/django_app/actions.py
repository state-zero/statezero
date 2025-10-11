from statezero.core.actions import action
from statezero.core.interfaces import AbstractActionPermission
from statezero.core.classes import DisplayMetadata, FieldGroup, FieldDisplayConfig
from rest_framework import serializers
from typing import List
from django.utils import timezone
import random
import hashlib


# Serializers
class SendNotificationInputSerializer(serializers.Serializer):
    message = serializers.CharField(
        max_length=500, help_text="Notification message to send"
    )
    recipients = serializers.ListField(
        child=serializers.EmailField(), help_text="List of email addresses to notify"
    )
    priority = serializers.ChoiceField(
        choices=[("low", "Low"), ("high", "High")],
        default="low",
        help_text="Notification priority level",
    )


class SendNotificationResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message_id = serializers.CharField()
    sent_to = serializers.IntegerField()
    queued_at = serializers.DateTimeField()


class ProcessDataInputSerializer(serializers.Serializer):
    data = serializers.ListField(
        child=serializers.IntegerField(), help_text="List of numbers to process"
    )
    operation = serializers.ChoiceField(
        choices=[
            ("sum", "Sum"),
            ("avg", "Average"),
            ("max", "Maximum"),
            ("min", "Minimum"),
        ],
        help_text="Mathematical operation to perform",
    )


class ProcessDataResponseSerializer(serializers.Serializer):
    operation = serializers.CharField()
    result = serializers.FloatField()
    processed_count = serializers.IntegerField()
    execution_time_ms = serializers.IntegerField()


# ADD MISSING SERIALIZERS
class CalculateHashInputSerializer(serializers.Serializer):
    text = serializers.CharField(help_text="Text to hash")
    algorithm = serializers.ChoiceField(
        choices=[("md5", "MD5"), ("sha1", "SHA1"), ("sha256", "SHA256")],
        default="sha256",
        help_text="Hash algorithm to use",
    )


class CalculateHashResponseSerializer(serializers.Serializer):
    original_text = serializers.CharField()
    algorithm = serializers.CharField()
    hash = serializers.CharField()
    text_length = serializers.IntegerField()
    processed_by = serializers.CharField()
    processed_at = serializers.DateTimeField()


class GetServerStatusResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    timestamp = serializers.DateTimeField()
    random_number = serializers.IntegerField()
    server_info = serializers.DictField()
    demo_data = serializers.DictField()


class GetUserInfoResponseSerializer(serializers.Serializer):
    username = serializers.CharField()
    email = serializers.EmailField()
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()
    date_joined = serializers.DateTimeField()
    last_login = serializers.DateTimeField(allow_null=True)
    server_time = serializers.DateTimeField()


class GetUsernameResponseSerializer(serializers.Serializer):
    username = serializers.CharField()
    retrieved_at = serializers.DateTimeField()


# Permissions
class IsAuthenticated(AbstractActionPermission):
    """Simple authentication check"""

    def has_permission(self, request, action_name: str) -> bool:
        return hasattr(request, "user") and request.user.is_authenticated

    def has_action_permission(
        self, request, action_name: str, validated_data: dict
    ) -> bool:
        return True


class CanSendNotifications(AbstractActionPermission):
    """Permission to send notifications"""

    def has_permission(self, request, action_name: str) -> bool:
        return hasattr(request, "user") and request.user.is_authenticated

    def has_action_permission(
        self, request, action_name: str, validated_data: dict
    ) -> bool:
        # Example business rule: limit number of recipients
        recipients = validated_data.get("recipients", [])
        max_recipients = 100 if request.user.is_staff else 10
        return len(recipients) <= max_recipients


class HasValidApiKey(AbstractActionPermission):
    """Example of API key based permission"""

    def has_permission(self, request, action_name: str) -> bool:
        api_key = request.META.get("HTTP_X_API_KEY")
        # Simple mock validation - in real app would check database
        valid_keys = ["demo-key-123", "test-key-456"]
        return api_key in valid_keys

    def has_action_permission(
        self, request, action_name: str, validated_data: dict
    ) -> bool:
        # Example: API key users have different limits based on data
        data_size = len(validated_data.get("data", []))
        return data_size <= 1000  # Limit data processing size


# Actions
@action(
    serializer=SendNotificationInputSerializer,
    response_serializer=SendNotificationResponseSerializer,
    permissions=[CanSendNotifications],
    display=DisplayMetadata(
        display_title="Send Notifications",
        display_description="Send notifications to multiple recipients with priority control",
        field_groups=[
            FieldGroup(
                display_title="Message Content",
                display_description="The notification message and priority level",
                field_names=["message", "priority"]
            ),
            FieldGroup(
                display_title="Recipients",
                display_description="Email addresses to send notifications to",
                field_names=["recipients"]
            )
        ],
        field_display_configs=[
            FieldDisplayConfig(
                field_name="message",
                display_component="TextArea",
                display_help_text="Enter your notification message here (max 500 characters)"
            ),
            FieldDisplayConfig(
                field_name="priority",
                display_component="RadioGroup",
                display_help_text="High priority notifications are processed first"
            ),
            FieldDisplayConfig(
                field_name="recipients",
                display_component="EmailListInput",
                display_help_text="Add one or more email addresses"
            )
        ]
    )
)
def send_notification(
    message: str, recipients: List[str], priority: str = "low", *, request=None
) -> dict:
    """Send notifications to multiple recipients"""

    # Simulate sending notification
    message_id = hashlib.md5(f"{message}{timezone.now()}".encode()).hexdigest()[:12]

    # Mock business logic - would actually send emails/push notifications
    sent_count = len(recipients)

    return {
        "success": True,
        "message_id": f"msg_{message_id}",
        "sent_to": sent_count,
        "queued_at": timezone.now(),
    }


@action(
    serializer=ProcessDataInputSerializer,
    response_serializer=ProcessDataResponseSerializer,
    permissions=[HasValidApiKey],
)
def process_data(data: List[int], operation: str, *, request=None) -> dict:
    """Process a list of numbers with various mathematical operations"""

    start_time = timezone.now()

    # Perform the requested operation
    if operation == "sum":
        result = float(sum(data))
    elif operation == "avg":
        result = float(sum(data) / len(data)) if data else 0.0
    elif operation == "max":
        result = float(max(data)) if data else 0.0
    elif operation == "min":
        result = float(min(data)) if data else 0.0
    else:
        result = 0.0

    # Calculate execution time
    end_time = timezone.now()
    execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

    return {
        "operation": operation,
        "result": result,
        "processed_count": len(data),
        "execution_time_ms": execution_time_ms,
    }


@action(
    permissions=[IsAuthenticated],
    response_serializer=GetUserInfoResponseSerializer,
)
def get_user_info(*, request=None) -> dict:
    """Get current user information (no serializers - simple action)"""

    return {
        "username": request.user.username,
        "email": request.user.email,
        "is_staff": request.user.is_staff,
        "is_superuser": request.user.is_superuser,
        "date_joined": request.user.date_joined,
        "last_login": request.user.last_login,
        "server_time": timezone.now(),
    }


@action(
    permissions=[IsAuthenticated],
    response_serializer=GetUsernameResponseSerializer,
)
def get_current_username(*, request=None) -> dict:
    """Get current user's username - simple focused action"""

    return {
        "username": request.user.username,
        "retrieved_at": timezone.now(),
    }


@action(
    response_serializer=GetServerStatusResponseSerializer,
)
def get_server_status(*, request=None) -> dict:
    """Get server status and random data (no authentication required)"""

    return {
        "status": "healthy",
        "timestamp": timezone.now(),
        "random_number": random.randint(1, 1000),
        "server_info": {
            "django_version": "5.2+",
            "statezero_version": "1.0.0",
            "actions_enabled": True,
        },
        "demo_data": {
            "colors": ["red", "blue", "green", "yellow"],
            "numbers": [random.randint(1, 100) for _ in range(5)],
            "message": "Hello from StateZero Actions!",
        },
    }


@action(
    serializer=CalculateHashInputSerializer,
    response_serializer=CalculateHashResponseSerializer,
    permissions=[IsAuthenticated],
)
def calculate_hash(text: str, algorithm: str = "sha256", *, request=None) -> dict:
    """Calculate hash of input text (demonstrates string processing)"""

    import hashlib

    # Validate algorithm
    available_algorithms = ["md5", "sha1", "sha256"]
    if algorithm not in available_algorithms:
        algorithm = "sha256"

    # Calculate hash
    if algorithm == "md5":
        hash_value = hashlib.md5(text.encode()).hexdigest()
    elif algorithm == "sha1":
        hash_value = hashlib.sha1(text.encode()).hexdigest()
    elif algorithm == "sha256":
        hash_value = hashlib.sha256(text.encode()).hexdigest()

    return {
        "original_text": text,
        "algorithm": algorithm,
        "hash": hash_value,
        "text_length": len(text),
        "processed_by": request.user.get_username(),
        "processed_at": timezone.now(),
    }
