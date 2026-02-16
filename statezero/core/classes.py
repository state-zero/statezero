from dataclasses import field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set, Type, Union, Annotated

import jsonschema
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.dataclasses import dataclass

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
    TIME = "time"
    FOREIGN_KEY = "foreign-key"
    ONE_TO_ONE = "one-to-one"
    MANY_TO_MANY = "many-to-many"
    DECIMAL = "decimal"
    FILE_PATH = "file-path"
    IMAGE_PATH = "image-path"
    JSON = "json"
    MONEY = "money"


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class AdditionalField:
    """
    Represents configuration for an additional computed field in the schema.

    Attributes:
        name: The name of the property/method on the model that provides the value
        field: The Django model field instance that defines the serialization behavior
        title: Optional override for the field's display title
    """

    name: str  # The property/method name to pull from
    field: ORMField  # The instantiated serializer field (e.g. CharField(max_length=255)) #type:ignore
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

    # Display customization
    display: Optional[Dict[str, Any]] = None

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
class FieldDisplayConfig:
    """
    Configuration for customizing how a field is displayed in the frontend.

    Attributes:
        field_name: The name of the field this config applies to
        display_component: Custom UI component name (e.g., "AddressAutocomplete", "DatePicker")
        filter_queryset: Filter options for select/multi-select fields (dict passed to backend)
        display_help_text: Additional help text for the field
        extra: Additional custom metadata for framework-specific or UI-specific extensions
    """
    field_name: str
    display_component: Optional[str] = None
    filter_queryset: Optional[Dict[str, Any]] = None
    display_help_text: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


@dataclass
class FieldGroup:
    """
    Group related fields together for better UX.

    Attributes:
        display_title: Group heading
        display_description: Group description
        field_names: List of field names in this group
    """
    display_title: str
    display_description: Optional[str] = None
    field_names: Optional[List[str]] = None


# =============================================================================
# Layout Elements - JSON Forms inspired layout system
# =============================================================================

class LayoutType(str, Enum):
    """Types of layout elements"""
    VERTICAL = "VerticalLayout"
    HORIZONTAL = "HorizontalLayout"
    GROUP = "Group"
    CONTROL = "Control"
    DISPLAY = "Display"
    ALERT = "Alert"
    LABEL = "Label"
    DIVIDER = "Divider"


@dataclass
class Control:
    """
    A form control bound to a serializer field.
    Uses same attribute names as FieldDisplayConfig for consistency.

    Attributes:
        field_name: The serializer field this control is bound to
        display_component: Custom UI component name
        filter_queryset: Filter options for FK/M2M fields
        display_help_text: Additional help text
        extra: Additional custom metadata passed to the component
        label: Override the field's title
        full_width: Whether this control should span full width
    """
    field_name: str
    display_component: Optional[str] = None
    filter_queryset: Optional[Dict[str, Any]] = None
    display_help_text: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    label: Optional[str] = None
    full_width: bool = False
    type: Literal["Control"] = field(default="Control", init=False)


@dataclass
class Display:
    """
    A display-only element that renders data from context.
    Does not collect input - purely for showing information.

    Attributes:
        context_path: Dot-notation path to value in workflow context (e.g., "unit.access_code")
        display_component: UI component to render with (e.g., "code-display", "copy-url")
        label: Label to show above the display
        extra: Additional custom metadata passed to the component
    """
    context_path: Optional[str] = None
    display_component: str = "text"
    label: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    type: Literal["Display"] = field(default="Display", init=False)


@dataclass
class Alert:
    """
    An alert/info banner element.

    Attributes:
        severity: Alert type - "info", "warning", "error", "success"
        text: Static text to display
        context_path: Or pull text from context
    """
    severity: Literal["info", "warning", "error", "success"] = "info"
    text: Optional[str] = None
    context_path: Optional[str] = None
    type: Literal["Alert"] = field(default="Alert", init=False)


@dataclass
class Label:
    """
    A static text label element.

    Attributes:
        text: The text to display
        variant: Text style - "heading", "subheading", "body", "caption"
    """
    text: str
    variant: Literal["heading", "subheading", "body", "caption"] = "body"
    type: Literal["Label"] = field(default="Label", init=False)


