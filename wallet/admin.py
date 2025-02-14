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
    TokenIndexReport
)
import re
from django.urls import path
from django.http import JsonResponse
from django.template.response import TemplateResponse
import asyncio
from .management.commands.sync_token_metadata import Command as SyncTokenMetadataCommand
from django.utils.safestring import mark_safe
from django.db import connection
import logging

logger = logging.getLogger(__name__)

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

@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    """代币管理"""
    list_display = ('logo_img', 'name', 'symbol', 'chain', 'address', 'decimals', 'is_native', 'is_visible', 'is_recommended')
    list_filter = (DecimalsFilter, 'chain', 'is_native', 'is_visible', 'is_recommended')
    search_fields = ('name', 'symbol', 'address')
    readonly_fields = ('created_at', 'updated_at')
    list_editable = ['is_recommended']
    actions = ['sync_token_metadata']
    change_list_template = 'admin/wallet/token/change_list.html'

    def get_queryset(self, request):
        """默认只显示非零小数位数的代币，并排除 NFT"""
        queryset = super().get_queryset(request)
        # 如果没有指定过滤器，默认排除小数位数为0的代币
        if 'decimals_filter' not in request.GET:
            queryset = queryset.exclude(decimals=0)
        # 排除 NFT：通过多个条件识别 NFT
        queryset = queryset.exclude(
            Q(type='nft') |  # 类型为 nft
            Q(decimals=0, symbol__icontains='DIGIKONG') |  # DIGIKONG NFT
            Q(decimals=0, contract_type__in=['ERC721', 'ERC1155'])  # ERC721/ERC1155 代币
        )
        return queryset

    def save_model(self, request, obj, form, change):
        """保存模型时统一合约地址为小写"""
        if obj.address:
            obj.address = obj.address.lower()
        super().save_model(request, obj, form, change)

    def logo_img(self, obj):
        if obj.logo:
            return format_html('<img src="{}" style="width: 32px; height: 32px; border-radius: 50%;" />', obj.logo)
        return '-'
    logo_img.short_description = '图标'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('sync-metadata/', self.admin_site.admin_view(self.sync_metadata_view), name='token_sync_metadata'),
            path('sync-metadata/status/', self.admin_site.admin_view(self.sync_metadata_status), name='token_sync_metadata_status'),
        ]
        return custom_urls + urls

    def sync_metadata_view(self, request):
        if request.method == 'POST':
            try:
                # 创建命令实例
                command = SyncTokenMetadataCommand()
                
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
            title='同步代币元数据',
        )
        return TemplateResponse(request, 'admin/wallet/token/sync_metadata.html', context)

    def sync_metadata_status(self, request):
        try:
            command = SyncTokenMetadataCommand()
            status = command.get_sync_status()
            logger.debug(f"获取同步状态: {status}")
            return JsonResponse(status)
        except Exception as e:
            import traceback
            error_msg = f"获取状态失败: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return JsonResponse({'status': 'error', 'message': error_msg}, status=500)

    def sync_token_metadata(self, request, queryset):
        """同步选中代币的元数据"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            command = SyncTokenMetadataCommand()
            loop.run_until_complete(command.handle_async())
            self.message_user(request, '代币元数据同步完成')
        except Exception as e:
            self.message_user(request, f'同步失败: {str(e)}', level='error')
    sync_token_metadata.short_description = '同步代币元数据'

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['name', 'chain', 'address', 'device_id', 'is_active', 'created_at']
    list_filter = ['chain', 'is_active', 'is_watch_only', 'is_imported']
    search_fields = ['name', 'address', 'device_id']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(NFTCollection)
class NFTCollectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'chain', 'contract_address', 'is_verified', 'is_recommended', 'floor_price']
    list_filter = ['chain', 'is_verified', 'is_recommended']
    search_fields = ['name', 'contract_address']
    list_editable = ['is_verified', 'is_recommended']
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
    list_display = ['device_id', 'created_at', 'updated_at']
    search_fields = ['device_id']
    readonly_fields = ['created_at', 'updated_at']

    def get_fieldsets(self, request, obj=None):
        return [
            ('基本信息', {
                'fields': [
                    'device_id', 'created_at', 'updated_at'
                ]
            })
        ]

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
    ordering = ('-report_date',)
