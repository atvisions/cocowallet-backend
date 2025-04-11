from functools import wraps
from rest_framework.response import Response
from rest_framework import status
import logging
from typing import Any, Callable
from .models import Task, TaskHistory, UserPoints
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

def check_task_completion():
    """检查任务完成状态的装饰器
    
    用法:
    @check_task_completion()
    async def your_view(self, request, ...):
        # 任务检查通过后的逻辑
        pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(view_instance: Any, request: Any, *args: Any, **kwargs: Any) -> Response:
            try:
                # 从请求中获取设备ID和任务代码
                if request.method == 'GET':
                    device_id = request.query_params.get('device_id')
                    task_code = request.query_params.get('task_code')
                else:
                    device_id = request.data.get('device_id')
                    task_code = request.data.get('task_code')
                
                # 检查参数是否完整
                if not device_id or not task_code:
                    return Response({
                        'status': 'error',
                        'message': '缺少设备ID或任务代码'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 获取任务
                try:
                    task = await Task.objects.aget(code=task_code, is_active=True)
                except Task.DoesNotExist:
                    return Response({
                        'status': 'error',
                        'message': '任务不存在或已停用'
                    }, status=status.HTTP_404_NOT_FOUND)
                
                # 检查任务是否已完成
                today = timezone.now().date()
                completed = await TaskHistory.objects.filter(
                    device_id=device_id,
                    task=task,
                    completed_at__date=today
                ).exists()
                
                if completed:
                    return Response({
                        'status': 'error',
                        'message': '今日已完成该任务'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 任务检查通过，继续执行原函数
                return await func(view_instance, request, *args, **kwargs)
                
            except Exception as e:
                logger.error(f"检查任务完成状态时出错: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'检查任务失败: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        return wrapper
    return decorator

def check_daily_limit():
    """检查每日任务限制的装饰器
    
    用法:
    @check_daily_limit()
    async def your_view(self, request, ...):
        # 检查通过后的逻辑
        pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(view_instance: Any, request: Any, *args: Any, **kwargs: Any) -> Response:
            try:
                # 从请求中获取设备ID
                if request.method == 'GET':
                    device_id = request.query_params.get('device_id')
                else:
                    device_id = request.data.get('device_id')
                
                # 检查参数是否完整
                if not device_id:
                    return Response({
                        'status': 'error',
                        'message': '缺少设备ID'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 检查今日任务完成次数
                today = timezone.now().date()
                completed_count = await TaskHistory.objects.filter(
                    device_id=device_id,
                    completed_at__date=today
                ).count()
                
                if completed_count >= 10:  # 假设每日最多完成10个任务
                    return Response({
                        'status': 'error',
                        'message': '今日任务次数已达上限'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 检查通过，继续执行原函数
                return await func(view_instance, request, *args, **kwargs)
                
            except Exception as e:
                logger.error(f"检查每日任务限制时出错: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'检查任务限制失败: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        return wrapper
    return decorator 