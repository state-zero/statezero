from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()

class QuerySubscription(models.Model):
    """
    Tracks active query subscriptions for the polling/push-based system.

    Each subscription represents a unique query (identified by hashed_cache_key) that
    clients are subscribed to via Pusher. This allows the server to:
    1. Know which queries have active subscribers
    2. Push updates only to queries that are being watched
    3. Track the last result for efficient diffing
    """

    # Hashed cache key for this query (SHA256 hash of SQL + txn_id + operation_context)
    # This is the hash portion only, without the "statezero:query:" prefix
    hashed_cache_key = models.CharField(max_length=64, unique=True, db_index=True)

    # Model name this subscription is for
    model_name = models.CharField(max_length=255, db_index=True, default="unknown")

    # The original AST that generates this query (for re-execution)
    ast = models.JSONField(help_text="The AST that generates this query")

    # Namespace extracted from the query filter (for event filtering)
    # Contains only simple equality and __in filters from the AST
    namespace = models.JSONField(
        default=dict,
        help_text="Namespace filters for determining when to re-execute this query"
    )

    # The last result that was sent to subscribers (for diffing)
    last_result = models.JSONField(null=True, blank=True, help_text="Last cached result")

    # Authenticated users subscribed to this query
    users = models.ManyToManyField(
        User,
        related_name='query_subscriptions',
        blank=True,
        help_text="Authenticated users subscribed to this query"
    )

    # Flag to indicate if anonymous users are allowed/subscribed
    anonymous_users_allowed = models.BooleanField(
        default=False,
        help_text="Whether anonymous users can subscribe to this query"
    )

    class Meta:
        db_table = 'statezero_query_subscription'
        indexes = [
            models.Index(fields=['hashed_cache_key']),
        ]

    def __str__(self):
        user_count = self.users.count()
        anon_status = " + anon" if self.anonymous_users_allowed else ""
        return f"Subscription {self.hashed_cache_key[:16]}... ({user_count} users{anon_status})"

    @property
    def full_cache_key(self) -> str:
        """Get the full cache key with prefix."""
        return f"statezero:query:{self.hashed_cache_key}"

    def has_subscribers(self) -> bool:
        """Check if this subscription has any active subscribers."""
        return self.users.exists() or self.anonymous_users_allowed
