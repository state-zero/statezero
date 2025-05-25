from __future__ import annotations
from django.db import models
from django.contrib.auth import get_user_model
from django.test import Client
import hashlib
import json
from typing import Optional, Dict, Any, Tuple
from fastapi.encoders import jsonable_encoder

User = get_user_model()

class ModelViewSubscription(models.Model):
    """
    Records a live request for a specific model and AST query.
    Simple per-user subscription model.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='live_requests', null=True, blank=True)
    model_name = models.CharField(max_length=255)  # e.g. "django_app.DummyModel"
    ast_query = models.JSONField()  # The FULL AST structure (including "query" wrapper)
    response_hash = models.CharField(max_length=64, null=True, blank=True)
    channel_name = models.CharField(max_length=64)  # Hash of user + ast_query
    
    class Meta:
        db_table = 'model_view_subscriptions'
        indexes = [
            models.Index(fields=['model_name']),
        ]
        unique_together = ['user', 'channel_name']
    
    def __str__(self):
        username = self.user.username if self.user else 'anonymous'
        return f"ModelViewSubscription({username}, {self.model_name}, {self.channel_name[:8]}...)"
    
    def subscription_info(self) -> Dict[str, Any]:
        """Get subscription metadata for API response."""
        return {
            'channel_name': self.channel_name,
        }
    
    def generate_hash(self, data: Optional[Dict[str, Any]]) -> Optional[str]:
        """Generate SHA-256 hash of data."""
        if data is None:
            return None
        json_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode('utf-8')).hexdigest()
    
    def generate_channel_name(self) -> str:
        """Generate unique channel name from user + ast_query."""
        event_data = {
            'user_id': self.user.pk if self.user else 'anon',
            'ast_query': self.ast_query
        }
        return self.generate_hash(event_data)
    
    @classmethod
    def _update_or_create_subscription(
        cls, 
        user: Optional[User], 
        model_name: str, 
        ast_query: Dict[str, Any], 
        response_data: Dict[str, Any]
    ) -> Tuple['ModelViewSubscription', bool]:
        """
        Create or update a live subscription for a specific model and AST query.
        Returns (subscription, created) tuple.
        """
        # Generate the channel name
        temp_instance = cls(
            user=user,
            model_name=model_name,
            ast_query=ast_query
        )
        channel_name = temp_instance.generate_channel_name()
        response_hash = temp_instance.generate_hash(response_data)
        
        # Use update_or_create with channel_name as unique constraint
        subscription, created = cls.objects.update_or_create(
            channel_name=channel_name,
            defaults={
                'user': user,
                'model_name': model_name,
                'ast_query': ast_query,
                'response_hash': response_hash,
            }
        )
        
        return subscription, created
    
    @classmethod
    def initialize(cls, user: Optional[User], model_name: str, ast_query: Dict[str, Any], response_data: Dict[str, Any]) -> 'ModelViewSubscription':
        """
        Create or update a subscription.
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
        if self.user:
            client.force_login(self.user)
        
        # Build the request to ModelView
        url = reverse("statezero:model_view", args=[self.model_name])
        
        # Use the stored AST directly
        payload = {"ast": self.ast_query}
        
        try:
            response = client.post(url, data=json.dumps(payload), content_type='application/json')
        except Exception:
            return False
        
        # Check for HTTP errors
        if response.status_code >= 400:
            return False
        
        # Parse JSON response
        try:
            new_response_data = response.json()
        except Exception:
            return False
        
        # Check if response changed
        new_hash = self.generate_hash(new_response_data)
        has_changed = self.response_hash != new_hash
        
        if has_changed:
            self.response_hash = new_hash
            self.save(update_fields=['response_hash'])
        
        return has_changed