from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from ..models import Task, TaskHistory, UserPoints, ReferralRelationship, ShareTaskToken, PointsHistory
from ..serializers import ShareTaskTokenSerializer, TaskSerializer
import logging
from django.conf import settings
from django.db.models import Count
from ..utils.twitter import TwitterValidator
from django.core.cache import cache

logger = logging.getLogger(__name__)

class TaskViewSet(viewsets.ViewSet):
    """任务系统视图集"""
    
    @action(detail=False, methods=['POST'])
    def daily_check_in(self, request):
        """每日签到"""
        try:
            device_id = request.data.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': 'Device ID is required'
                }, status=400)

            # 获取签到任务
            try:
                task = Task.objects.get(code='DAILY_CHECK_IN', is_active=True)
            except Task.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': 'Daily check-in task not found'
                }, status=404)

            # 检查今日是否已签到
            today = timezone.now().date()
            today_check_in = TaskHistory.objects.filter(
                device_id=device_id,
                task=task,
                completed_at__date=today
            ).exists()

            if today_check_in:
                return Response({
                    'status': 'error',
                    'message': 'Already checked in today'
                }, status=400)

            # 记录签到历史
            TaskHistory.objects.create(
                device_id=device_id,
                task=task,
                points_awarded=task.points
            )

            # 添加积分
            user_points = UserPoints.get_or_create_user_points(device_id)
            user_points.add_points(
                points=task.points,
                action_type='DAILY_CHECK_IN',
                description='Daily check-in reward',
                related_device_id=device_id
            )

            return Response({
                'status': 'success',
                'message': f'Check-in successful! Earned {task.points} points',
                'data': {
                    'points_awarded': task.points
                }
            })

        except Exception as e:
            logger.error(f"Daily check-in failed: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': 'Check-in failed'
            }, status=500)
    
    @action(detail=False, methods=['GET'])
    def list_tasks(self, request):
        """Get task list"""
        try:
            device_id = request.query_params.get('device_id')
            logger.info("[list_tasks] Starting for device_id: %s", device_id)

            if not device_id:
                return Response({
                    'status': 'error',
                    'message': 'Device ID is required'
                }, status=400)

            # 1. Get all active tasks except SHARE_TOKEN
            tasks = Task.objects.filter(
                is_active=True
            ).exclude(
                code='SHARE_TOKEN'
            )
            logger.info("[list_tasks] Found %d active tasks", tasks.count())
            
            # 2. Get task history records
            task_histories = TaskHistory.objects.filter(
                device_id=device_id
            ).select_related('task')
            
            # Print original query and parameters
            logger.info("[list_tasks] Device ID for query: %s", device_id)
            logger.info("[list_tasks] Found %d history records", task_histories.count())
            
            # Print each history record
            for history in task_histories:
                logger.info(
                    "[list_tasks] History: task_id=%d, device_id=%s, task_code=%s, completed_at=%s",
                    history.task_id,
                    history.device_id,
                    history.task.code,
                    history.completed_at
                )
            
            # 3. Get today's records
            today = timezone.now().date()
            today_histories = task_histories.filter(completed_at__date=today)
            
            # 4. Get completed non-repeatable tasks
            completed_tasks = task_histories.filter(
                task__is_repeatable=False
            ).values_list('task_id', flat=True).distinct()
            
            logger.info("[list_tasks] Completed task IDs: %s", list(completed_tasks))
            
            # 5. Prepare task data
            task_list = []
            for task in tasks:
                task_data = TaskSerializer(task).data
                
                # Check completion status
                if task.is_repeatable:
                    is_completed = today_histories.filter(task_id=task.id).exists()
                else:
                    is_completed = task.id in completed_tasks
                
                task_data['is_completed'] = is_completed
                logger.info(
                    "[list_tasks] Task %s (ID: %d): is_repeatable=%s, is_completed=%s, in_completed_tasks=%s",
                    task.code,
                    task.id,
                    task.is_repeatable,
                    is_completed,
                    task.id in completed_tasks
                )
                
                # Get today's completion count
                today_count = today_histories.filter(task_id=task.id).count()
                task_data['today_count'] = today_count
                
                task_list.append(task_data)
            
            return Response({
                'status': 'success',
                'data': task_list
            })
            
        except Exception as e:
            logger.error("[list_tasks] Error: %s", str(e), exc_info=True)
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)

    @action(detail=False, methods=['GET'])
    def check_task_status(self, request):
        """Check task completion status"""
        try:
            device_id = request.query_params.get('device_id')
            task_code = request.query_params.get('task_code')
            
            if not device_id or not task_code:
                return Response({
                    'status': 'error',
                    'message': 'Missing required parameters'
                }, status=400)
            
            try:
                task = Task.objects.get(code=task_code)
            except Task.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': 'Task not found'
                }, status=404)
            
            # Check task completion status
            if task.is_repeatable:
                today = timezone.now().date()
                is_completed = TaskHistory.objects.filter(
                    device_id=device_id,
                    task_id=task.id,
                    completed_at__date=today
                ).exists()
            else:
                is_completed = TaskHistory.objects.filter(
                    device_id=device_id,
                    task_id=task.id
                ).exists()
            
            return Response({
                'status': 'success',
                'data': {
                    'is_completed': is_completed
                }
            })
            
        except Exception as e:
            logger.error(f"[check_task_status] Error: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)
    
    @action(detail=False, methods=['POST'])
    def complete_task(self, request):
        """完成任务"""
        try:
            device_id = request.data.get('device_id')
            task_code = request.data.get('task_code')
            
            if not device_id or not task_code:
                return Response({
                    'status': 'error',
                    'message': 'Missing required parameters'
                }, status=400)
            
            # 获取任务
            try:
                task = Task.objects.get(code=task_code, is_active=True)
            except Task.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': 'Task not found'
                }, status=404)
            
            # 检查是否已完成（对于不可重复的任务）
            if not task.is_repeatable:
                completed = TaskHistory.objects.filter(
                    device_id=device_id,
                    task=task
                ).exists()
                if completed:
                    return Response({
                        'status': 'error',
                        'message': f'Task {task.name} already completed'
                    }, status=400)
            
            # 检查今日完成次数
            today = timezone.now().date()
            today_count = TaskHistory.objects.filter(
                device_id=device_id,
                task=task,
                completed_at__date=today
            ).count()
            
            if today_count >= task.daily_limit:
                return Response({
                    'status': 'error',
                    'message': 'Daily limit reached'
                }, status=400)
            
            # 记录任务完成
            TaskHistory.objects.create(
                device_id=device_id,
                task=task,
                points_awarded=task.points
            )
            
            # 添加积分
            user_points = UserPoints.get_or_create_user_points(device_id)
            user_points.add_points(
                points=task.points,
                action_type='TASK_COMPLETE',
                description=f'Completed task: {task.name}',
                related_device_id=device_id
            )
            
            return Response({
                'status': 'success',
                'message': f'Task completed! Earned {task.points} points',
                'data': {
                    'points_awarded': task.points
                }
            })
            
        except Exception as e:
            logger.error(f"Task completion failed: {str(e)}")
            return Response({
                'status': 'error',
                'message': 'Task completion failed'
            }, status=500)

    @action(detail=False, methods=['POST'], url_path='verify_share')
    def verify_share(self, request):
        """验证代币分享"""
        try:
            device_id = request.data.get('device_id')
            tweet_id = request.data.get('tweet_id')
            token_address = request.data.get('token_address')

            # 1. 基本参数验证
            if not all([device_id, tweet_id, token_address]):
                return Response({
                    'status': 'error',
                    'message': 'Missing required parameters'
                }, status=400)

            # 2. 查找分享任务
            share_task = ShareTaskToken.objects.filter(
                token__address=token_address,
                is_active=True
            ).first()

            if not share_task:
                return Response({
                    'status': 'error',
                    'message': 'Invalid share task'
                }, status=400)

            # 3. 检查今日完成次数
            today = timezone.now().date()
            today_count = TaskHistory.objects.filter(
                device_id=device_id,
                task__share_token_tasks=share_task,
                completed_at__date=today
            ).count()

            if today_count >= share_task.daily_limit:
                return Response({
                    'status': 'error',
                    'message': 'Daily limit reached'
                }, status=400)

            # 4. 记录任务完成
            task_history = TaskHistory.objects.create(
                device_id=device_id,
                task=share_task.task,
                points_awarded=share_task.points,
                extra_data={
                    'token_address': token_address,
                    'tweet_id': tweet_id
                }
            )

            # 5. 添加积分
            user_points = UserPoints.get_or_create_user_points(device_id)
            user_points.add_points(
                points=share_task.points,
                action_type='SHARE_TOKEN',
                description=f"Share token {share_task.token.symbol}",
                related_device_id=device_id
            )

            # 6. 返回成功响应
            return Response({
                'status': 'success',
                'message': f'Share verified, earned {share_task.points} points',
                'data': {
                    'points_awarded': share_task.points
                }
            })

        except Exception as e:
            logger.error(f"Share verification failed: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': 'Share verification failed'
            }, status=500)

