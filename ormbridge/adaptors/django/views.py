import logging

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ormbridge.adaptors.django.config import config, registry
from ormbridge.adaptors.django.exception_handler import \
    explicit_exception_handler
from ormbridge.adaptors.django.permissions import ORMBridgeViewAccessGate
from ormbridge.core.exceptions import ORMBridgeError
from ormbridge.core.interfaces import AbstractEventEmitter
from ormbridge.core.process_request import RequestProcessor

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class EventsAuthView(APIView):
    """
    A generic authentication view for event emitters.
    It uses the broadcast emitter from the event bus to check access and then
    calls its authenticate method with the request.
    """
    permission_classes = ['rest_framework.permissions.AllowAny']
    
    def post(self, request, *args, **kwargs):
        channel_name = request.data.get("channel_name")
        socket_id = request.data.get("socket_id")

        if not channel_name or not socket_id:
            return Response(
                {"error": "Missing channel_name or socket_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract the namespace from the channel name.
        # Assumes channel_name is prefixed with "private-"
        if channel_name.startswith("private-"):
            namespace = channel_name[len("private-") :]
        else:
            namespace = channel_name

        # Retrieve the broadcast emitter from the global event bus.
        if not config.event_bus or not config.event_bus.broadcast_emitter:
            return Response(
                {"error": "Broadcast emitter is not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        event_emitter: AbstractEventEmitter = config.event_bus.broadcast_emitter

        # Use the event emitter's permission check.
        if not event_emitter.has_permission(request, namespace):
            return Response(
                {"error": "Permission denied for accessing channel."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Delegate authentication to the event emitter.
        response = event_emitter.authenticate(request)
        logger.debug(f"Authentication successful for channel: {channel_name}")
        return Response(response, status=status.HTTP_200_OK)


class ModelListView(APIView):
    """
    Returns a list of registered model names.
    """

    permission_classes = [ORMBridgeViewAccessGate]

    def get(self, request, *args, **kwargs):
        model_names = []
        for model in registry._models_config.keys():
            model_name = config.orm_provider.get_model_name(model)
            model_names.append(model_name)
        return Response(model_names, status=status.HTTP_200_OK)


class ModelView(APIView):

    permission_classes = ['rest_framework.permissions.AllowAny']

    @transaction.atomic
    def post(self, request, model_name):
        processor = RequestProcessor(config=config, registry=registry)
        try:
            result = processor.process_request(req=request)
        except Exception as original_exception:
            return explicit_exception_handler(original_exception)
        return Response(result, status=status.HTTP_200_OK)


class SchemaView(APIView):
    permission_classes = [ORMBridgeViewAccessGate]

    def get(self, request, model_name):
        processor = RequestProcessor(config=config, registry=registry)
        try:
            result = processor.process_schema(req=request)
        except Exception as original_exception:
            return explicit_exception_handler(original_exception)
        return Response(result, status=status.HTTP_200_OK)
