import logging

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.module_loading import import_string

from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.exception_handler import \
    explicit_exception_handler
from statezero.adaptors.django.permissions import ORMBridgeViewAccessGate
from statezero.core.interfaces import AbstractEventEmitter
from statezero.core.process_request import RequestProcessor

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

default_permission = "rest_framework.permissions.AllowAny"
permission_class = import_string(getattr(settings, "STATEZERO_VIEW_ACCESS_CLASS", default_permission))

class EventsAuthView(APIView):
    """
    A generic authentication view for event emitters.
    It uses the broadcast emitter from the event bus to check access and then
    calls its authenticate method with the request.
    """
    permission_classes = [permission_class]
    
    def post(self, request, *args, **kwargs):
        channel_name = request.data.get("channel_name")
        socket_id = request.data.get("socket_id")

        if not channel_name or not socket_id:
            return Response(
                {"error": "Missing channel_name or socket_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract the namespace from the channel name.
        if channel_name.startswith("private-"):
            namespace = channel_name[len("private-"):]
        else:
            namespace = channel_name

        # Retrieve the broadcast emitter from the global event bus.
        if not config.event_bus or not config.event_bus.broadcast_emitter:
            return Response(
                {"error": "Broadcast emitter is not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        event_emitter: AbstractEventEmitter = config.event_bus.broadcast_emitter

        # Use the event emitter's permission check
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

    permission_classes = [permission_class]

    @transaction.atomic
    def post(self, request, model_name):
        processor = RequestProcessor(config=config, registry=registry)
        timeout_ms = getattr(settings, 'STATEZERO_QUERY_TIMEOUT_MS', 1000)
        try:
            with config.context_manager(timeout_ms):
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
    

class BatchView(APIView):
    """
    Process multiple queries in a single atomic transaction.
    
    This endpoint executes multiple operations in a single database transaction,
    ensuring true atomicity - either all operations succeed, or none do.
    """
    
    permission_classes = [ORMBridgeViewAccessGate]
    
    def post(self, request):
        """
        Process a batch of queries within a single atomic transaction.
        
        If any operation fails, the entire transaction is rolled back and error details are returned.
        
        Request format:
        {
            "operations": [
                {
                    "model": "model_name",
                    "query": { ... query AST ... },
                    "id": "operation_id"
                },
                ...
            ]
        }
        
        Success Response format:
        {
            "results": [
                {
                    "id": "operation_id",
                    "data": { ... result data ... },
                    "status": "success"
                },
                ...
            ]
        }
        
        Error Response format:
        {
            "error": "Transaction failed",
            "failed_operation": {
                "id": "operation_id",
                "index": 2,  // index in the operations array
                "model": "model_name"
            },
            "details": { ... error details ... }
        }
        """
        operations = request.data.get("operations", [])
        if not operations:
            return Response(
                {"error": "No operations provided"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Apply a transaction timeout if configured
        timeout_ms = getattr(settings, 'STATEZERO_QUERY_TIMEOUT_MS', 1000)
        
        results = []
        processor = RequestProcessor(config=config, registry=registry)
        
        try:
            # Use transaction.atomic as a context manager
            with transaction.atomic():
                with config.context_manager(timeout_ms):
                    for index, op in enumerate(operations):
                        model_name = op.get("model")
                        query_ast = op.get("query", {})
                        operation_id = op.get("id")
                        
                        if not model_name:
                            # Fail fast with a descriptive error
                            error_response = {
                                "error": "Missing model name",
                                "failed_operation": {
                                    "id": operation_id,
                                    "index": index
                                }
                            }
                            return Response(error_response, status=status.HTTP_400_BAD_REQUEST)
                        
                        try:
                            # Create a custom request object with the operation's query
                            custom_request = type('CustomRequest', (), {})()
                            custom_request.data = {"ast": {"query": query_ast}}
                            custom_request.parser_context = {"kwargs": {"model_name": model_name}}
                            custom_request.user = request.user
                            
                            # Process the request - any exception will be caught below
                            result = processor.process_request(req=custom_request)
                            
                            results.append({
                                "id": operation_id,
                                "data": result,
                                "status": "success"
                            })
                        except Exception as operation_exception:
                            # Capture which operation failed, then re-raise to trigger rollback
                            logger.exception(f"Operation {index} ({operation_id}) failed")
                            
                            # Add context to the exception
                            operation_exception.failed_operation = {
                                "id": operation_id,
                                "index": index,
                                "model": model_name
                            }
                            
                            # Re-raise to ensure transaction rollback
                            raise
        
        except Exception as e:
            # Handle the exception from the transaction
            logger.exception("Transaction failed")
            
            # Get the failed operation details if available
            failed_operation = getattr(e, 'failed_operation', None)
            
            # Create an error response with details about which operation failed
            error_response = {
                "error": str(e),
                "transaction_failed": True
            }
            
            if failed_operation:
                error_response["failed_operation"] = failed_operation
            
            # Use the exception handler to get a properly formatted error response
            error_details = explicit_exception_handler(e)
            if hasattr(error_details, 'data'):
                error_response["details"] = error_details.data
            
            return Response(error_response, status=status.HTTP_400_BAD_REQUEST)
        
        # If we got here, all operations succeeded
        return Response({"results": results}, status=status.HTTP_200_OK)
