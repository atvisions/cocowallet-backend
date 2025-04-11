"""钱包管理后台"""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import path
from django.template.response import TemplateResponse
from django.http import JsonResponse
from django import forms
import asyncio
import logging
from django.contrib.auth.models import User, Group
from .models import (
    Wallet, Transaction, Token, HiddenToken, PaymentPassword
)
from tasks.models import (
    ReferralRelationship, ReferralLink, UserPoints, PointsHistory, Task, TaskHistory, ShareTaskToken
)

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
        return [
            ('0', '0'),
            ('6', '6'),
            ('8', '8'),
            ('9', '9'),
            ('18', '18'),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(decimals=int(self.value()))
        return queryset

class ChainFilter(admin.SimpleListFilter):
    """链筛选器"""
    title = '链'
    parameter_name = 'chain'

    def lookups(self, request, model_admin):
        return [
            ('ETH', 'Ethereum'),
            ('BSC', 'BNB Chain'),
            ('MATIC', 'Polygon'),
            ('SOL', 'Solana'),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(chain=self.value())
        return queryset

class TokenAdminForm(forms.ModelForm):
    class Meta:
        model = Token
        fields = '__all__'
        exclude = ['is_recommended']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['address'].widget.attrs['readonly'] = True
            self.fields['chain'].widget.attrs['readonly'] = True

@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    """代币管理"""
    form = TokenAdminForm
    
    def logo_img(self, obj):
        """显示代币logo"""
        if obj.logo:
            return format_html('<img src="{}" style="width: 32px; height: 32px; border-radius: 50%;" />', obj.logo)
        return '-'
    logo_img.short_description = 'Logo'

    list_display = ('logo_img', 'symbol', 'name', 'chain', 'address', 'is_verified', 'is_visible', 'is_recommended')
    list_filter = ('chain', 'is_verified', 'is_recommended', 'is_visible')
    search_fields = ('symbol', 'name', 'address')
    list_editable = ['is_verified', 'is_visible', 'is_recommended']
    readonly_fields = ('created_at', 'updated_at')

    class Media:
        css = {
            'all': ('admin/css/token_sync.css',)
        }
        js = (
            'admin/js/token_sync.js',
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('sync/<str:address>/', self.admin_site.admin_view(self.sync_metadata_view), name='token_sync'),
        ]
        return custom_urls + urls

    def sync_metadata_view(self, request, address):
        if request.method == 'POST':
            try:
                from .management.commands.sync_token_metadata import Command
                command = Command()
                command.handle(address=address)
                return JsonResponse({'status': 'success'})
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
        
        context = dict(
            self.admin_site.each_context(request),
            title='同步代币元数据',
            address=address,
        )
        return TemplateResponse(request, 'admin/wallet/token/sync.html', context)

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['name', 'device_id', 'chain', 'address', 'is_active']
    search_fields = ['name', 'device_id', 'address']
    list_filter = ['chain', 'is_active']

    class Meta:
        verbose_name = 'Wallet'
        verbose_name_plural = 'Wallets'

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['tx_hash', 'get_chain', 'tx_type', 'status', 'from_address', 'to_address', 'amount', 'block_timestamp']
    list_filter = ['wallet__chain', 'tx_type', 'status']
    search_fields = ['tx_hash', 'from_address', 'to_address']
    readonly_fields = ['created_at']
    
    def get_chain(self, obj):
        return obj.wallet.chain
    get_chain.short_description = '链'
    get_chain.admin_order_field = 'wallet__chain'

@admin.register(PaymentPassword)
class PaymentPasswordAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'created_at']
    search_fields = ['device_id']

    class Meta:
        verbose_name = 'Payment Password'
        verbose_name_plural = 'Payment Passwords'

@admin.register(ReferralRelationship)
class ReferralRelationshipAdmin(admin.ModelAdmin):
    list_display = ['referrer_device_id', 'referred_device_id', 'download_completed']
    list_filter = ['download_completed']
    search_fields = ['referrer_device_id', 'referred_device_id']

    class Meta:
        verbose_name = 'Referral Relationship'
        verbose_name_plural = 'Referral Relationships'

@admin.register(ReferralLink)
class ReferralLinkAdmin(admin.ModelAdmin):
    list_display = ['code', 'clicks', 'created_at']
    search_fields = ['code']

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
                'models': ['Token']
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
admin_site.register(ReferralLink, ReferralLinkAdmin)
admin_site.register(ReferralRelationship, ReferralRelationshipAdmin)
admin_site.register(PaymentPassword, PaymentPasswordAdmin)

# 替换默认的 AdminSite
admin.site = admin_site
