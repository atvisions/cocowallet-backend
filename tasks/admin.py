from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages
from django.urls import path
from django.shortcuts import redirect
from django.core.management import call_command
from .models import (
    Task, TaskHistory, UserPoints, PointsHistory, ShareTaskToken
)



@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    """任务管理"""
    list_display = ['name', 'code', 'points', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'code']

    def get_queryset(self, request):
        """过滤掉 SHARE_TOKEN 类型的任务"""
        qs = super().get_queryset(request)
        return qs.exclude(code='SHARE_TOKEN')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('sync-tasks/', self.sync_tasks, name='sync-tasks'),
        ]
        return custom_urls + urls

    def sync_tasks(self, request):
        """同步任务配置"""
        try:
            call_command('sync_tasks')
            self.message_user(request, '任务同步成功！', messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f'任务同步失败：{str(e)}', messages.ERROR)
        return redirect('..')

    def changelist_view(self, request, extra_context=None):
        """添加同步按钮到列表页面"""
        extra_context = extra_context or {}
        extra_context['sync_tasks_button'] = True
        return super().changelist_view(request, extra_context)

    def save_model(self, request, obj, form, change):
        # 防止创建 SHARE_TOKEN 类型的通用任务
        if obj.code == 'SHARE_TOKEN':
            messages.error(request, '请使用 Share Task Token 管理分享代币任务')
            return
        super().save_model(request, obj, form, change)

@admin.register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
    """任务历史管理"""
    list_display = ['device_id', 'task', 'completed_at', 'points_awarded']
    list_filter = ['completed_at', 'points_awarded']
    search_fields = ['device_id', 'task__name']

@admin.register(ShareTaskToken)
class ShareTaskTokenAdmin(admin.ModelAdmin):
    """分享代币任务管理"""
    list_display = ['token', 'points', 'is_active']
    list_filter = ['is_active']
    search_fields = ['token__name', 'token__symbol']
    raw_id_fields = ['token']
    
    def save_model(self, request, obj, form, change):
        try:
            # 1. 获取或创建 SHARE_TOKEN 任务
            task, created = Task.objects.get_or_create(
                code='SHARE_TOKEN',
                defaults={
                    'name': 'Share Token',
                    'description': 'Share token to earn points',
                    'points': 0,  # 使用 ShareTaskToken 中的 points
                    'is_active': True
                }
            )
            
            # 2. 关联任务
            obj.task = task
            
            # 3. 确保每个代币只有一个活跃的分享任务
            if obj.is_active:
                existing = ShareTaskToken.objects.filter(
                    token=obj.token,
                    is_active=True
                ).exclude(pk=obj.pk).exists()
                
                if existing:
                    messages.error(request, f'代币 {obj.token.symbol} 已存在活跃的分享任务')
                    return
                    
            super().save_model(request, obj, form, change)
            
        except Exception as e:
            messages.error(request, f'保存失败: {str(e)}')

@admin.register(UserPoints)
class UserPointsAdmin(admin.ModelAdmin):
    """用户积分管理"""
    list_display = ['device_id', 'total_points', 'created_at']
    search_fields = ['device_id']

@admin.register(PointsHistory)
class PointsHistoryAdmin(admin.ModelAdmin):
    """积分历史管理"""
    list_display = ['device_id', 'points', 'action_type', 'created_at']
    list_filter = ['action_type', 'created_at']
    search_fields = ['device_id']
