from functools import wraps
from rest_framework.response import Response
from rest_framework import status
import logging
from typing import Any, Callable
from .models import PaymentPassword
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)

def async_to_sync_api(func):
    """装饰器：将异步API转换为同步API"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        return async_to_sync(func)(*args, **kwargs)
    return wrapper

def verify_payment_password():
    """验证支付密码的装饰器
    
    用法:
    @verify_payment_password()
    async def your_view(self, request, ...):
        # 密码验证通过后的逻辑
        pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(view_instance: Any, request: Any, *args: Any, **kwargs: Any) -> Response:
            try:
                # 从请求中获取设备ID和支付密码
                if request.method == 'GET':
                    device_id = request.query_params.get('device_id')
                    payment_password = request.query_params.get('payment_password')
                else:
                    device_id = request.data.get('device_id')
                    payment_password = request.data.get('payment_password')
                
                # 检查参数是否完整
                if not device_id or not payment_password:
                    return Response({
                        'status': 'error',
                        'message': '缺少设备ID或支付密码'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 验证支付密码
                is_valid = await PaymentPassword.verify_device_password(device_id, payment_password)
                if not is_valid:
                    return Response({
                        'status': 'error',
                        'message': '支付密码错误'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 密码验证通过，继续执行原函数
                return await func(view_instance, request, *args, **kwargs)
                
            except Exception as e:
                logger.error(f"验证支付密码时出错: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'验证支付密码失败: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        return wrapper
    return decorator 