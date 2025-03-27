from django.contrib import admin
from django.utils.html import format_html
import requests
from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from .models import (
    Wallet, Token, NFTCollection, Transaction,
    MnemonicBackup, PaymentPassword, TokenIndex,
    TokenIndexSource, TokenIndexMetrics, TokenIndexGrade,
    TokenIndexReport, TokenCategory,
    ReferralRelationship, UserPoints, PointsHistory, ReferralLink,
    Task, TaskHistory, ShareTaskToken
)
import re
from django.urls import path
from django.http import JsonResponse, HttpResponse
from django.template.response import TemplateResponse
import asyncio
from .management.commands.sync_token_metadata import Command as SyncTokenMetadataCommand
from django.utils.safestring import mark_safe
from django.db import connection
import logging
from django import forms
from .services.factory import ChainServiceFactory
from django.core.exceptions import ValidationError
import json
from openai import OpenAI
import csv
from django.contrib.auth.models import User, Group
from django.core.management import call_command
from django.template.loader import render_to_string
from django.conf import settings
from django.shortcuts import redirect

logger = logging.getLogger(__name__)

# 修改后台标题
admin.site.site_header = 'COCO Wallet 管理后台'
admin.site.site_title = 'COCO Wallet'
admin.site.index_title = '管理中心'

# 用户和组的中文显示
admin.site.unregister(User)
admin.site.unregister(Group)

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'is_active', 'date_joined']
    search_fields = ['username', 'email']
    list_filter = ['is_active', 'is_staff', 'date_joined']

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    class Meta:
        verbose_name = '用户组'
        verbose_name_plural = '用户组'

