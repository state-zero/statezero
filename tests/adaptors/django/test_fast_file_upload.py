import json
import requests
import tempfile
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.core.files.storage import default_storage
from tests.django_app.models import FileTest


class FastUploadViewTests(APITestCase):
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        self.fast_upload_url = reverse('statezero:fast_file_upload')
    
    def test_single_file_upload_initiate(self):
        """Test initiating single file upload with real S3 presigned URL"""
        response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'test-single.txt',
            'content_type': 'text/plain',
            'file_size': 1000,
            'num_chunks': 1
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['upload_type'], 'single')
        self.assertIn('upload_url', response.data)
        self.assertIn('file_path', response.data)
        self.assertEqual(response.data['content_type'], 'text/plain')
        
        # Verify the presigned URL is actually valid
        upload_url = response.data['upload_url']
        self.assertTrue(upload_url.startswith('https://'))
        
        return response.data  # Return for use in other tests
    
    def test_multipart_upload_initiate(self):
        """Test initiating multipart upload with real S3 presigned URLs"""
        response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'test-multipart.zip',
            'content_type': 'application/zip',
            'file_size': 50000000,  # 50MB
            'num_chunks': 3
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['upload_type'], 'multipart')
        self.assertIn('upload_id', response.data)
        self.assertIn('upload_urls', response.data)
        self.assertIn('file_path', response.data)
        
        # Check that we got URLs for all parts
        upload_urls = response.data['upload_urls']
        self.assertEqual(len(upload_urls), 3)
        
        # Verify all URLs are valid
        for part_num, url in upload_urls.items():
            self.assertTrue(url.startswith('https://'))
            self.assertIn('uploadId=', url)  # Should contain upload ID
            self.assertIn(f'partNumber={part_num}', url)  # Should contain part number
        
        return response.data
    
    def test_single_file_upload_complete_flow(self):
        """Test complete single file upload flow with actual S3 upload"""
        # Step 1: Initiate upload
        initiate_response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'complete-test.txt',
            'content_type': 'text/plain',
            'file_size': 20,
            'num_chunks': 1
        })
        
        self.assertEqual(initiate_response.status_code, status.HTTP_200_OK)
        upload_data = initiate_response.data
        
        # Step 2: Actually upload file to S3 using presigned URL
        file_content = b'This is test content'
        upload_response = requests.put(
            upload_data['upload_url'],
            data=file_content,
            headers={'Content-Type': 'text/plain'}
        )
        
        self.assertEqual(upload_response.status_code, 200)
        
        # Step 3: Complete the upload
        complete_response = self.client.post(self.fast_upload_url, {
            'action': 'complete',
            'file_path': upload_data['file_path'],
            'original_name': 'complete-test.txt'
        })
        
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        self.assertEqual(complete_response.data['file_path'], upload_data['file_path'])
        self.assertEqual(complete_response.data['original_name'], 'complete-test.txt')
        self.assertEqual(complete_response.data['size'], 20)
        self.assertIn('file_url', complete_response.data)
        
        # Verify file actually exists in storage
        file_path = upload_data['file_path']
        self.assertTrue(default_storage.exists(file_path))
        
        # Verify file content
        with default_storage.open(file_path, 'rb') as f:
            stored_content = f.read()
            self.assertEqual(stored_content, file_content)
        
        # Clean up
        default_storage.delete(file_path)
        
        return complete_response.data
    
    def test_multipart_upload_complete_flow(self):
        """Test complete multipart upload flow with actual S3 upload"""
        # Create test content for multiple parts
        part1_content = b'A' * (5 * 1024 * 1024)  # 5MB
        part2_content = b'B' * (5 * 1024 * 1024)  # 5MB  
        part3_content = b'C' * (1 * 1024 * 1024)  # 1MB (last part can be smaller)
        total_size = len(part1_content) + len(part2_content) + len(part3_content)
        
        # Step 1: Initiate multipart upload
        initiate_response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'multipart-test.bin',
            'content_type': 'application/octet-stream',
            'file_size': total_size,
            'num_chunks': 3
        })
        
        self.assertEqual(initiate_response.status_code, status.HTTP_200_OK)
        upload_data = initiate_response.data
        
        # Step 2: Upload each part to S3
        parts_info = []
        part_contents = [part1_content, part2_content, part3_content]
        
        for part_num in range(1, 4):
            part_url = upload_data['upload_urls'][part_num]
            part_content = part_contents[part_num - 1]
            
            upload_response = requests.put(
                part_url,
                data=part_content,
                headers={'Content-Type': 'application/octet-stream'}
            )
            
            self.assertEqual(upload_response.status_code, 200)
            
            # Extract ETag from response
            etag = upload_response.headers.get('ETag', '').strip('"')
            self.assertTrue(etag)  # ETag should exist
            
            parts_info.append({
                'PartNumber': part_num,
                'ETag': etag
            })
        
        # Step 3: Complete multipart upload
        complete_response = self.client.post(
            self.fast_upload_url, 
            data=json.dumps({
                'action': 'complete',
                'file_path': upload_data['file_path'],
                'original_name': 'large-model-test.bin',
                'upload_id': upload_data['upload_id'],
                'parts': parts_info
            }),
            content_type='application/json'
        )
        
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        self.assertEqual(complete_response.data['file_path'], upload_data['file_path'])
        self.assertEqual(complete_response.data['original_name'], 'multipart-test.bin')
        self.assertEqual(complete_response.data['size'], total_size)
        
        # Verify file actually exists and has correct content
        file_path = upload_data['file_path']
        self.assertTrue(default_storage.exists(file_path))
        
        # Verify complete file content
        with default_storage.open(file_path, 'rb') as f:
            stored_content = f.read()
            expected_content = part1_content + part2_content + part3_content
            self.assertEqual(stored_content, expected_content)
            self.assertEqual(len(stored_content), total_size)
        
        # Clean up
        default_storage.delete(file_path)
        
        return complete_response.data
    
    def test_multipart_upload_too_many_chunks(self):
        """Test that multipart upload rejects too many chunks"""
        response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'huge-file.zip',
            'content_type': 'application/zip',
            'file_size': 50000000000,  # 50GB
            'num_chunks': 10001  # Over the limit
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Too many chunks', response.data['error'])
    
    def test_initiate_missing_filename(self):
        """Test that initiate fails without filename"""
        response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'content_type': 'text/plain',
            'file_size': 1000,
            'num_chunks': 1
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('filename required', response.data['error'])
    
    def test_content_type_auto_detection(self):
        """Test that content type is auto-detected from filename"""
        response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'document.pdf',  # No content_type provided
            'file_size': 1000,
            'num_chunks': 1
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['content_type'], 'application/pdf')
    
    def test_complete_missing_file_path(self):
        """Test that complete fails without file_path"""
        response = self.client.post(self.fast_upload_url, {
            'action': 'complete',
            'original_name': 'test.txt'
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file_path required', response.data['error'])
    
    def test_complete_file_not_found(self):
        """Test completing upload when file doesn't exist"""
        response = self.client.post(self.fast_upload_url, {
            'action': 'complete',
            'file_path': 'nonexistent/file.txt',
            'original_name': 'file.txt'
        })
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('File not found', response.data['error'])
    
    def test_invalid_action(self):
        """Test invalid action parameter"""
        response = self.client.post(self.fast_upload_url, {
            'action': 'invalid_action',
            'filename': 'test.txt'
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Invalid action', response.data['error'])
    
    def test_image_upload_with_fast_upload(self):
        """Test uploading an image file using fast upload"""
        # Create a simple 1x1 pixel PNG
        png_content = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13'
            b'\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x0cIDATx\x9cc```'
            b'\x00\x00\x00\x04\x00\x01\xdd\xcc\xdb\x1b\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        
        # Initiate upload
        initiate_response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'test-image.png',
            'content_type': 'image/png',
            'file_size': len(png_content),
            'num_chunks': 1
        })
        
        self.assertEqual(initiate_response.status_code, status.HTTP_200_OK)
        upload_data = initiate_response.data
        
        # Upload to S3
        upload_response = requests.put(
            upload_data['upload_url'],
            data=png_content,
            headers={'Content-Type': 'image/png'}
        )
        
        self.assertEqual(upload_response.status_code, 200)
        
        # Complete upload
        complete_response = self.client.post(self.fast_upload_url, {
            'action': 'complete',
            'file_path': upload_data['file_path'],
            'original_name': 'test-image.png'
        })
        
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        self.assertTrue(complete_response.data['file_path'].endswith('.png'))
        self.assertEqual(complete_response.data['size'], len(png_content))
        
        # Verify file exists and has correct content
        file_path = upload_data['file_path']
        self.assertTrue(default_storage.exists(file_path))
        
        with default_storage.open(file_path, 'rb') as f:
            stored_content = f.read()
            self.assertEqual(stored_content, png_content)
        
        # Clean up
        default_storage.delete(file_path)


class FastUploadIntegrationWithModelTests(APITestCase):
    """Integration tests with FileTest model using real S3 uploads"""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        self.fast_upload_url = reverse('statezero:fast_file_upload')
    
    def test_fast_upload_with_filetest_document_field(self):
        """Test using fast upload result with FileTest document field"""
        # Upload a document using fast upload
        file_content = b'This is a test document content for FileTest model'
        
        # Initiate
        initiate_response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'model-test-doc.txt',
            'content_type': 'text/plain',
            'file_size': len(file_content),
            'num_chunks': 1
        })
        
        upload_data = initiate_response.data
        
        # Upload to S3
        upload_response = requests.put(
            upload_data['upload_url'],
            data=file_content,
            headers={'Content-Type': 'text/plain'}
        )
        
        self.assertEqual(upload_response.status_code, 200)
        
        # Complete
        complete_response = self.client.post(self.fast_upload_url, {
            'action': 'complete',
            'file_path': upload_data['file_path'],
            'original_name': 'model-test-doc.txt'
        })
        
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        
        # Create FileTest instance with the uploaded file
        file_path = complete_response.data['file_path']
        file_test = FileTest.objects.create(
            title="Fast Upload Document Test",
            document=file_path
        )
        
        # Verify model integration
        self.assertEqual(file_test.title, "Fast Upload Document Test")
        self.assertTrue(file_test.document.name.endswith('.txt'))
        self.assertTrue(default_storage.exists(file_test.document.name))
        
        # Verify file content through model
        with file_test.document.open('rb') as f:
            model_content = f.read()
            self.assertEqual(model_content, file_content)
        
        # Clean up
        file_test.document.delete()
        file_test.delete()
    
    def test_fast_upload_with_filetest_image_field(self):
        """Test using fast upload result with FileTest image field"""
        # Create test image content
        png_content = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13'
            b'\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x0cIDATx\x9cc```'
            b'\x00\x00\x00\x04\x00\x01\xdd\xcc\xdb\x1b\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        
        # Upload using fast upload
        initiate_response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'model-test-image.png',
            'content_type': 'image/png',
            'file_size': len(png_content),
            'num_chunks': 1
        })
        
        upload_data = initiate_response.data
        
        # Upload to S3
        upload_response = requests.put(
            upload_data['upload_url'],
            data=png_content,
            headers={'Content-Type': 'image/png'}
        )
        
        self.assertEqual(upload_response.status_code, 200)
        
        # Complete
        complete_response = self.client.post(self.fast_upload_url, {
            'action': 'complete',
            'file_path': upload_data['file_path'],
            'original_name': 'model-test-image.png'
        })
        
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        
        # Create FileTest instance with the uploaded image
        file_path = complete_response.data['file_path']
        file_test = FileTest.objects.create(
            title="Fast Upload Image Test",
            image=file_path
        )
        
        # Verify model integration
        self.assertEqual(file_test.title, "Fast Upload Image Test")
        self.assertTrue(file_test.image.name.endswith('.png'))
        self.assertTrue(default_storage.exists(file_test.image.name))
        
        # Test image-specific properties (ImageField features)
        self.assertEqual(file_test.image.width, 1)
        self.assertEqual(file_test.image.height, 1)
        
        # Clean up
        file_test.image.delete()
        file_test.delete()
    
    def test_large_multipart_upload_with_model(self):
        """Test large file multipart upload integration with model"""
        # Create larger content requiring multipart upload
        part1_content = b'PART1-' + b'A' * (5 * 1024 * 1024 - 6)  # 5MB
        part2_content = b'PART2-' + b'B' * (5 * 1024 * 1024 - 6)  # 5MB
        total_size = len(part1_content) + len(part2_content)
        
        # Initiate multipart upload
        initiate_response = self.client.post(self.fast_upload_url, {
            'action': 'initiate',
            'filename': 'large-model-test.bin',
            'content_type': 'application/octet-stream',
            'file_size': total_size,
            'num_chunks': 2
        })
        
        upload_data = initiate_response.data
        
        # Upload parts
        parts_info = []
        part_contents = [part1_content, part2_content]
        
        for part_num in range(1, 3):
            part_url = upload_data['upload_urls'][part_num]
            part_content = part_contents[part_num - 1]
            
            upload_response = requests.put(
                part_url,
                data=part_content,
                headers={'Content-Type': 'application/octet-stream'}
            )
            
            self.assertEqual(upload_response.status_code, 200)
            
            etag = upload_response.headers.get('ETag', '').strip('"')
            parts_info.append({
                'PartNumber': part_num,
                'ETag': etag
            })
        
        # Complete upload
        complete_response = self.client.post(
            self.fast_upload_url, 
            data=json.dumps({
                'action': 'complete',
                'file_path': upload_data['file_path'],
                'original_name': 'large-model-test.bin',
                'upload_id': upload_data['upload_id'],
                'parts': parts_info
            }),
            content_type='application/json'
        )
        
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        
        # Create FileTest instance with the large uploaded file
        file_path = complete_response.data['file_path']
        file_test = FileTest.objects.create(
            title="Fast Upload Large File Test",
            document=file_path
        )
        
        # Verify the large file is correctly stored and accessible
        self.assertEqual(file_test.title, "Fast Upload Large File Test")
        self.assertTrue(default_storage.exists(file_test.document.name))
        
        # Verify complete file content
        with file_test.document.open('rb') as f:
            stored_content = f.read()
            expected_content = part1_content + part2_content
            self.assertEqual(stored_content, expected_content)
            self.assertEqual(len(stored_content), total_size)
        
        # Clean up
        file_test.document.delete()
        file_test.delete()