class ShareTaskTokenViewSet(viewsets.ModelViewSet):
    """分享任务代币管理"""
    queryset = ShareTaskToken.objects.all()
    serializer_class = ShareTaskTokenSerializer
    twitter_validator = TwitterValidator()

    @action(detail=False, methods=['GET'])
    def available_tasks(self, request):
        """Get available share tasks"""
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response({
                'status': 'error',
                'message': 'Device ID is required'
            }, status=400)

        try:
            # 获取所有活跃的分享任务
            share_tasks = ShareTaskToken.objects.filter(
                is_active=True
            ).select_related('token')  # 移除 task 关联

            # 获取用户今日已完成的分享记录
            today = timezone.now().date()
            completed_shares = TaskHistory.objects.filter(
                device_id=device_id,
                completed_at__date=today,
                extra_data__has_key='token_address'  # 确保是分享代币的记录
            ).values('extra_data__token_address').annotate(
                share_count=Count('id')
            )

            # 构建完成次数字典
            completed_counts = {
                share['extra_data__token_address']: share['share_count']
                for share in completed_shares
            }

            # 准备返回数据
            task_list = []
            for share_task in share_tasks:
                token = share_task.token
                today_count = completed_counts.get(token.address, 0)
                
                task_list.append({
                    'id': share_task.id,
                    'token_address': token.address,
                    'token_symbol': token.symbol,
                    'token_name': token.name,
                    'token_logo': token.logo,
                    'points': share_task.points,
                    'daily_limit': share_task.daily_limit,
                    'today_shared': today_count,
                    'can_share': today_count < share_task.daily_limit,
                    'official_tweet_id': share_task.official_tweet_id,
                    'is_active': share_task.is_active,
                    'is_completed': today_count >= share_task.daily_limit
                })

            return Response({
                'status': 'success',
                'data': task_list
            })

        except Exception as e:
            logger.error(f"Failed to get share tasks: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)

    @action(detail=False, methods=['POST'], url_path='verify_share')
    def verify_share(self, request):
        """验证代币分享"""
        try:
            device_id = request.data.get('device_id')
            tweet_id = request.data.get('tweet_id')
            token_address = request.data.get('token_address')

            # 1. 基本参数验证
            if not all([device_id, tweet_id, token_address]):
                return Response({
                    'status': 'error',
                    'message': 'Missing required parameters'
                }, status=400)

            # 2. 查找分享任务
            share_task = ShareTaskToken.objects.filter(
                token__address=token_address,
                is_active=True
            ).first()

            if not share_task:
                return Response({
                    'status': 'error',
                    'message': 'Invalid share task'
                }, status=400)

            # 3. 检查今日完成次数
            today = timezone.now().date()
            today_count = TaskHistory.objects.filter(
                device_id=device_id,
                task__share_token_tasks=share_task,
                completed_at__date=today
            ).count()

            if today_count >= share_task.daily_limit:
                return Response({
                    'status': 'error',
                    'message': 'Daily limit reached'
                }, status=400)

            # 4. 记录任务完成
            task_history = TaskHistory.objects.create(
                device_id=device_id,
                task=share_task.task,
                points_awarded=share_task.points,
                extra_data={
                    'token_address': token_address,
                    'tweet_id': tweet_id
                }
            )

            # 5. 添加积分
            user_points = UserPoints.get_or_create_user_points(device_id)
            user_points.add_points(
                points=share_task.points,
                action_type='SHARE_TOKEN',
                description=f"Share token {share_task.token.symbol}",
                related_device_id=device_id
            )

            # 6. 返回成功响应
            return Response({
                'status': 'success',
                'message': f'Share verified, earned {share_task.points} points',
                'data': {
                    'points_awarded': share_task.points
                }
            })

        except Exception as e:
            logger.error(f"Share verification failed: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': 'Share verification failed'
            }, status=500)

