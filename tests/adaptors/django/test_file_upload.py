import io
import tempfile
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from rest_framework import status
from django.core.files.storage import default_storage
from tests.django_app.models import FileTest

class FileUploadViewTests(APITestCase):
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
    
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_file_upload_success(self):
        """Test successful file upload"""
        test_file = SimpleUploadedFile(
            "test.txt",
            b"file content",
            content_type="text/plain"
        )
        
        url = reverse('statezero:file_upload')
        response = self.client.post(url, {'file': test_file}, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('file_path', response.data)
        self.assertIn('file_url', response.data)
        self.assertIn('original_name', response.data)
        self.assertIn('size', response.data)
        self.assertEqual(response.data['original_name'], 'test.txt')
        self.assertEqual(response.data['size'], 12)
    
    def test_file_upload_no_file(self):
        """Test upload with no file provided"""
        url = reverse('statezero:file_upload')
        response = self.client.post(url, {}, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertEqual(response.data['error'], 'No file provided')
    
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_file_upload_image(self):
        """Test image file upload"""
        # Create a simple 1x1 pixel PNG
        png_content = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13'
            b'\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x0cIDATx\x9cc```'
            b'\x00\x00\x00\x04\x00\x01\xdd\xcc\xdb\x1b\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        
        test_image = SimpleUploadedFile(
            "test.png",
            png_content,
            content_type="image/png"
        )
        
        url = reverse('statezero:file_upload')
        response = self.client.post(url, {'file': test_image}, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['original_name'], 'test.png')
        self.assertTrue(response.data['file_path'].endswith('.png'))
    
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_file_actually_saved(self):
        """Test that file is actually saved to storage"""
        test_file = SimpleUploadedFile(
            "saved_test.txt",
            b"content to save",
            content_type="text/plain"
        )
        
        url = reverse('statezero:file_upload')
        response = self.client.post(url, {'file': test_file}, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check file exists in storage
        file_path = response.data['file_path']
        self.assertTrue(default_storage.exists(file_path))
        
        # Check file content
        with default_storage.open(file_path, 'rb') as f:
            content = f.read()
            self.assertEqual(content, b"content to save")


class FileTestModelIntegrationTests(APITestCase):
    """Integration tests using our FileTest model"""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
    
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_upload_and_create_filetest_with_document(self):
        """Test uploading a file and creating FileTest model with document field"""
        # First upload a file
        test_file = SimpleUploadedFile(
            "document.pdf",
            b"fake pdf content",
            content_type="application/pdf"
        )
        
        upload_url = reverse('statezero:file_upload')
        upload_response = self.client.post(upload_url, {'file': test_file}, format='multipart')
        
        self.assertEqual(upload_response.status_code, status.HTTP_200_OK)
        file_path = upload_response.data['file_path']
        
        # Create FileTest instance manually to test the integration
        file_test = FileTest.objects.create(
            title="Test Document",
            document=file_path
        )
        
        self.assertEqual(file_test.title, "Test Document")
        self.assertTrue(file_test.document.name.endswith('.pdf'))
        self.assertTrue(default_storage.exists(file_test.document.name))
    
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_upload_and_create_filetest_with_image(self):
        """Test uploading an image and creating FileTest model with image field"""
        # Create a simple 1x1 pixel PNG
        png_content = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13'
            b'\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x0cIDATx\x9cc```'
            b'\x00\x00\x00\x04\x00\x01\xdd\xcc\xdb\x1b\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        
        test_image = SimpleUploadedFile(
            "image.png",
            png_content,
            content_type="image/png"
        )
        
        upload_url = reverse('statezero:file_upload')
        upload_response = self.client.post(upload_url, {'file': test_image}, format='multipart')
        
        self.assertEqual(upload_response.status_code, status.HTTP_200_OK)
        file_path = upload_response.data['file_path']
        
        # Create FileTest instance manually to test the integration
        file_test = FileTest.objects.create(
            title="Test Image",
            image=file_path
        )
        
        self.assertEqual(file_test.title, "Test Image")
        self.assertTrue(file_test.image.name.endswith('.png'))
        self.assertTrue(default_storage.exists(file_test.image.name))
        
        # Test image-specific properties (width/height are available for ImageField)
        # Note: The test PNG is 1x1 pixel
        self.assertEqual(file_test.image.width, 1)
        self.assertEqual(file_test.image.height, 1)
    
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_filetest_with_both_fields(self):
        """Test FileTest model with both document and image fields"""
        # Upload document
        doc_file = SimpleUploadedFile("doc.txt", b"document content", content_type="text/plain")
        upload_url = reverse('statezero:file_upload')
        doc_response = self.client.post(upload_url, {'file': doc_file}, format='multipart')
        doc_path = doc_response.data['file_path']
        
        # Upload image
        png_content = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13'
            b'\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x0cIDATx\x9cc```'
            b'\x00\x00\x00\x04\x00\x01\xdd\xcc\xdb\x1b\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        img_file = SimpleUploadedFile("img.png", png_content, content_type="image/png")
        img_response = self.client.post(upload_url, {'file': img_file}, format='multipart')
        img_path = img_response.data['file_path']
        
        # Create FileTest with both fields
        file_test = FileTest.objects.create(
            title="Full Test",
            document=doc_path,
            image=img_path
        )
        
        self.assertEqual(file_test.title, "Full Test")
        self.assertTrue(file_test.document.name.endswith('.txt'))
        self.assertTrue(file_test.image.name.endswith('.png'))
        
        # Both files should exist
        self.assertTrue(default_storage.exists(file_test.document.name))
        self.assertTrue(default_storage.exists(file_test.image.name))