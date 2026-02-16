from django.db.models import Field as DjangoField
from django.db.models import Model as DjangoModel
from django.db.models.query import QuerySet as DjangoQuerySet
from rest_framework.request import Request as DRFRequest

# Type definitions for the Django adaptor
ORMField = DjangoField
ORMModel = DjangoModel
ORMQuerySet = DjangoQuerySet
RequestType = DRFRequest
