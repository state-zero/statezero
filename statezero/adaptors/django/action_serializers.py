import inspect
import datetime as _dt
import uuid
import enum
import copy
from typing import Any, Dict, Optional, get_args, get_origin, Union, Annotated

from django.db import models
from rest_framework import serializers
from docstring_parser import parse as parse_docstring


class AutoSerializerInferenceError(ValueError):
    """Raised when an action serializer cannot be inferred from type hints."""


def get_or_build_action_serializer(action_config: dict):
    """
    Return the configured serializer or infer one from the action function's type hints.
    Caches the inferred serializer on the action config and function attributes.
    """
    serializer_class = action_config.get("serializer")
    if serializer_class:
        return serializer_class

    func = action_config.get("function")
    if not func:
        return None

    serializer_class = build_action_input_serializer(
        func, docstring=action_config.get("docstring")
    )
    if serializer_class:
        action_config["serializer"] = serializer_class
        func._statezero_serializer = serializer_class
    return serializer_class


def build_action_input_serializer(func, docstring: Optional[str] = None):
    """
    Infer a DRF Serializer from the action's type hints.
    Returns None when no input fields are required.
    """
    signature = inspect.signature(func)
    param_descriptions = _parse_param_descriptions(docstring)

    try:
        type_hints = _get_type_hints_safe(func)
    except Exception as exc:
        raise AutoSerializerInferenceError(
            f"Failed to resolve type hints for action '{func.__name__}'. "
            "Provide an explicit serializer."
        ) from exc

    fields: Dict[str, serializers.Field] = {}
    for param in signature.parameters.values():
        if param.name == "request":
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise AutoSerializerInferenceError(
                f"Action '{func.__name__}' uses *args/**kwargs which cannot be auto-inferred. "
                "Provide an explicit serializer."
            )

        annotation = type_hints.get(param.name, inspect._empty)
        if annotation is inspect._empty:
            raise AutoSerializerInferenceError(
                f"Action '{func.__name__}' parameter '{param.name}' is missing a type hint. "
                "Provide an explicit serializer."
            )

        description = param_descriptions.get(param.name)
        field = _field_from_annotation(annotation, param.name, func.__name__, description)

        _apply_param_defaults(field, param, annotation)
        fields[param.name] = field

    if not fields:
        return None

    class_name = _to_camel_case(func.__name__) + "AutoInputSerializer"
    return type(class_name, (serializers.Serializer,), fields)


def _get_type_hints_safe(func):
    # Use function globals so forward references resolve in app context.
    return getattr(__import__("typing"), "get_type_hints")(func, globalns=func.__globals__)


def _apply_param_defaults(field: serializers.Field, param: inspect.Parameter, annotation):
    annotation, optional = _unwrap_optional(_unwrap_annotated(annotation))

    if param.default is not inspect._empty:
        field.required = False
        if param.default is None:
            field.allow_null = True
            field.default = None
            _set_field_kwargs(field, required=False, allow_null=True, default=None)
        else:
            field.default = param.default
            _set_field_kwargs(field, required=False, default=param.default)
    elif optional:
        field.required = False
        field.allow_null = True
        _set_field_kwargs(field, required=False, allow_null=True)


def _set_field_kwargs(field: serializers.Field, **updates) -> None:
    # Keep DRF deepcopy behavior consistent with runtime field attributes.
    if not hasattr(field, "_kwargs"):
        return
    field._kwargs.update(updates)


