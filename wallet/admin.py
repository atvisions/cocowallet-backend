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
    form = TokenAdminForm
    list_display = ['display_logo', 'name', 'symbol', 'chain', 'is_verified', 'is_recommended', 'is_visible']
    search_fields = ['name', 'symbol', 'address']
    list_filter = ['chain', 'is_verified', 'is_recommended', 'is_visible']
    list_editable = ['is_verified', 'is_visible', 'is_recommended']
    readonly_fields = ('created_at', 'updated_at')
    actions = ['sync_token_metadata', 'fetch_ai_recommendations', 'set_token_category', 'make_recommended', 'remove_recommended']
    
    # 添加自定义按钮的 Media 类
    class Media:
        js = ('admin/js/token_sync.js',)  # 创建这个 JS 文件
        css = {
            'all': ('admin/css/token_sync.css',)  # 创建这个 CSS 文件
        }

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'sync-metadata/',
                self.admin_site.admin_view(self.sync_metadata_view),
                name='wallet_token_sync_metadata'
            ),
            path(
                'toggle-recommend/<int:token_id>/',
                self.admin_site.admin_view(self.toggle_recommend_view),
                name='wallet_token_toggle_recommend'
            ),
            path('sync-tasks/', self.sync_tasks, name='sync-tasks'),
        ]
        return custom_urls + urls

    def sync_metadata_view(self, request):
        """处理同步元数据请求"""
        try:
            address = request.GET.get('address')
            chain = request.GET.get('chain')
            
            if not address or not chain:
                return JsonResponse({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=400)

            try:
                # 调用同步命令
                call_command('sync_token_metadata', 
                            address=address, 
                            chain=chain, 
                            async_mode=False)

                # 获取更新后的数据
                try:
                    token = Token.objects.get(chain=chain, address=address)
                    return JsonResponse({
                        'status': 'success',
                        'data': {
                            'name': token.name,
                            'symbol': token.symbol,
                            'decimals': token.decimals,
                            'logo': token.logo,
                            'is_verified': token.is_verified,
                            'category': token.category.id if token.category else None,
                            'description': token.description,
                            'website': token.website,
                            'twitter': token.twitter,
                            'telegram': token.telegram,
                            'discord': token.discord,
                            'github': token.github,
                            'total_supply': token.total_supply,
                            'circulating_supply': token.circulating_supply,
                            'market_cap': token.market_cap,
                            'contract_type': token.contract_type
                        }
                    })
                except Token.DoesNotExist:
                    return JsonResponse({
                        'status': 'error',
                        'message': '代币未找到或同步失败'
                    }, status=404)

            except Exception as e:
                # 处理同步命令执行失败的情况
                error_message = str(e)
                if "未找到" in error_message:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'代币未在 Jupiter 上找到'
                    }, status=404)
                else:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'同步失败: {error_message}'
                    }, status=500)

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'请求处理失败: {str(e)}'
            }, status=500)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not obj:  # 只在创建新对象时设置默认值
            form.base_fields['chain'].initial = 'SOL'
        # 限制 chain 字段只能选择 SOL
        form.base_fields['chain'].choices = [('SOL', 'Solana')]
        form.base_fields['address'].widget.template_name = 'admin/widgets/token_address_widget.html'
        return form

    def category_display(self, obj):
        if obj.category:
            return obj.category.name
        return '-'
    category_display.short_description = '分类'
    
    def set_token_category(self, request, queryset):
        """设置代币分类"""
        from django.template.response import TemplateResponse
        
        if 'apply' in request.POST:
            category_id = request.POST.get('category')
            category = None
            if category_id and category_id != '':
                try:
                    category = TokenCategory.objects.get(id=category_id)
                except TokenCategory.DoesNotExist:
                    self.message_user(request, '所选分类不存在', level='error')
                    return
            
            count = 0
            for token in queryset:
                token.category = category
                token.save()
                count += 1
            
            self.message_user(request, f'成功为 {count} 个代币设置分类')
            return
        
        # 显示分类选择表单
        categories = TokenCategory.objects.filter(is_active=True)
        return TemplateResponse(
            request,
            'admin/wallet/token/set_category.html',
            {
                'title': '设置代币分类',
                'queryset': queryset,
                'categories': categories,
                'opts': self.model._meta,
            }
        )
    set_token_category.short_description = '设置所选代币的分类'
    
    def import_tokens_view(self, request):
        """导入代币视图"""
        if request.method == 'POST':
            try:
                file = request.FILES.get('import_file')
                if not file:
                    return JsonResponse({'status': 'error', 'message': '请选择文件'}, status=400)
                
                # 根据文件类型处理
                if file.name.endswith('.csv'):
                    result = self.import_from_csv(file)
                elif file.name.endswith('.json'):
                    result = self.import_from_json(file)
                else:
                    return JsonResponse({'status': 'error', 'message': '不支持的文件类型，请上传 CSV 或 JSON 文件'}, status=400)
                
                return JsonResponse({
                    'status': 'success',
                    'message': f'成功导入 {result["imported"]} 个代币，跳过 {result["skipped"]} 个代币',
                    'details': result
                })
            except Exception as e:
                logger.error(f"导入代币失败: {str(e)}")
                return JsonResponse({'status': 'error', 'message': f'导入失败: {str(e)}'}, status=500)
        
        # GET 请求显示导入页面
        context = dict(
            self.admin_site.each_context(request),
            title='导入代币',
            categories=TokenCategory.objects.filter(is_active=True),
        )
        return TemplateResponse(request, 'admin/wallet/token/import_tokens.html', context)
    
    def export_tokens_view(self, request):
        """导出代币视图"""
        try:
            # 获取筛选条件
            chain = request.GET.get('chain')
            category_id = request.GET.get('category')
            format = request.GET.get('format', 'json')
            
            # 构建查询
            queryset = Token.objects.all()
            if chain:
                queryset = queryset.filter(chain=chain)
            if category_id:
                queryset = queryset.filter(category_id=category_id)
            
            # 导出数据
            if format == 'csv':
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = 'attachment; filename="tokens.csv"'
                
                writer = csv.writer(response)
                writer.writerow(['chain', 'address', 'name', 'symbol', 'decimals', 'logo', 'category', 'is_native', 'is_visible', 'is_recommended'])
                
                for token in queryset:
                    writer.writerow([
                        token.chain,
                        token.address,
                        token.name,
                        token.symbol,
                        token.decimals,
                        token.logo,
                        token.category.code if token.category else '',
                        token.is_native,
                        token.is_visible,
                        token.is_recommended
                    ])
                
                return response
            else:  # JSON
                data = []
                for token in queryset:
                    data.append({
                        'chain': token.chain,
                        'address': token.address,
                        'name': token.name,
                        'symbol': token.symbol,
                        'decimals': token.decimals,
                        'logo': token.logo,
                        'category': token.category.code if token.category else None,
                        'is_native': token.is_native,
                        'is_visible': token.is_visible,
                        'is_recommended': token.is_recommended
                    })
                
                response = HttpResponse(json.dumps(data, indent=2), content_type='application/json')
                response['Content-Disposition'] = 'attachment; filename="tokens.json"'
                return response
        except Exception as e:
            logger.error(f"导出代币失败: {str(e)}")
            return JsonResponse({'status': 'error', 'message': f'导出失败: {str(e)}'}, status=500)
    
    def import_from_csv(self, file):
        """从 CSV 文件导入代币"""
        imported = 0
        skipped = 0
        errors = []
        
        # 读取 CSV 文件
        decoded_file = file.read().decode('utf-8').splitlines()
        reader = csv.DictReader(decoded_file)
        
        # 获取所有分类的映射
        categories = {cat.code: cat for cat in TokenCategory.objects.all()}
        
        for row in reader:
            try:
                # 检查必填字段
                if not row.get('chain') or not row.get('address') or not row.get('symbol'):
                    errors.append(f"行 {reader.line_num}: 缺少必填字段")
                    skipped += 1
                    continue
                
                # 查找分类
                category = None
                if row.get('category') and row['category'] in categories:
                    category = categories[row['category']]
                
                # 更新或创建代币
                token, created = Token.objects.update_or_create(
                    chain=row['chain'],
                    address=row['address'],
                    defaults={
                        'name': row.get('name', row['symbol']),
                        'symbol': row['symbol'],
                        'decimals': int(row.get('decimals', 0)),
                        'logo': row.get('logo', ''),
                        'category': category,
                        'is_native': row.get('is_native', '').lower() in ('true', 'yes', '1'),
                        'is_visible': row.get('is_visible', '').lower() in ('true', 'yes', '1', ''),
                        'is_recommended': row.get('is_recommended', '').lower() in ('true', 'yes', '1')
                    }
                )
                
                imported += 1
            except Exception as e:
                errors.append(f"行 {reader.line_num}: {str(e)}")
                skipped += 1
        
        return {
            'imported': imported,
            'skipped': skipped,
            'errors': errors
        }
    
    def import_from_json(self, file):
        """从 JSON 文件导入代币"""
        imported = 0
        skipped = 0
        errors = []
        
        try:
            # 读取 JSON 文件
            data = json.loads(file.read().decode('utf-8'))
            
            # 获取所有分类的映射
            categories = {cat.code: cat for cat in TokenCategory.objects.all()}
            
            # 处理数据
            for i, item in enumerate(data):
                try:
                    # 检查必填字段
                    if not item.get('chain') or not item.get('address') or not item.get('symbol'):
                        errors.append(f"项目 {i+1}: 缺少必填字段")
                        skipped += 1
                        continue
                    
                    # 查找分类
                    category = None
                    if item.get('category') and item['category'] in categories:
                        category = categories[item['category']]
                    
                    # 更新或创建代币
                    token, created = Token.objects.update_or_create(
                        chain=item['chain'],
                        address=item['address'],
                        defaults={
                            'name': item.get('name', item['symbol']),
                            'symbol': item['symbol'],
                            'decimals': int(item.get('decimals', 0)),
                            'logo': item.get('logo', ''),
                            'category': category,
                            'is_native': item.get('is_native', False),
                            'is_visible': item.get('is_visible', True),
                            'is_recommended': item.get('is_recommended', False)
                        }
                    )
                    
                    imported += 1
                except Exception as e:
                    errors.append(f"项目 {i+1}: {str(e)}")
                    skipped += 1
            
        except json.JSONDecodeError:
            return {
                'imported': 0,
                'skipped': 0,
                'errors': ['无效的 JSON 文件']
            }
        
        return {
            'imported': imported,
            'skipped': skipped,
            'errors': errors
        }
    
    def save_model(self, request, obj, form, change):
        """保存模型时处理批量导入"""
        if not change and 'bulk_import' in form.cleaned_data and form.cleaned_data['bulk_import']:
            # 处理批量导入
            file = form.cleaned_data['bulk_import']
            if file.name.endswith('.csv'):
                result = self.import_from_csv(file)
            elif file.name.endswith('.json'):
                result = self.import_from_json(file)
            else:
                messages.error(request, '不支持的文件类型，请上传 CSV 或 JSON 文件')
                return
            
            messages.success(request, f'成功导入 {result["imported"]} 个代币，跳过 {result["skipped"]} 个代币')
            if result['errors']:
                messages.warning(request, f'导入过程中有 {len(result["errors"])} 个错误')
                for error in result['errors'][:5]:  # 只显示前5个错误
                    messages.warning(request, error)
                if len(result['errors']) > 5:
                    messages.warning(request, '...')
            return
        
        super().save_model(request, obj, form, change)

    def display_logo(self, obj):
        """在列表中显示代币logo"""
        if obj.logo:
            if obj.logo.startswith('http'):
                logo_url = obj.logo
            else:
                logo_url = f"{settings.MEDIA_URL}{obj.logo}"
            return format_html('<img src="{}" width="32" height="32" style="border-radius: 50%;" />', logo_url)
        return '-'
    
    display_logo.short_description = 'Logo'  # 列标题

    def sync_token_metadata(self, modeladmin, request, queryset):
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

    def ai_recommend_view(self, request, token_id):
        """单个代币的 AI 推荐视图"""
        return JsonResponse({'status': 'success', 'message': 'AI 推荐功能暂未实现'})

    def ai_recommend_batch_view(self, request):
        """批量 AI 推荐视图"""
        return JsonResponse({'status': 'success', 'message': 'AI 批量推荐功能暂未实现'})

    def fetch_ai_recommendations(self, modeladmin, request, queryset):
        """获取 AI 推荐"""
        self.message_user(request, 'AI 推荐功能暂未实现')
    fetch_ai_recommendations.short_description = '获取 AI 推荐'

    def fetch_token_metadata(self, request):
        """获取代币元数据"""
        try:
            chain = request.GET.get('chain')
            address = request.GET.get('address')
            
            if not chain or not address:
                return JsonResponse({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=400)

            # 根据链类型获取对应的代币信息服务
            token_info_service = ChainServiceFactory.get_token_info_service(chain)
            if not token_info_service:
                return JsonResponse({
                    'status': 'error',
                    'message': f'不支持的链类型: {chain}'
                }, status=400)

            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 获取代币元数据
            token_data = loop.run_until_complete(token_info_service.get_token_metadata(address))
            loop.close()

            if not token_data:
                return JsonResponse({
                    'status': 'error',
                    'message': '获取代币元数据失败'
                }, status=400)

            return JsonResponse({
                'status': 'success',
                'data': token_data
            })

        except Exception as e:
            logger.error(f"获取代币元数据失败: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)

    def make_recommended(self, request, queryset):
        """将选中的代币设为推荐"""
        queryset.update(is_recommended=True)
        self.message_user(request, f'已将 {queryset.count()} 个代币设为推荐')
    make_recommended.short_description = '设为推荐代币'

    def remove_recommended(self, request, queryset):
        """取消选中代币的推荐状态"""
        queryset.update(is_recommended=False)
        self.message_user(request, f'已取消 {queryset.count()} 个代币的推荐')
    remove_recommended.short_description = '取消推荐'

    def toggle_recommend_view(self, request, token_id):
        """切换代币的推荐状态"""
        if request.method != 'POST':
            return JsonResponse({
                'status': 'error',
                'message': '不支持的请求方法'
            }, status=405)

        try:
            token = Token.objects.get(id=token_id)
            token.is_recommended = not token.is_recommended
            token.save()

            # 返回更新后的状态
            return JsonResponse({
                'status': 'success',
                'is_recommended': token.is_recommended,
                'message': '推荐状态已更新'
            })
        except Token.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': '代币不存在'
            }, status=404)
        except Exception as e:
            logger.error(f"切换推荐状态失败: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': f'操作失败: {str(e)}'
            }, status=500)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        # 添加额外的上下文数据
        extra_context['show_recommend_button'] = True
        return super().changelist_view(request, extra_context)

    def get_list_display(self, request):
        list_display = list(super().get_list_display(request))
        if 'is_recommended' not in list_display:
            list_display.append('is_recommended')
        return list_display

    def sync_tasks(self, request):
        """同步任务配置"""
        try:
            call_command('sync_tasks')
            self.message_user(request, '任务同步成功！', messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f'任务同步失败：{str(e)}', messages.ERROR)
        return redirect('..')

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

@admin.register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
    """任务历史管理"""
    list_display = ['device_id', 'task', 'completed_at', 'points_awarded']
    list_filter = ['completed_at', 'points_awarded']
    search_fields = ['device_id', 'task__name']

@admin.register(ShareTaskToken)
class ShareTaskTokenAdmin(admin.ModelAdmin):
    list_display = ['token', 'points', 'daily_limit', 'is_active']
    list_filter = ['is_active']
    search_fields = ['token__name', 'token__symbol']

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
