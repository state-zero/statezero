from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Type, Union

import jsonschema
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from statezero.core.types import ORMField


class ValidatorType(str, Enum):
    """OpenAPI-aligned validators"""

    # Numeric validators
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    EXCLUSIVE_MINIMUM = "exclusiveMinimum"
    EXCLUSIVE_MAXIMUM = "exclusiveMaximum"
    MULTIPLE_OF = "multipleOf"

    # String validators
    MIN_LENGTH = "minLength"
    MAX_LENGTH = "maxLength"
    PATTERN = "pattern"

    # Array validators
    MIN_ITEMS = "minItems"
    MAX_ITEMS = "maxItems"
    UNIQUE_ITEMS = "uniqueItems"

    # Object validators
    MIN_PROPERTIES = "minProperties"
    MAX_PROPERTIES = "maxProperties"
    REQUIRED = "required"

    # Format validators
    FORMAT = "format"  # Handles email, url, date-time, etc.


@dataclass
class Validator:
    type: ValidatorType
    value: Any  # The constraint value
    message: str  # Error message to display

    def to_openapi(self) -> dict:
        """Convert validator to OpenAPI schema fragment"""
        if self.type == ValidatorType.FORMAT:
            return {"format": self.value}
        return {self.type: self.value}


class FieldType(str, Enum):
    """Basic field types from the implementation"""

    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    NUMBER = "number"
    ARRAY = "array"
    OBJECT = "object"
    FILE = "file"


class FieldFormat(str, Enum):
    """Field formats from the implementation"""

    ID = "id"
    UUID = "uuid"
    TEXT = "text"
    DATE = "date"
    DATETIME = "date-time"
    FOREIGN_KEY = "foreign-key"
    ONE_TO_ONE = "one-to-one"
    MANY_TO_MANY = "many-to-many"
    DECIMAL = "decimal"
    FILE_PATH = "file-path"
    IMAGE_PATH = "image-path"
    JSON = "json"
    MONEY = "money"


@dataclass
class AdditionalField:
    """
    Represents configuration for an additional computed field in the schema.

    Attributes:
        name: The name of the property/method on the model that provides the value
        field: The Django model field instance that defines the serialization behavior
        title: Optional override for the field's display title
    """

    name: str  # The property/method name to pull from
    field: Type[ORMField]  # The instantiated serializer field (e.g. CharField(max_length=255)) #type:ignore
    title: Optional[str] # Optional display name override

class SchemaFieldMetadata(BaseModel):
    type: FieldType
    title: str
    required: bool
    description: Optional[str] = None
    nullable: bool = False
    format: Optional[FieldFormat] = None
    max_length: Optional[int] = None
    choices: Optional[Dict[str, str]] = None
    default: Optional[Any] = None
    validators: List[Validator] = Field(default_factory=list)
    max_digits: Optional[int] = None  # For decimal fields
    decimal_places: Optional[int] = None  # For decimal fields
    read_only: bool = False
    ref: Optional[str] = None


class ModelSchemaMetadata(BaseModel):
    """Core model metadata needed for frontend operations"""

    model_name: str  # model name for queries
    title: str  # display name (verbose_name)
    class_name: str  # class name for generating ts/js classes
    plural_title: str  # verbose_name_plural
    primary_key_field: str

    # Query capabilities
    filterable_fields: Set[str]
    searchable_fields: Set[str]
    ordering_fields: Set[str]
    properties: Dict[str, SchemaFieldMetadata]
    relationships: Dict[str, Dict[str, Any]]
    default_ordering: Optional[List[str]] = None
    # Extra definitions (for schemas referenced via $ref) are merged in if provided.
    definitions: Dict[str, Any] = field(default_factory=dict)
    
    # Date / time formatting templates
    datetime_format: Optional[str] = None
    date_format: Optional[str] = None
    time_format: Optional[str] = None

@dataclass
class ModelSummaryRepresentation:
    pk: Any
    repr: Dict[str, Optional[str]] = field(default_factory=dict)
    model_name: Optional[str] = field(default=None)
    pk_field: str = "id"

    def to_dict(self) -> dict:
        return {
            self.pk_field: jsonable_encoder(self.pk),
            "repr": self.repr,
        }


@dataclass
class ModelNode:
    model_name: str
    model: Optional[Type] = None  # The actual model class (if applicable)
    type: str = "model"


@dataclass
class FieldNode:
    model_name: str  # The parent model's name
    field_name: str  # The name of the field
    is_relation: bool
    related_model: Optional[str] = None  # The object name of the related model, if any
    type: str = "field"
