import logging
import traceback

from django.conf import settings
from django.core.exceptions import \
    MultipleObjectsReturned as DjangoMultipleObjectsReturned
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
# Import Django/DRF exceptions.
from django.db.models import Model
from django.http import Http404
from fastapi.encoders import jsonable_encoder  # Requires fastapi dependency
from rest_framework import status
from rest_framework.exceptions import NotFound as DRFNotFound
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

# Import your custom StateZero exception types.
from statezero.core.exceptions import (ErrorDetail, StateZeroError,
                                       MultipleObjectsReturned, NotFound,
                                       PermissionDenied, ValidationError)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def map_exception(exc):
    """
    Map Django/DRF exceptions to your library’s errors.
    If the exception is already one of your library's types, return it as is.
    """
    logger.debug("Mapping exception type: %s", type(exc))

    if isinstance(exc, StateZeroError):
        return exc

    if isinstance(exc, type) and issubclass(exc, Model.DoesNotExist):
        return NotFound(detail=str(exc))

    if isinstance(exc, DjangoMultipleObjectsReturned):
        return MultipleObjectsReturned(detail=str(exc))
    if isinstance(exc, (ObjectDoesNotExist, Http404)):
        return NotFound(detail=str(exc))
    if isinstance(exc, DjangoValidationError):
        detail = getattr(exc, "message_dict", getattr(exc, "messages", str(exc)))
        return ValidationError(detail=detail)
    if isinstance(exc, DjangoPermissionDenied):
        return PermissionDenied(detail=str(exc))

    if isinstance(exc, DRFValidationError):
        return ValidationError(detail=exc.detail)
    if isinstance(exc, DRFNotFound):
        return NotFound(detail=str(exc))
    if isinstance(exc, DRFPermissionDenied):
        return PermissionDenied(detail=str(exc))

    return exc


def explicit_exception_handler(exc):
    """
    Extended explicit exception handler that builds a structured JSON response.
    It maps known Django/DRF exceptions to StateZero's standard errors and
    uses jsonable_encoder to ensure the output is JSON serializable.
    """
    traceback.print_exc()
    exc = map_exception(exc)
    logger.debug("Using exception type after mapping: %s", type(exc))
    
    if isinstance(exc, NotFound):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, PermissionDenied):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, ValidationError):
        status_code = status.HTTP_400_BAD_REQUEST
    else:
        status_code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    # Only show detailed errors for 400 and 404 in production
    # For 403 and 500 errors, only show details in debug mode
    if status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_500_INTERNAL_SERVER_ERROR] and not settings.DEBUG:
        if status_code == status.HTTP_403_FORBIDDEN:
            detail = "Permission denied"
        else:
            detail = "Internal server error"
    else:
        detail = jsonable_encoder(exc.detail) if hasattr(exc, "detail") else str(exc)
    
    error_data = {
        "status": status_code,
        "type": exc.__class__.__name__,
        "detail": detail,
    }
    
    logger.error("Exception handled explicitly: %s", error_data)
    return Response(error_data, status=status_code)
