from rest_framework import serializers
from django.conf import settings
import os
import random
import string
from PIL import Image, ImageDraw
import io
import base64
from django.core.files.base import ContentFile
from django.utils import timezone
from mnemonic import Mnemonic
from io import BytesIO

from .models import Wallet, Token, PaymentPassword, Chain

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
    avatar_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Wallet
        fields = ['id', 'device_id', 'name', 'chain', 'address', 'avatar_url', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def get_avatar_url(self, obj):
        """获取头像URL"""
        if not obj.avatar:
            # 生成随机头像
            avatar_image = generate_avatar()
            avatar_io = BytesIO()
            avatar_image.save(avatar_io, format='PNG')
            avatar_file = ContentFile(avatar_io.getvalue())
            
            # 保存头像
            obj.avatar.save(f'wallet_avatar_{obj.pk}.png', avatar_file, save=True)
        
        if settings.DEBUG:
            return f"http://192.168.3.16:8000{obj.avatar.url}"
        return f"https://{settings.DOMAIN}{obj.avatar.url}"

class WalletCreateSerializer(serializers.ModelSerializer):
    """钱包创建序列化器"""
    class Meta:
        model = Wallet
        fields = ['device_id', 'name', 'chain', 'address', 'encrypted_private_key']

class WalletUpdateSerializer(serializers.ModelSerializer):
    """钱包更新序列化器"""
    class Meta:
        model = Wallet
        fields = ['name']

class WalletImportSerializer(serializers.Serializer):
    """钱包导入序列化器"""
    device_id = serializers.CharField(max_length=100)
    name = serializers.CharField(max_length=100)
    chain = serializers.CharField(max_length=10)
    private_key = serializers.CharField()
    payment_password = serializers.CharField(write_only=True)
    
    def validate_chain(self, value):
        """验证链类型"""
        from .models import Chain
        if value not in [choice[0] for choice in Chain.CHOICES]:
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
    payment_password = serializers.CharField(write_only=True)
    
    def validate_payment_password(self, value):
        """验证支付密码"""
        if len(value) < 6:
            raise serializers.ValidationError('支付密码长度不能小于6位')
        return value

class ChainSelectionSerializer(serializers.Serializer):
    """链选择序列化器"""
    device_id = serializers.CharField(max_length=100)
    chain = serializers.CharField(max_length=10)
    
    def validate_chain(self, value):
        """验证链类型"""
        from .models import Chain
        if value not in [choice[0] for choice in Chain.CHOICES]:
            raise serializers.ValidationError('不支持的链类型')
        return value

class VerifyMnemonicSerializer(serializers.Serializer):
    """助记词验证序列化器"""
    device_id = serializers.CharField(max_length=100)
    chain = serializers.CharField(max_length=10)
    mnemonic = serializers.CharField()
    
    def validate_chain(self, value):
        """验证链类型"""
        from .models import Chain
        if value not in [choice[0] for choice in Chain.CHOICES]:
            raise serializers.ValidationError('不支持的链类型')
        return value
    
    def validate_mnemonic(self, value):
        """验证助记词格式"""
        try:
            Mnemonic("english").check(value)
            return value
        except Exception as e:
            raise serializers.ValidationError('助记词格式错误')

class TokenSerializer(serializers.ModelSerializer):
    """代币序列化器"""
    class Meta:
        model = Token
        fields = ['id', 'chain', 'address', 'name', 'symbol', 'decimals', 'logo', 'is_active']
