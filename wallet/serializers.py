from rest_framework import serializers
from .models import (
    Wallet, Token, NFTCollection, Transaction,
    MnemonicBackup, PaymentPassword, TokenIndex,
    TokenIndexSource, TokenIndexMetrics, TokenIndexGrade,
    TokenIndexReport, TokenCategory,
    ReferralRelationship, UserPoints, PointsHistory, ReferralLink,
    Task, TaskHistory, ShareTaskToken
)
from django.conf import settings
from PIL import Image, ImageDraw
import os
from io import BytesIO
from django.core.files.base import ContentFile
import random
import re

def generate_avatar(size=200, bg_color=None):
    """生成简单的随机头像"""
    if bg_color is None:
        # 生成随机颜色
        bg_color = (
            random.randint(50, 200),
            random.randint(50, 200),
            random.randint(50, 200)
        )
    
    # 创建图像
    image = Image.new('RGB', (size, size), bg_color) # type: ignore
    draw = ImageDraw.Draw(image)
    
    # 生成随机图案
    for _ in range(10):
        x1 = random.randint(0, size)
        y1 = random.randint(0, size)
        x2 = random.randint(0, size)
        y2 = random.randint(0, size)
        color = (
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255)
        )
        draw.line([(x1, y1), (x2, y2)], fill=color, width=5)
    
    return image

class WalletSerializer(serializers.ModelSerializer):
    """钱包序列化器"""
    avatar = serializers.SerializerMethodField()
    
    class Meta:
        model = Wallet
        fields = [
            'id', 'device_id', 'name', 'chain', 'address',
            'avatar', 'is_active', 'is_watch_only', 'is_imported',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_avatar(self, obj):
        """获取头像 URL"""
        if obj.avatar:
            # 根据 DEBUG 配置返回不同的 URL
            if settings.DEBUG:
                return f'{settings.DEVELOPMENT_DOMAIN}{obj.avatar.url}'
            else:
                return f'{settings.PRODUCTION_DOMAIN}{obj.avatar.url}'
        return None
    
class MnemonicBackupSerializer(serializers.ModelSerializer):
    """助记词备份序列化器"""
    
    class Meta:
        model = MnemonicBackup
        fields = ['id', 'device_id', 'encrypted_mnemonic', 'created_at']
        read_only_fields = ['id', 'created_at']

class WalletCreateSerializer(serializers.ModelSerializer):
    """钱包创建序列化器"""
    referral_info = serializers.JSONField(required=False)
    
    class Meta:
        model = Wallet
        fields = [
            'device_id', 'name', 'chain', 'address',
            'encrypted_private_key', 'avatar', 'is_watch_only',
            'is_imported', 'referral_info'
        ]

class WalletUpdateSerializer(serializers.Serializer):
    """钱包更新序列化器"""
    name = serializers.CharField(max_length=50)
    is_active = serializers.BooleanField(required=False)

class WalletImportSerializer(serializers.Serializer):
    """钱包导入序列化器"""
    chain = serializers.CharField(max_length=10)  # 改为 CharField，不使用 ChoiceField
    name = serializers.CharField(max_length=50)
    mnemonic = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)
    device_id = serializers.CharField(max_length=100)

    def validate_chain(self, value):
        """验证链类型"""
        if value not in settings.SUPPORTED_CHAINS:
            raise serializers.ValidationError('不支持的链类型')
        return value

class PaymentPasswordSerializer(serializers.ModelSerializer):
    """支付密码序列化器"""
    class Meta:
        model = PaymentPassword
        fields = ['device_id', 'encrypted_password']

class WalletSetupSerializer(serializers.Serializer):
    """钱包设置序列化器"""
    device_id = serializers.CharField(max_length=100)
    payment_password = serializers.CharField()
    payment_password_confirm = serializers.CharField()

    def validate(self, data):
        """验证支付密码和确认密码是否匹配"""
        payment_password = data.get('payment_password')
        payment_password_confirm = data.get('payment_password_confirm')
        
        if not payment_password:
            raise serializers.ValidationError({'payment_password': '请输入支付密码'})
        if not payment_password_confirm:
            raise serializers.ValidationError({'payment_password_confirm': '请输入确认密码'})
        
        if payment_password != payment_password_confirm:
            raise serializers.ValidationError({'payment_password_confirm': '两次输入的密码不一致'})
        
        if not re.match(r'^\d{6}$', payment_password):
            raise serializers.ValidationError({'payment_password': '支付密码必须是6位数字'})
        
        return data 

