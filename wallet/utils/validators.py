import re
from django.core.exceptions import ValidationError

def validate_device_id(device_id: str) -> None:
    """
    验证设备ID
    
    Args:
        device_id: 设备ID
        
    Raises:
        ValidationError: 如果设备ID无效
    """
    if not device_id:
        raise ValidationError('设备ID不能为空')
    
    # 设备ID格式：平台_32位UUID
    pattern = r'^(android|ios)_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if not re.match(pattern, device_id):
        raise ValidationError('无效的设备ID格式')

def validate_payment_password(password: str) -> None:
    """
    验证支付密码
    
    Args:
        password: 支付密码
        
    Raises:
        ValidationError: 如果支付密码无效
    """
    if not password:
        raise ValidationError('支付密码不能为空')
    
    # 支付密码必须是6位数字
    if not re.match(r'^\d{6}$', password):
        raise ValidationError('支付密码必须是6位数字') 