@dataclass
class Divider:
    """A visual separator/divider element."""
    type: Literal["Divider"] = field(default="Divider", init=False)


@dataclass
class Conditional:
    """
    Conditionally render a layout based on form data or context.

    The `when` expression is evaluated as JavaScript with access to:
    - formData: Current form field values
    - context: Workflow context data

    Examples:
        when="formData.payment_method === 'card'"
        when="context.has_wifi === true"
        when="formData.amount > 100"

    Attributes:
        when: JavaScript expression that returns a boolean
        layout: Layout to render when condition is true
    """
    when: str
    layout: "LayoutElement"
    type: Literal["Conditional"] = field(default="Conditional", init=False)


@dataclass
class Tab:
    """
    A single tab within a Tabs container.

    Attributes:
        label: Tab button label
        layout: Content to render when tab is active
    """
    label: str
    layout: "LayoutElement"


@dataclass
class Tabs:
    """
    A tabbed container for organizing content into switchable panels.

    Attributes:
        tabs: List of Tab elements
        default_tab: Index of initially active tab (0-based)
    """
    tabs: List[Tab] = field(default_factory=list)
    default_tab: int = 0
    type: Literal["Tabs"] = field(default="Tabs", init=False)


# Layout element union type for type hints
LayoutElement = Union[
    Control, Display, Alert, Label, Divider, Conditional, Tabs,
    "VerticalLayout", "HorizontalLayout", "Group"
]


@dataclass
class VerticalLayout:
    """
    Stack elements vertically.

    Attributes:
        elements: Child layout elements
        gap: Spacing between elements - "sm", "md", "lg"
    """
    elements: List["LayoutElement"] = field(default_factory=list)
    gap: Literal["sm", "md", "lg"] = "md"
    type: Literal["VerticalLayout"] = field(default="VerticalLayout", init=False)


@dataclass
class HorizontalLayout:
    """
    Stack elements horizontally.

    Attributes:
        elements: Child layout elements
        gap: Spacing between elements - "sm", "md", "lg"
        align: Vertical alignment - "start", "center", "end", "stretch"
    """
    elements: List["LayoutElement"] = field(default_factory=list)
    gap: Literal["sm", "md", "lg"] = "md"
    align: Literal["start", "center", "end", "stretch"] = "start"
    type: Literal["HorizontalLayout"] = field(default="HorizontalLayout", init=False)


@dataclass
class Group:
    """
    A labeled container/section with nested layout.

    Attributes:
        label: Section heading
        description: Section description
        layout: Nested layout (defaults to VerticalLayout)
        collapsible: Whether the group can be collapsed
        collapsed: Initial collapsed state
    """
    label: str
    description: Optional[str] = None
    layout: Optional["LayoutElement"] = None
    collapsible: bool = False
    collapsed: bool = False
    type: Literal["Group"] = field(default="Group", init=False)


# Convenience type for the root layout
Layout = Union[VerticalLayout, HorizontalLayout]


@dataclass
class DisplayMetadata:
    """
    Rich display information for models and actions to customize frontend rendering.

    Attributes:
        display_title: Main heading/title override
        display_description: Explanatory text about the model/action
        field_groups: Logical grouping of fields (e.g., "Contact Info", "Address Details")
            - Legacy: use `layout` for more control
        field_display_configs: Per-field customization (custom components, filters, help text)
            - Legacy: use Control elements in `layout` for more control
        layout: Rich layout tree for complex form/display rendering. Takes precedence over
            field_groups when present. Supports nesting, display-only elements, conditionals, etc.
        extra: Additional custom metadata for framework-specific or UI-specific extensions
    """
    display_title: Optional[str] = None
    display_description: Optional[str] = None
    field_groups: Optional[List[FieldGroup]] = None
    field_display_configs: Optional[List[FieldDisplayConfig]] = None
    layout: Optional[Layout] = None
    extra: Optional[Dict[str, Any]] = None