class ChainSelectionSerializer(serializers.Serializer):
    """链选择序列化器"""
    device_id = serializers.CharField(max_length=100)
    chain = serializers.CharField(max_length=20)

    def validate_chain(self, value):
        """验证链类型
        
        支持的链标识符:
        - ETH: 以太坊主网
        - BSC: 币安智能链
        - MATIC: Polygon主网
        - AVAX: Avalanche C-Chain
        - BASE: Base主网
        - ARBITRUM: Arbitrum One
        - OPTIMISM: Optimism主网
        - SOL: Solana主网
        - BTC: 比特币主网 (即将支持)
        """
        # 获取支持的链列表
        supported_chains = {
            'ETH': {'status': 'active'},
            'BSC': {'status': 'active'},
            'MATIC': {'status': 'active'},
            'AVAX': {'status': 'active'},
            'BASE': {'status': 'active'},
            'ARBITRUM': {'status': 'active'},
            'OPTIMISM': {'status': 'active'},
            'SOL': {'status': 'active'},
            'BTC': {'status': 'coming_soon'}
        }
        
        if value not in supported_chains:
            raise serializers.ValidationError('不支持的链类型')
            
        if supported_chains[value]['status'] == 'coming_soon':
            raise serializers.ValidationError(f"{value} 即将支持")
            
        return value

class ReferralLinkSerializer(serializers.ModelSerializer):
    """推荐链接序列化器"""
    full_link = serializers.SerializerMethodField()
    
    class Meta:
        model = ReferralLink
        fields = ['code', 'clicks', 'created_at', 'full_link']
        read_only_fields = ['code', 'clicks', 'created_at']
    
    def get_full_link(self, obj):
        """获取完整的推荐链接"""
        # 根据 DEBUG 配置返回不同的基础 URL
        base_url = f"{settings.DEVELOPMENT_DOMAIN}/" if settings.DEBUG else f"{settings.PRODUCTION_DOMAIN}/"
        return f"{base_url}?ref={obj.code}"

class ReferralRelationshipSerializer(serializers.ModelSerializer):
    """Referral relationship serializer"""
    status = serializers.SerializerMethodField()
    
    class Meta:
        model = ReferralRelationship
        fields = ['referred_device_id', 'download_completed', 'wallet_created', 
                  'created_at', 'status']
        read_only_fields = ['referred_device_id', 'download_completed', 'wallet_created', 
                           'created_at', 'status']
    
    def get_status(self, obj):
        """Get referral status"""
        if obj.wallet_created:
            return "Completed"
        elif obj.download_completed:
            return "Downloaded, wallet not created"
        else:
            return "Incomplete"

class UserPointsSerializer(serializers.ModelSerializer):
    """用户积分序列化器"""
    class Meta:
        model = UserPoints
        fields = ['device_id', 'total_points', 'created_at', 'updated_at']
        read_only_fields = ['device_id', 'total_points', 'created_at', 'updated_at']

class PointsHistorySerializer(serializers.ModelSerializer):
    """Points history serializer"""
    action_display = serializers.SerializerMethodField()
    
    class Meta:
        model = PointsHistory
        fields = ['points', 'action_type', 'action_display', 'description', 
                  'related_device_id', 'created_at']
        read_only_fields = ['points', 'action_type', 'action_display', 'description', 
                           'related_device_id', 'created_at']
    
    def get_action_display(self, obj):
        """Get action type display name"""
        return dict(PointsHistory.ACTION_TYPES).get(obj.action_type, obj.action_type)

class ReferralStatsSerializer(serializers.Serializer):
    """推荐统计序列化器"""
    total_referrals = serializers.IntegerField()
    total_points = serializers.IntegerField()
    download_points = serializers.IntegerField()

class TaskSerializer(serializers.ModelSerializer):
    """任务序列化器"""
    class Meta:
        model = Task
        fields = [
            'id', 'name', 'code', 'description', 
            'points', 'daily_limit', 'is_repeatable',
            'is_active', 'stages_config'
        ]

class TaskHistorySerializer(serializers.ModelSerializer):
    """任务历史记录序列化器"""
    task = TaskSerializer()
    
    class Meta:
        model = TaskHistory
        fields = ['task', 'device_id', 'completed_at', 'points_awarded']

class ShareTaskTokenSerializer(serializers.ModelSerializer):
    token_symbol = serializers.CharField(source='token.symbol', read_only=True)
    token_name = serializers.CharField(source='token.name', read_only=True)
    token_logo = serializers.URLField(source='token.logo', read_only=True)
    token_price = serializers.CharField(source='token.last_price', read_only=True)
    token_price_change = serializers.CharField(source='token.last_price_change', read_only=True)

    class Meta:
        model = ShareTaskToken
        fields = ['id', 'token', 'token_symbol', 'token_name', 'token_logo', 
                 'token_price', 'token_price_change', 'points', 'daily_limit', 
                 'is_active', 'start_time', 'end_time']

class TokenSerializer(serializers.ModelSerializer):
    """代币序列化器"""
    logo = serializers.SerializerMethodField()

    class Meta:
        model = Token
        fields = [
            'id',
            'chain',
            'address',
            'name',
            'symbol',
            'decimals',
            'logo',
            'website',
            'twitter',
            'telegram',
            'discord',
            'description',
            'total_supply',
            'is_verified',
            'is_recommended',
            'is_visible',
            'created_at',
            'updated_at'
        ]

    def get_logo(self, obj):
        """返回完整的logo URL"""
        if obj.logo:
            if obj.logo.startswith('http'):
                return obj.logo
            return f"{settings.MEDIA_URL}{obj.logo}"
        return None
