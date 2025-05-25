from __future__ import annotations
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.test import Client
import hashlib
import json
from typing import Optional, Dict, Any, Tuple
from fastapi.encoders import jsonable_encoder

User = get_user_model()

class ModelViewSubscription(models.Model):
    """
    Records a live request for a specific model and AST query.
    Optimized for statezero ModelView requests.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='live_requests')
    model_name = models.CharField(max_length=255)  # e.g. "django_app.DummyModel"
    ast_query = models.JSONField()  # The FULL AST structure (including "query" wrapper)
    response_hash = models.CharField(max_length=64, null=True, blank=True)
    channel_name = models.CharField(max_length=64)  # Hash of model_name + ast_query
    has_error = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_checked = models.DateTimeField(default=timezone.now)
    last_updated = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'model_view_subscriptions'
        indexes = [
            models.Index(fields=['model_name', 'is_active']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['channel_name']),
            models.Index(fields=['last_checked']),
        ]
        unique_together = ['user', 'channel_name']
    
    def __str__(self):
        return f"ModelViewSubscription({self.user.username}, {self.model_name}, {self.channel_name[:8]}...)"
    
    def subscription_info(self) -> Dict[str, Any]:
        """Get subscription metadata for API response."""
        return {
            'id': self.id,
            'channel_name': self.channel_name,
            'response_hash': self.response_hash,
            'last_updated': self.last_updated.isoformat(),
            'is_active': self.is_active,
            'has_error': self.has_error,
            'model_name': self.model_name
        }
    
    def generate_hash(self, data: Optional[Dict[str, Any]]) -> Optional[str]:
        """Generate SHA-256 hash of data."""
        if data is None:
            return None
        json_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode('utf-8')).hexdigest()
    
    def generate_channel_key(self) -> str:
        """Generate channel key from model_name + ast_query."""
        channel_data = {
            'model_name': self.model_name,
            'ast_query': self.ast_query
        }
        return self.generate_hash(channel_data)
    
    @classmethod
    def _update_or_create_subscription(
        cls, 
        user: User, 
        model_name: str, 
        ast_query: Dict[str, Any], 
        response_data: Dict[str, Any]
    ) -> Tuple['ModelViewSubscription', bool]:
        """
        Create or update a live subscription for a specific model and AST query.
        Returns (subscription, created) tuple.
        """
        # First, generate the channel name we'll use for lookup
        temp_instance = cls(
            model_name=model_name,
            ast_query=ast_query
        )
        channel_name = temp_instance.generate_channel_key()
        response_hash = temp_instance.generate_hash(response_data)
        
        # Use update_or_create with the unique constraint fields
        subscription, created = cls.objects.update_or_create(
            user=user,
            channel_name=channel_name,
            defaults={
                'model_name': model_name,
                'ast_query': ast_query,
                'response_hash': response_hash,
                'has_error': False,
                'is_active': True,
                'last_checked': timezone.now()
            }
        )
        
        # If updating existing subscription, ensure last_updated reflects the data change
        if not created:
            subscription.last_updated = timezone.now()
            subscription.save(update_fields=['last_updated'])
        
        return subscription, created
    
    @classmethod
    def initialize(cls, user: User, model_name: str, ast_query: Dict[str, Any], response_data: Dict[str, Any]) -> ModelViewSubscription:
        """
        Legacy method - now delegates to _update_or_create_subscription.
        Kept for backward compatibility.
        """
        jsonable_ast_query = jsonable_encoder(ast_query)
        subscription, created = cls._update_or_create_subscription(user, model_name, jsonable_ast_query, response_data)
        return subscription
    
    def rerun(self) -> bool:
        """
        Rerun the ModelView request and return True if data changed.
        """
        from django.urls import reverse
        
        # Create test client
        client = Client()
        client.force_login(self.user)
        
        # Build the request to ModelView
        url = reverse("statezero:model_view", args=[self.model_name])
        
        # Use the stored AST directly - no parsing/nesting needed!
        payload = {"ast": self.ast_query}
        
        try:
            response = client.post(url, data=json.dumps(payload), content_type='application/json')
        except Exception as e:
            self._set_error_state()
            return False
        
        # Check for HTTP errors
        if response.status_code >= 400:
            self._set_error_state()
            return False
        
        # Parse JSON response
        try:
            new_response_data = response.json()
        except Exception as e:
            self._set_error_state()
            raise
        
        # Check if response changed
        new_hash = self.generate_hash(new_response_data)
        has_changed = self.response_hash != new_hash
        
        if has_changed:
            self.response_hash = new_hash
            self.last_updated = timezone.now()
        
        self.has_error = False
        self.last_checked = timezone.now()
        self.save(update_fields=['response_hash', 'has_error', 'last_checked', 'last_updated'])
        
        return has_changed
    
    def _set_error_state(self):
        """Set the error state for this subscription."""
        self.response_hash = "ERROR"
        self.has_error = True
        self.last_checked = timezone.now()
        self.save(update_fields=['response_hash', 'has_error', 'last_checked'])
        
    def deactivate(self):
        """Deactivate this subscription (soft delete)."""
        self.is_active = False
        self.save(update_fields=['is_active'])
    
    def reactivate(self):
        """Reactivate this subscription."""
        self.is_active = True
        self.has_error = False
        self.last_checked = timezone.now()
        self.save(update_fields=['is_active', 'has_error', 'last_checked'])