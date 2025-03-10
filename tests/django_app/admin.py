from django.contrib import admin

from .models import (ComprehensiveModel, DeepModelLevel1, DeepModelLevel2,
                     DeepModelLevel3, DummyModel, DummyRelatedModel)

admin.site.register(DummyRelatedModel)
admin.site.register(DummyModel)
admin.site.register(DeepModelLevel3)
admin.site.register(DeepModelLevel2)
admin.site.register(DeepModelLevel1)
admin.site.register(ComprehensiveModel)