class DecimalsFilter(admin.SimpleListFilter):
    """代币小数位数过滤器"""
    title = '小数位数'
    parameter_name = 'decimals_filter'

    def lookups(self, request, model_admin):
        return (
            ('non_zero', '非零小数位数'),
            ('zero', '零小数位数'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'non_zero':
            return queryset.exclude(decimals=0)
        elif self.value() == 'zero':
            return queryset.filter(decimals=0)
        return queryset

class ChainFilter(admin.SimpleListFilter):
    """链筛选器"""
    title = '链'
    parameter_name = 'chain'

    def lookups(self, request, model_admin):
        return (
            ('ETH', 'Ethereum'),
            ('BNB', 'BNB Chain'),  # 修改为 BNB 以匹配 MoralisConfig
            ('MATIC', 'Polygon'),
            ('AVAX', 'Avalanche'),
            ('BASE', 'Base'),
            ('ARBITRUM', 'Arbitrum'),
            ('OPTIMISM', 'Optimism'),
            ('SOL', 'Solana')
        )

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(chain=self.value())
        return queryset

class TokenAdminForm(forms.ModelForm):
    """代币管理表单"""
    class Meta:
        model = Token
        fields = '__all__'
        exclude = ['is_recommended']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 将 chain 字段改为只有 Solana 选项的选择框
        self.fields['chain'] = forms.ChoiceField(
            choices=[('SOL', 'Solana')],  # 只保留 Solana 选项
            initial='SOL',  # 设置默认值
            label='链'
        )
        
        # 添加批量导入字段
        if not self.instance.pk:  # 只在创建新记录时显示
            self.fields['bulk_import'] = forms.FileField(
                required=False,
                label='批量导入 (CSV/JSON)',
                help_text='上传 CSV 或 JSON 文件批量导入代币'
            )

    def clean_address(self):
        # 返回原始地址，不进行任何转换
        return self.cleaned_data['address']

@admin.register(TokenCategory)
class TokenCategoryAdmin(admin.ModelAdmin):
    """代币分类管理"""
    list_display = ('name', 'code', 'description', 'priority', 'is_active', 'token_count')
    list_editable = ('priority', 'is_active')
    search_fields = ('name', 'code', 'description')
    ordering = ('priority', 'name')
    
    def token_count(self, obj):
        return obj.tokens.count()
    token_count.short_description = '代币数量'

@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    """代币管理"""
    list_display = ('symbol', 'name', 'chain', 'address', 'is_verified', 'is_visible', 'is_recommended')
    list_filter = ('chain', 'is_verified', 'is_recommended', 'is_visible')
    search_fields = ('symbol', 'name', 'address')
    list_editable = ['is_verified', 'is_visible', 'is_recommended']
    readonly_fields = ('created_at', 'updated_at')
    
    def get_queryset(self, request):
        """获取查询集"""
        # 移除任何涉及 code 字段的过滤
        return super().get_queryset(request)
    
    def sync_token_metadata(self, request, queryset):
        """同步代币元数据"""
        for token in queryset:
            try:
                # 调用同步命令
                call_command('sync_token_metadata', 
                           address=token.address, 
                           chain=token.chain)
                self.message_user(request, f'成功同步代币 {token.symbol} 的元数据')
            except Exception as e:
                self.message_user(request, f'同步代币 {token.symbol} 失败: {str(e)}', level=messages.ERROR)
    
    sync_token_metadata.short_description = "同步选中代币的元数据"
    
    actions = ['sync_token_metadata']

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['name', 'device_id', 'chain', 'address', 'is_active']
    search_fields = ['name', 'device_id', 'address']
    list_filter = ['chain', 'is_active']

    class Meta:
        verbose_name = 'Wallet'
        verbose_name_plural = 'Wallets'

@admin.register(NFTCollection)
class NFTCollectionAdmin(admin.ModelAdmin):
    def logo_img(self, obj):
        if obj.logo:
            return format_html('<img src="{}" style="width: 32px; height: 32px; border-radius: 50%;" />', obj.logo)
        return '-'
    logo_img.short_description = '图标'
    
    list_display = ['logo_img', 'name', 'chain', 'contract_address', 'is_verified', 'is_spam', 'floor_price_usd']
    list_filter = ['chain', 'is_verified', 'is_spam']
    search_fields = ['name', 'contract_address']
    list_editable = ['is_verified', 'is_spam']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['tx_hash', 'chain', 'tx_type', 'status', 'from_address', 'to_address', 'amount', 'block_timestamp']
    list_filter = ['chain', 'tx_type', 'status']
    search_fields = ['tx_hash', 'from_address', 'to_address']
    readonly_fields = ['created_at']

@admin.register(MnemonicBackup)
class MnemonicBackupAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'created_at']
    search_fields = ['device_id']
    readonly_fields = ['created_at']

@admin.register(PaymentPassword)
class PaymentPasswordAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'created_at']
    search_fields = ['device_id']

    class Meta:
        verbose_name = 'Payment Password'
        verbose_name_plural = 'Payment Passwords'

