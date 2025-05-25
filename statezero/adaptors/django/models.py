import hashlib
import json
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class QuerySubscription(models.Model):
    query_hash = models.CharField(max_length=64, unique=True, db_index=True)
    model_name = models.CharField(max_length=100, db_index=True)
    query_ast = models.JSONField()
    query_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_executed_at = models.DateTimeField(null=True, blank=True)
    active_subscribers = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'statezero_query_subscriptions'
        indexes = [
            models.Index(fields=['model_name', 'created_at']),
            models.Index(fields=['active_subscribers', 'last_executed_at']),
        ]
    
    @classmethod
    def get_query_hash(cls, model_name, query_ast):
        query_data = {
            'model': model_name,
            'query': query_ast
        }
        query_str = json.dumps(query_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(query_str.encode('utf-8')).hexdigest()


class UserSubscription(models.Model):
    subscription = models.ForeignKey(
        QuerySubscription, 
        on_delete=models.CASCADE,
        related_name='user_subscriptions'
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    last_data_hash = models.CharField(max_length=64, null=True, blank=True)
    last_queried_at = models.DateTimeField(auto_now=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    socket_id = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'statezero_user_subscriptions'
        unique_together = ['subscription', 'user']
        indexes = [
            models.Index(fields=['user', 'is_active', 'last_queried_at']),
            models.Index(fields=['subscription', 'is_active', 'last_notified_at']),
        ]

    @classmethod
    def get_data_hash(cls, data):
        data_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(data_str.encode('utf-8')).hexdigest()