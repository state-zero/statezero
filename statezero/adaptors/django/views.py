import logging

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers
from rest_framework.parsers import MultiPartParser
from django.core.files.storage import storages
from django.utils.module_loading import import_string
from datetime import datetime
from django.conf import settings
from django.core.files.storage import default_storage
import math
import mimetypes

from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.exception_handler import \
    explicit_exception_handler
from statezero.adaptors.django.permissions import ORMBridgeViewAccessGate
from statezero.adaptors.django.actions import DjangoActionSchemaGenerator
from statezero.core.interfaces import AbstractEventEmitter
from statezero.core.process_request import RequestProcessor
from statezero.core.actions import action_registry
from statezero.core.interfaces import AbstractActionPermission

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

default_permission = "rest_framework.permissions.AllowAny"
permission_class = import_string(getattr(settings, "STATEZERO_VIEW_ACCESS_CLASS", default_permission))
default_storage = default_storage = storages[getattr(settings, 'STATEZERO_STORAGE_KEY', 'default')]

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

class FileUploadView(APIView):
    """Standard file upload - returns permanent URL"""
    parser_classes = [MultiPartParser]
    permission_classes = [permission_class]
    
    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'No file provided'}, status=400)
        
        upload_dir = getattr(settings, 'STATEZERO_UPLOAD_DIR', 'statezero')
        full_path = f"{upload_dir}/{file.name}"
        
        file_path = default_storage.save(full_path, file)
        file_url = default_storage.url(file_path)
        
        response_data = {
            'file_path': file_path,
            'file_url': file_url,
            'original_name': file.name,
            'size': file.size
        }
        
        # Execute callbacks
        self._execute_callbacks(request, file, file_path, response_data)
        
        return Response(response_data)
    
    def _execute_callbacks(self, request, uploaded_file, file_path, response_data):
        """Execute configured file upload callbacks"""
        if config.file_upload_callbacks:
            for callback_path in config.file_upload_callbacks:
                try:
                    callback = import_string(callback_path)
                    callback(
                        request=request,
                        uploaded_file=uploaded_file,
                        file_path=file_path,
                        response_data=response_data
                    )
                except Exception as e:
                    logger.error(f"File upload callback failed: {e}")