@admin.register(TokenIndex)
class TokenIndexAdmin(admin.ModelAdmin):
    """代币索引管理"""
    list_display = ('name', 'symbol', 'chain', 'address', 'decimals', 'is_native', 'is_verified', 'get_grade', 'get_metrics')
    list_filter = ('chain', 'is_native', 'is_verified', 'grade__grade')
    search_fields = ('name', 'symbol', 'address')
    readonly_fields = ('created_at', 'updated_at', 'get_grade', 'get_metrics')
    change_list_template = 'admin/wallet/tokenindex/change_list.html'
    actions = ['sync_selected_tokens']

    def get_grade(self, obj):
        """获取代币等级"""
        try:
            return obj.grade.get_grade_display()
        except:
            return '-'
    get_grade.short_description = '等级'

    def get_metrics(self, obj):
        """获取代币指标"""
        try:
            metrics = obj.metrics
            return format_html(
                '持有人: {}<br>'
                '日交易量: ${:,.2f}<br>'
                '流动性: ${:,.2f}<br>'
                '价格: ${:,.6f}',
                metrics.holder_count,
                float(metrics.daily_volume),
                float(metrics.liquidity),
                float(metrics.price)
            )
        except:
            return '-'
    get_metrics.short_description = '指标'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('sync/', self.admin_site.admin_view(self.sync_view), name='tokenindex_sync'),
            path('sync/status/', self.admin_site.admin_view(self.sync_status), name='tokenindex_sync_status'),
        ]
        return custom_urls + urls

    def sync_view(self, request):
        if request.method == 'POST':
            try:
                from .management.commands.sync_token_index import Command
                command = Command()
                
                # 在后台运行同步任务
                async def run_sync():
                    try:
                        await command.handle_async()
                    except Exception as e:
                        logger.error(f"同步任务执行失败: {str(e)}")
                        command.update_sync_status(status='error', progress=0, message=str(e))
                
                # 创建新的事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # 启动异步任务
                future = asyncio.ensure_future(run_sync(), loop=loop)
                
                # 在后台线程中运行事件循环
                import threading
                def run_loop():
                    loop.run_until_complete(future)
                    loop.close()
                
                thread = threading.Thread(target=run_loop)
                thread.daemon = True
                thread.start()
                
                return JsonResponse({'status': 'success', 'message': '同步任务已启动'})
            except Exception as e:
                import traceback
                error_msg = f"启动同步任务失败: {str(e)}\n{traceback.format_exc()}"
                logger.error(error_msg)
                return JsonResponse({'status': 'error', 'message': error_msg}, status=500)
        
        # GET 请求显示同步页面
        context = dict(
            self.admin_site.each_context(request),
            title='同步代币索引',
        )
        return TemplateResponse(request, 'admin/wallet/tokenindex/sync.html', context)

    def sync_status(self, request):
        try:
            from .management.commands.sync_token_index import Command
            command = Command()
            status = command.get_sync_status()
            return JsonResponse(status)
        except Exception as e:
            import traceback
            error_msg = f"获取状态失败: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return JsonResponse({'status': 'error', 'message': error_msg}, status=500)

    def sync_selected_tokens(self, request, queryset):
        """同步选中的代币"""
        try:
            from .management.commands.sync_token_index import Command
            command = Command()
            
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # 运行同步任务
            loop.run_until_complete(command.handle_async())
            
            self.message_user(request, f'成功同步 {len(queryset)} 个代币')
        except Exception as e:
            self.message_user(request, f'同步失败: {str(e)}', level='error')
    sync_selected_tokens.short_description = '同步选中代币'

    def save_model(self, request, obj, form, change):
        """保存模型时统一合约地址为小写"""
        if obj.address:
            obj.address = obj.address.lower()
        super().save_model(request, obj, form, change)

@admin.register(TokenIndexSource)
class TokenIndexSourceAdmin(admin.ModelAdmin):
    """代币数据源管理"""
    list_display = ('name', 'priority', 'last_sync', 'is_active')
    list_editable = ('priority', 'is_active')
    ordering = ('priority',)

@admin.register(TokenIndexMetrics)
class TokenIndexMetricsAdmin(admin.ModelAdmin):
    """代币指标管理"""
    list_display = ('token', 'daily_volume', 'holder_count', 'liquidity', 'market_cap', 'price', 'updated_at')
    search_fields = ('token__symbol', 'token__name', 'token__address')
    readonly_fields = ('updated_at',)

@admin.register(TokenIndexGrade)
class TokenIndexGradeAdmin(admin.ModelAdmin):
    """代币等级管理"""
    list_display = ('token', 'grade', 'score', 'last_evaluated')
    list_filter = ('grade',)
    search_fields = ('token__symbol', 'token__name', 'token__address')
    readonly_fields = ('last_evaluated',)

@admin.register(TokenIndexReport)
class TokenIndexReportAdmin(admin.ModelAdmin):
    """索引库报告管理"""
    list_display = ('report_date', 'total_tokens', 'grade_a_count', 'grade_b_count', 'grade_c_count', 'new_tokens', 'removed_tokens')
    readonly_fields = ('report_date', 'total_tokens', 'grade_a_count', 'grade_b_count', 'grade_c_count', 'new_tokens', 'removed_tokens', 'details')

