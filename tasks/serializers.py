from rest_framework import serializers
from .models import (
    Task, TaskHistory, UserPoints, PointsHistory, ShareTaskToken
)

class TaskSerializer(serializers.ModelSerializer):
    """任务序列化器"""
    class Meta:
        model = Task
        fields = [
            'id', 'code', 'name', 'description', 'points',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class TaskHistorySerializer(serializers.ModelSerializer):
    """任务历史记录序列化器"""
    task = TaskSerializer()
    
    class Meta:
        model = TaskHistory
        fields = ['task', 'device_id', 'completed_at', 'points_awarded']
        read_only_fields = ['device_id', 'completed_at', 'points_awarded']

class ShareTaskTokenSerializer(serializers.ModelSerializer):
    """分享任务代币序列化器"""
    token_symbol = serializers.CharField(source='token.symbol', read_only=True)
    token_name = serializers.CharField(source='token.name', read_only=True)
    token_logo = serializers.URLField(source='token.logo', read_only=True)
    token_price = serializers.CharField(source='token.last_price', read_only=True)
    token_price_change = serializers.CharField(source='token.last_price_change', read_only=True)
    
    class Meta:
        model = ShareTaskToken
        fields = ['id', 'token', 'token_symbol', 'token_name', 'token_logo', 
                 'token_price', 'token_price_change', 'points', 'is_active',
                 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

class UserPointsSerializer(serializers.ModelSerializer):
    """用户积分序列化器"""
    class Meta:
        model = UserPoints
        fields = ['device_id', 'total_points', 'created_at', 'updated_at']
        read_only_fields = ['device_id', 'total_points', 'created_at', 'updated_at']

class PointsHistorySerializer(serializers.ModelSerializer):
    """积分历史记录序列化器"""
    action_display = serializers.SerializerMethodField()
    
    class Meta:
        model = PointsHistory
        fields = ['points', 'action_type', 'action_display', 'description', 
                 'related_device_id', 'created_at']
        read_only_fields = ['points', 'action_type', 'action_display', 'description', 
                          'related_device_id', 'created_at']
    
    def get_action_display(self, obj):
        """获取操作类型显示名称"""
        action_types = {
            'DAILY_CHECK_IN': '每日签到',
            'TASK_COMPLETION': '完成任务',
            'SHARE_TASK': '分享任务',
            'REFERRAL': '推荐奖励'
        }
        return action_types.get(obj.action_type, obj.action_type)