def get_stage_points(task, device_id):
    """获取当前阶段的奖励积分"""
    if task.code != 'INVITE_DOWNLOAD' or not task.stages_config:
        return task.points
        
    # 获取用户已完成的邀请数量
    completed_count = TaskHistory.objects.filter(
        device_id=device_id,
        task=task
    ).count()
    
    # 根据完成数量确定当前阶段的奖励
    stages = task.stages_config.get('stages', [])
    for stage in reversed(stages):
        if completed_count >= stage['target']:
            return stage['points']
            
    return task.points  # 如果没有达到任何阶段，返回基础积分

def complete_task(device_id, task_code):
    """General task completion handler"""
    try:
        task = Task.objects.get(code=task_code)
        
        if not task.is_repeatable:
            completed = TaskHistory.objects.filter(
                device_id=device_id,
                task_id=task.id
            ).exists()
            if completed:
                return False, f"Task '{task.name}' already completed"
        
        today = timezone.now().date()
        today_count = TaskHistory.objects.filter(
            device_id=device_id,
            task_id=task.id,
            completed_at__date=today
        ).count()
        
        if today_count >= task.daily_limit:
            return False, "Daily limit reached"
            
        points = get_stage_points(task, device_id)
            
        task_history = TaskHistory.objects.create(
            device_id=device_id,
            task=task,
            points_awarded=points,
            extra_data={
                'task_code': task_code,
                'task_name': task.name,
                'task_description': task.description
            }
        )
        
        user_points = UserPoints.get_or_create_user_points(device_id)
        user_points.add_points(
            points=points,
            action_type='TASK_COMPLETE',
            description=f"Completed task: {task.name}",
            related_device_id=device_id
        )
        
        return True, f"Task '{task.name}' completed! Earned {points} points"
        
    except Exception as e:
        logger.error(f"[complete_task] Error: {str(e)}", exc_info=True)
        return False, str(e)