@admin.register(ReferralRelationship)
class ReferralRelationshipAdmin(admin.ModelAdmin):
    list_display = ['referrer_device_id', 'referred_device_id', 'download_completed']
    list_filter = ['download_completed']
    search_fields = ['referrer_device_id', 'referred_device_id']

    class Meta:
        verbose_name = 'Referral Relationship'
        verbose_name_plural = 'Referral Relationships'

@admin.register(UserPoints)
class UserPointsAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'total_points', 'created_at']
    search_fields = ['device_id']

@admin.register(PointsHistory)
class PointsHistoryAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'points', 'action_type', 'created_at']
    list_filter = ['action_type', 'created_at']
    search_fields = ['device_id']

@admin.register(ReferralLink)
class ReferralLinkAdmin(admin.ModelAdmin):
    list_display = ['code', 'clicks', 'created_at']
    search_fields = ['code']

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    """任务管理"""
    list_display = ['name', 'code', 'points', 'daily_limit', 'is_repeatable', 'is_active']
    list_filter = ['is_active', 'is_repeatable']
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
    list_display = ['token', 'points', 'daily_limit', 'is_active', 'official_tweet_id']
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
                    'daily_limit': 1,
                    'is_repeatable': True,
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

# 自定义应用分组
class WalletAdminArea(admin.AdminSite):
    site_header = 'COCO Wallet Admin'
    site_title = 'COCO Wallet Admin Portal'
    index_title = 'Welcome to COCO Wallet Admin Portal'

    def get_app_list(self, request):
        """获取应用列表并按分组重组"""
        # 获取原始应用列表
        original_app_list = super().get_app_list(request)
        
        # 定义分组
        app_dict = {
            'Account Management': {
                'name': 'Account Management',
                'models': ['Wallet', 'PaymentPassword']
            },
            'Token Management': {
                'name': 'Token Management',
                'models': ['Token', 'TokenIndex', 'TokenCategory']
            },
            'Task Management': {
                'name': 'Task Management',
                'models': ['Task', 'TaskHistory', 'ShareTaskToken']
            },
            'Points Management': {
                'name': 'Points Management',
                'models': ['UserPoints', 'PointsHistory']
            },
            'Referral Management': {
                'name': 'Referral Management',
                'models': ['ReferralLink', 'ReferralRelationship']
            }
        }
        
        # 获取所有模型
        all_models = []
        for app in original_app_list:
            all_models.extend(app['models'])
        
        # 重组应用列表
        new_app_list = []
        for group_name, group_config in app_dict.items():
            group_models = []
            for model in all_models:
                if model['object_name'] in group_config['models']:
                    model_dict = {
                        'name': model['name'],
                        'object_name': model['object_name'],
                        'perms': model['perms'],
                        'admin_url': model['admin_url'],
                        'add_url': model['add_url'],
                    }
                    group_models.append(model_dict)
            
            if group_models:  # 只添加有模型的分组
                new_app_list.append({
                    'name': group_config['name'],
                    'app_label': group_name.lower().replace(' ', '_'),
                    'app_url': '#',
                    'has_module_perms': True,
                    'models': group_models
                })
        
        return new_app_list

# 创建新的管理站点实例
admin_site = WalletAdminArea(name='admin')

# 注册所有模型
admin_site.register(Wallet, WalletAdmin)
admin_site.register(Token, TokenAdmin)
admin_site.register(Task, TaskAdmin)
admin_site.register(TaskHistory, TaskHistoryAdmin)
admin_site.register(ShareTaskToken, ShareTaskTokenAdmin)
admin_site.register(UserPoints, UserPointsAdmin)
admin_site.register(PointsHistory, PointsHistoryAdmin)
admin_site.register(ReferralLink, ReferralLinkAdmin)
admin_site.register(ReferralRelationship, ReferralRelationshipAdmin)
admin_site.register(PaymentPassword, PaymentPasswordAdmin)

# 替换默认的 AdminSite
admin.site = admin_site