def _field_from_annotation(annotation, param_name: str, func_name: str, description: Optional[str]):
    annotation = _unwrap_annotated(annotation)
    annotation, optional = _unwrap_optional(annotation)

    kwargs = {}
    if description:
        kwargs["help_text"] = description
    if optional:
        kwargs["allow_null"] = True

    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation in (str,):
        return serializers.CharField(**kwargs)
    if annotation in (int,):
        return serializers.IntegerField(**kwargs)
    if annotation in (float,):
        return serializers.FloatField(**kwargs)
    if annotation in (bool,):
        return serializers.BooleanField(**kwargs)
    if annotation is _dt.datetime:
        return serializers.DateTimeField(**kwargs)
    if annotation is _dt.date:
        return serializers.DateField(**kwargs)
    if annotation is _dt.time:
        return serializers.TimeField(**kwargs)
    if annotation is uuid.UUID:
        return serializers.UUIDField(**kwargs)

    if _is_drf_field_annotation(annotation):
        return _drf_field_from_annotation(annotation, kwargs)

    if _is_enum(annotation):
        choices = _enum_choices(annotation)
        return serializers.ChoiceField(choices=choices, **kwargs)

    if _is_model_class(annotation):
        return serializers.PrimaryKeyRelatedField(
            queryset=annotation.objects.all(), **kwargs
        )

    if origin in (list,):
        if not args:
            raise AutoSerializerInferenceError(
                f"Action '{func_name}' parameter '{param_name}' uses an untyped list. "
                "Provide an explicit serializer."
            )
        child_type = args[0]
        child_type = _unwrap_annotated(child_type)
        child_type, _ = _unwrap_optional(child_type)

        if _is_model_class(child_type):
            return serializers.PrimaryKeyRelatedField(
                many=True, queryset=child_type.objects.all(), **kwargs
            )
        if child_type in (str, int, float, bool):
            return serializers.ListField(child=_field_from_annotation(child_type, param_name, func_name, None), **kwargs)
        if child_type in (dict,) or get_origin(child_type) in (dict,):
            return serializers.ListField(child=serializers.JSONField(), **kwargs)

        if child_type is Any:
            raise AutoSerializerInferenceError(
                f"Action '{func_name}' parameter '{param_name}' uses List[Any] which cannot be auto-inferred. "
                "Provide an explicit serializer."
            )

        raise AutoSerializerInferenceError(
            f"Action '{func_name}' parameter '{param_name}' uses a list of unsupported type '{child_type}'. "
            "Provide an explicit serializer."
        )

    if annotation in (dict,) or origin in (dict,):
        return serializers.JSONField(**kwargs)

    if origin is getattr(__import__("typing"), "Literal"):
        if not args:
            raise AutoSerializerInferenceError(
                f"Action '{func_name}' parameter '{param_name}' uses an empty Literal. "
                "Provide an explicit serializer."
            )
        return serializers.ChoiceField(choices=list(args), **kwargs)

    if annotation is Any:
        raise AutoSerializerInferenceError(
            f"Action '{func_name}' parameter '{param_name}' uses Any which cannot be auto-inferred. "
            "Provide an explicit serializer."
        )

    raise AutoSerializerInferenceError(
        f"Action '{func_name}' parameter '{param_name}' uses unsupported type '{annotation}'. "
        "Provide an explicit serializer."
    )


def _unwrap_optional(annotation):
    origin = get_origin(annotation)
    if origin is Union:
        args = [arg for arg in get_args(annotation)]
        if type(None) in args:
            non_none = [arg for arg in args if arg is not type(None)]
            if len(non_none) == 1:
                return non_none[0], True
            raise AutoSerializerInferenceError(
                "Union types with multiple non-None members cannot be auto-inferred. "
                "Provide an explicit serializer."
            )
    return annotation, False


def _unwrap_annotated(annotation):
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            return args[0]
    return annotation


def _is_model_class(candidate) -> bool:
    return isinstance(candidate, type) and issubclass(candidate, models.Model)


def _is_drf_field_annotation(candidate) -> bool:
    return isinstance(candidate, serializers.Field) or (
        isinstance(candidate, type) and issubclass(candidate, serializers.Field)
    )


def _drf_field_from_annotation(annotation, kwargs: Dict[str, Any]) -> serializers.Field:
    if isinstance(annotation, serializers.Field):
        field = copy.deepcopy(annotation)
        _set_field_kwargs(field, **kwargs)
        field.required = kwargs.get("required", field.required)
        field.allow_null = kwargs.get("allow_null", field.allow_null)
        if "help_text" in kwargs:
            field.help_text = kwargs["help_text"]
        return field
    return annotation(**kwargs)


def _is_enum(candidate) -> bool:
    return isinstance(candidate, type) and issubclass(candidate, enum.Enum)


def _enum_choices(enum_cls):
    # Prefer Django TextChoices/IntegerChoices choices if available.
    choices = getattr(enum_cls, "choices", None)
    if choices:
        return choices
    return [(member.value, member.name) for member in enum_cls]


def _to_camel_case(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _parse_param_descriptions(docstring: Optional[str]) -> Dict[str, str]:
    if not docstring:
        return {}
    parsed = parse_docstring(docstring)
    return {
        param.arg_name: param.description.strip()
        for param in parsed.params
        if param.arg_name and param.description
    }