class FastUploadView(APIView):
    """Fast upload with S3 presigned URLs - single or multipart based on chunks"""
    permission_classes = [permission_class]

    def post(self, request):
        action = request.data.get('action', 'initiate')

        if action == 'initiate':
            return self._initiate_upload(request)
        elif action == 'complete':
            return self._complete_upload(request)
        else:
            return Response({'error': 'Invalid action'}, status=400)

    def _initiate_upload(self, request):
        """Generate presigned URLs - single or multipart based on num_chunks"""
        filename = request.data.get('filename')
        content_type = request.data.get('content_type')
        file_size = request.data.get('file_size', 0)
        num_chunks_str = request.data.get('num_chunks', 1)  # Client decides chunking
        num_chunks = int(num_chunks_str)

        if not filename:
            return Response({'error': 'filename required'}, status=400)

        # Generate file path
        upload_dir = getattr(settings, 'STATEZERO_UPLOAD_DIR', 'statezero')
        file_path = f"{upload_dir}/{filename}"

        if not content_type:
            content_type, _ = mimetypes.guess_type(filename)
            content_type = content_type or 'application/octet-stream'

        if not self._is_s3_storage():
            return Response({'error': 'Fast upload requires S3 storage backend'}, status=400)

        try:
            s3_client = self._get_s3_client()

            if num_chunks == 1:
                # Single upload (existing logic)
                presigned_url = s3_client.generate_presigned_url(
                    ClientMethod='put_object',
                    Params={
                        'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                        'Key': file_path,
                        'ContentType': content_type,
                    },
                    ExpiresIn=3600,
                    HttpMethod='PUT',
                )

                return Response({
                    'upload_type': 'single',
                    'upload_url': presigned_url,
                    'file_path': file_path,
                    'content_type': content_type
                })

            else:
                # Multipart upload
                if num_chunks > 10000:
                    return Response({'error': 'Too many chunks (max 10,000)'}, status=400)

                # Initiate multipart upload
                response = s3_client.create_multipart_upload(
                    Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                    Key=file_path,
                    ContentType=content_type
                )

                upload_id = response['UploadId']

                # Generate presigned URLs for all parts
                upload_urls = {}
                for part_number in range(1, num_chunks + 1):
                    url = s3_client.generate_presigned_url(
                        ClientMethod='upload_part',
                        Params={
                            'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                            'Key': file_path,
                            'PartNumber': part_number,
                            'UploadId': upload_id,
                        },
                        ExpiresIn=3600,
                        HttpMethod='PUT'
                    )
                    upload_urls[part_number] = url

                return Response({
                    'upload_type': 'multipart',
                    'upload_id': upload_id,
                    'upload_urls': upload_urls,  # All URLs at once
                    'file_path': file_path,
                    'content_type': content_type
                })

        except Exception as e:
            logger.error(f"Upload initiation failed: {e}")
            return Response({'error': 'Upload unavailable'}, status=500)

    def _complete_upload(self, request):
        """Complete upload - single or multipart"""
        file_path = request.data.get('file_path')
        original_name = request.data.get('original_name')
        upload_id = request.data.get('upload_id')  # Only present for multipart
        parts = request.data.get('parts', [])  # Only present for multipart

        if not file_path:
            return Response({'error': 'file_path required'}, status=400)

        try:
            if upload_id and parts:
                # Complete multipart upload
                s3_client = self._get_s3_client()

                # Sort parts by PartNumber to ensure correct order
                sorted_parts = sorted(parts, key=lambda x: x['PartNumber'])

                response = s3_client.complete_multipart_upload(
                    Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                    Key=file_path,
                    UploadId=upload_id,
                    MultipartUpload={'Parts': sorted_parts}
                )

                logger.info(f"Multipart upload completed for {file_path}")

            # For single uploads, file is already there after PUT
            # For multipart, it's now assembled

            if not default_storage.exists(file_path):
                return Response({'error': 'File not found'}, status=404)

            return Response({
                'file_path': file_path,
                'file_url': default_storage.url(file_path),
                'original_name': original_name,
                'size': default_storage.size(file_path)
            })

        except Exception as e:
            logger.error(f"Upload completion failed: {e}")
            # Clean up failed multipart upload
            if upload_id:
                try:
                    s3_client = self._get_s3_client()
                    s3_client.abort_multipart_upload(
                        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                        Key=file_path,
                        UploadId=upload_id
                    )
                    logger.info(f"Aborted failed multipart upload {upload_id}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to abort multipart upload: {cleanup_error}")
            return Response({'error': 'Upload completion failed'}, status=500)

    def _get_s3_client(self):
        """Get S3 client"""
        import boto3
        return boto3.client(
            "s3",
            region_name=settings.AWS_S3_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=getattr(settings, 'AWS_S3_ENDPOINT_URL', None)
        )

    def _is_s3_storage(self) -> bool:
        """Check if using S3-compatible storage"""
        try:
            from storages.backends.s3boto3 import S3Boto3Storage
            from storages.backends.s3 import S3Storage
        except ImportError:
            return False
        return isinstance(default_storage, (S3Boto3Storage, S3Storage))


class ActionView(APIView):
    """Django view to handle StateZero action execution"""

    def post(self, request, action_name):
        """Execute a registered action"""
        action_config = action_registry.get_action(action_name)

        if not action_config:
            return Response(
                {"error": f"Action '{action_name}' not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check permissions
        if not self._check_permissions(request, action_config, action_name):
            return Response(
                {"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN
            )

        # Validate input if serializer provided
        validated_data = {}
        if action_config["serializer"]:
            serializer = action_config["serializer"](
                data=request.data, context={"request": request}
            )
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            validated_data = serializer.validated_data
        else:
            # No input serializer - pass raw data
            validated_data = request.data

        # Check action-level permissions (after validation)
        if not self._check_action_permissions(
            request, action_config, action_name, validated_data
        ):
            return Response(
                {"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            # Execute the action function
            action_func = action_config["function"]
            result = action_func(**validated_data, request=request)

            # Validate response if response_serializer provided
            if action_config["response_serializer"]:
                response_serializer = action_config["response_serializer"](data=result)
                if not response_serializer.is_valid():
                    return Response(
                        {
                            "error": f"Action returned invalid response: {response_serializer.errors}"
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
                return Response(response_serializer.validated_data)
            else:
                # No response serializer - return raw result
                return Response(result)

        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _check_permissions(self, request, action_config, action_name) -> bool:
        """Check view-level permissions (before validation)"""
        permissions = action_config.get("permissions", [])

        for permission_class in permissions:
            permission_instance = permission_class()
            if not permission_instance.has_permission(request, action_name):
                return False

        return True

    def _check_action_permissions(
        self, request, action_config, action_name, validated_data
    ) -> bool:
        """Check action-level permissions (after validation)"""
        permissions = action_config.get("permissions", [])

        for permission_class in permissions:
            permission_instance = permission_class()
            if not permission_instance.has_action_permission(
                request, action_name, validated_data
            ):
                return False

        return True


class ActionSchemaView(APIView):
    """Django view to provide action schema information for frontend generation"""

    def get(self, request):
        """Return schema information for all registered actions"""
        return DjangoActionSchemaGenerator.generate_actions_schema()
