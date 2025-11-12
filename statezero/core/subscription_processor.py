"""
Subscription processor for handling CRUD events and re-executing queries.
"""
import logging
from typing import Any, List

from statezero.core.namespace_utils import should_emit_to_namespace

logger = logging.getLogger(__name__)


def process_model_change(instance: Any, action_type: str, orm_provider, registry) -> None:
    """
    Process a model change event and update affected query subscriptions.

    Args:
        instance: The model instance that changed
        action_type: Type of change (CREATE, UPDATE, DELETE)
        orm_provider: ORM provider to get model name
        registry: StateZero registry object
    """
    from statezero.adaptors.django.models import QuerySubscription

    model_name = orm_provider.get_model_name(instance)
    logger.debug(f"Processing {action_type} event for {model_name} (pk={instance.pk})")

    # Get all subscriptions for this model
    subscriptions = QuerySubscription.objects.filter(model_name=model_name)

    if not subscriptions.exists():
        logger.debug(f"No subscriptions found for {model_name}")
        return

    logger.info(f"Found {subscriptions.count()} subscription(s) for {model_name}")

    # Filter subscriptions to determine which need re-execution
    subscriptions_to_run = []

    for subscription in subscriptions:
        if _should_rerun_subscription(subscription, instance):
            subscriptions_to_run.append(subscription)

    logger.info(f"{len(subscriptions_to_run)} subscription(s) need to be re-executed")
    print(f"[SUBSCRIPTION PROCESSOR] Subscriptions to run: {[s.id for s in subscriptions_to_run]}")

    # TODO: Re-execute queries and broadcast results


def _should_rerun_subscription(subscription, instance: Any) -> bool:
    """
    Determine if a subscription needs to be re-executed based on the instance change.

    Logic:
    1. If last_result is null, always re-run (need initial data)
    2. If instance is already in previous data OR instance passes namespace check, re-run
    3. Otherwise, skip re-execution

    Args:
        subscription: QuerySubscription instance
        instance: The model instance that changed

    Returns:
        True if subscription should be re-executed, False otherwise
    """
    # Rule 1: No previous result, must run to populate
    if subscription.last_result is None:
        logger.debug(f"Subscription {subscription.id}: No last_result, needs re-execution")
        return True

    # Check if instance is in previous results
    instance_in_previous = _instance_in_result(instance, subscription.last_result)

    # Check if instance passes namespace filter
    instance_matches_namespace = _instance_matches_namespace(instance, subscription.namespace)

    # Rule 2: If instance is in previous data OR matches namespace, re-run
    if instance_in_previous or instance_matches_namespace:
        logger.debug(
            f"Subscription {subscription.id}: Instance in previous={instance_in_previous}, "
            f"matches namespace={instance_matches_namespace}, needs re-execution"
        )
        return True

    # Rule 3: Instance not relevant to this subscription
    logger.debug(f"Subscription {subscription.id}: Instance not relevant, skipping")
    return False


def _instance_in_result(instance: Any, result: dict) -> bool:
    """
    Check if an instance appears in the cached query result.

    Args:
        instance: The model instance
        result: The cached query result (with 'detail' key containing instance data)

    Returns:
        True if instance is in result, False otherwise
    """
    if not result or "detail" not in result:
        return False

    instance_pk = instance.pk
    detail = result["detail"]

    # detail is a dict where keys are PKs (could be int or str due to JSON serialization)
    # Check both string and integer versions of the PK
    return str(instance_pk) in detail or instance_pk in detail


def _instance_matches_namespace(instance: Any, namespace: dict) -> bool:
    """
    Check if an instance matches the subscription's namespace filter.

    Args:
        instance: The model instance
        namespace: The namespace filter dict

    Returns:
        True if instance matches namespace, False otherwise
    """
    # Empty namespace means match all
    if not namespace:
        return True

    return should_emit_to_namespace(instance, namespace)
