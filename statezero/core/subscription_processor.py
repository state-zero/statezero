"""
Subscription processor for handling CRUD events and re-executing queries.
"""
import logging
from typing import Any, List, Union

from statezero.core.namespace_utils import instance_matches_namespace_filter

logger = logging.getLogger(__name__)


def process_model_change(instances: Union[Any, List[Any]], action_type: str, orm_provider, registry) -> None:
    """
    Process a model change event and update affected query subscriptions.

    Args:
        instances: The model instance(s) that changed (single instance or list)
        action_type: Type of change (CREATE, UPDATE, DELETE)
        orm_provider: ORM provider to get model name
        registry: StateZero registry object
    """
    from statezero.adaptors.django.models import QuerySubscription

    # Normalize to list
    if not isinstance(instances, list):
        instances = [instances]

    if not instances:
        return

    # Get model name from first instance
    first_instance = instances[0]
    model_name = orm_provider.get_model_name(first_instance)
    logger.debug(f"Processing {action_type} event for {model_name} ({len(instances)} instance(s))")

    # Get all subscriptions for this model
    # For read queries: check pk_index (contains models from results including joins)
    # For aggregate queries: check model_name (aggregates don't have pk_index populated)
    # Exclude subscriptions already marked as needing rerun (avoid redundant processing)
    from django.db.models import Q
    subscriptions = QuerySubscription.objects.filter(
        Q(pk_index__has_key=model_name) | Q(model_name=model_name),
        needs_rerun=False
    )

    if not subscriptions.exists():
        logger.debug(f"No subscriptions found for {model_name} (or all already marked dirty)")
        return

    logger.info(f"Found {subscriptions.count()} subscription(s) for {model_name}")

    # Filter subscriptions to determine which need re-execution
    subscriptions_to_mark = []

    for subscription in subscriptions:
        if _should_rerun_subscription(subscription, instances, orm_provider):
            subscriptions_to_mark.append(subscription.id)

    if subscriptions_to_mark:
        # Mark all affected subscriptions as needing rerun in a single query
        QuerySubscription.objects.filter(id__in=subscriptions_to_mark).update(needs_rerun=True)
        logger.info(f"Marked {len(subscriptions_to_mark)} subscription(s) as needing rerun")

def _should_rerun_subscription(subscription, instances: List[Any], orm_provider) -> bool:
    """
    Determine if a subscription needs to be re-executed based on the instance changes.

    Logic:
    1. If last_result is null, always re-run (need initial data)
    2. If query_type is "aggregate", always re-run (any change affects aggregates)
    3. If query_type is "read":
       - Extract PK set from previous results once
       - If ANY instance PK is in PK set OR passes namespace check, re-run
       - Otherwise, skip

    Args:
        subscription: QuerySubscription instance
        instances: List of model instances that changed

    Returns:
        True if subscription should be re-executed, False otherwise
    """
    # Rule 1: No previous result, must run to populate
    if subscription.last_result is None:
        logger.debug(f"Subscription {subscription.id}: No last_result, needs re-execution")
        return True

    # Rule 2: Aggregates always need re-execution (any change affects count/sum/etc)
    if subscription.query_type == "aggregate":
        logger.debug(f"Subscription {subscription.id}: Aggregate query, needs re-execution")
        return True

    # Rule 3: For read queries, check if ANY instance is relevant
    # Use optimized pk_index for fast lookups
    pk_index = subscription.pk_index or {}

    # Get the model name from the first instance
    model_name = orm_provider.get_model_name(instances[0])
    pk_set = set(pk_index.get(model_name, []))

    for instance in instances:
        instance_pk = instance.pk

        # Check if instance PK is in pk_index (O(1) set lookup)
        instance_in_previous = str(instance_pk) in pk_set or instance_pk in pk_set

        # Check if instance passes namespace filter (empty namespace means match all)
        instance_matches_namespace = not subscription.namespace or instance_matches_namespace_filter(instance, subscription.namespace)

        # Can only skip if instance is NOT in previous PKs AND NOT in namespace
        # Otherwise, we need to rerun
        can_skip = not instance_in_previous and not instance_matches_namespace

        if not can_skip:
            logger.debug(
                f"Subscription {subscription.id}: Instance pk={instance_pk} in previous={instance_in_previous}, "
                f"matches namespace={instance_matches_namespace}, needs re-execution"
            )
            return True

    # All instances were skippable (not in previous PKs and not in namespace)
    logger.debug(f"Subscription {subscription.id}: No instances relevant, skipping")
    return False
