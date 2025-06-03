from rest_framework import fields
from rest_framework.fields import empty
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage

image_fields_supported = False
try:
    from PIL import Image
    import io
    image_fields_supported = True
except:
    image_fields_supported = False

class FileFieldSerializer(fields.FileField):
    """
    Copy of DRF's FileField but handles file paths instead of file objects.
    """
    default_error_messages = {
        'required': 'No file path provided.',
        'invalid': 'Not a valid file path.',
        'no_name': 'No filename could be determined.',
        'empty': 'The submitted file path is empty.',
        'max_length': 'Ensure this filename has at most {max_length} characters (it has {length}).',
        'file_not_found': 'File not found at the specified path.',
    }

    def __init__(self, **kwargs):
        self.max_length = kwargs.pop('max_length', None)
        self.allow_empty_file = kwargs.pop('allow_empty_file', False)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if data is empty:
            return None

        if not isinstance(data, str):
            self.fail('invalid')

        if not data:
            if self.allow_empty_file:
                return data
            self.fail('empty')

        if self.max_length is not None and len(data) > self.max_length:
            self.fail('max_length', max_length=self.max_length, length=len(data))

        if not default_storage.exists(data):
            self.fail('file_not_found')

        return data

class ImageFieldSerializer(fields.ImageField):
    """
    Copy of DRF's ImageField but handles file paths instead of file objects.
    """
    default_error_messages = {
        'invalid_image': (
            'Upload a valid image. The file you uploaded was either not an '
            'image or a corrupted image.'
        ),
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        # File path validation logic
        if data is empty:
            return None

        if not isinstance(data, str):
            self.fail('invalid')

        if not data:
            if self.allow_empty_file:
                return data
            self.fail('empty')

        if self.max_length is not None and len(data) > self.max_length:
            self.fail('max_length', max_length=self.max_length, length=len(data))

        if not default_storage.exists(data):
            self.fail('file_not_found')

        # Image validation logic
        if image_fields_supported:
            try:
                with default_storage.open(data, 'rb') as f:
                    image = Image.open(f)
                    image.verify()
                    
                    # verify() invalidates the image
                    f.seek(0)
                    image = Image.open(f)
                    
            except Exception:
                self.fail('invalid_image')

        return data