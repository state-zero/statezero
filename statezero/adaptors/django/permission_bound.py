from statezero.core.permission_bound import PermissionBound as _PermissionBound


class PermissionBound(_PermissionBound):
    """
    Django convenience subclass that fills in ``registry``,
    ``orm_provider``, and ``serializer`` from the Django config singletons.

    Usage::

        from statezero.adaptors.django.permission_bound import PermissionBound

        bound = PermissionBound(MyModel, user)
        bound.objects.filter(city="NYC").serialize()
    """

    def __init__(self, model, user, depth=1, **kwargs):
        from statezero.adaptors.django.config import config, registry

        kwargs.setdefault("registry", registry)
        kwargs.setdefault("orm_provider", config.orm_provider)
        kwargs.setdefault("serializer", config.serializer)
        super().__init__(model, user, depth=depth, **kwargs)

    @property
    def serializer_class(self):
        """Return a DynamicModelSerializer class for this model."""
        from statezero.adaptors.django.serializers import DynamicModelSerializer

        return DynamicModelSerializer.for_model(self.model)
