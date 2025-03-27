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
    
    @action(detail=False, methods=['GET'])
    def list_tasks(self, request):
        """获取任务列表"""
        try:
            device_id = request.query_params.get('device_id')
            logger.info("[list_tasks] Starting for device_id: %s", device_id)

            if not device_id:
                return Response({
                    'status': 'error',
                    'message': 'Device ID is required'
                }, status=400)

            # 1. 获取所有活跃任务
            tasks = Task.objects.filter(is_active=True)
            logger.info("[list_tasks] Found %d active tasks", tasks.count())
            
            # 2. 获取任务历史记录
            task_histories = TaskHistory.objects.filter(
                device_id=device_id
            ).select_related('task')
            
            # 打印原始查询和参数
            logger.info("[list_tasks] Device ID for query: %s", device_id)
            logger.info("[list_tasks] Found %d history records", task_histories.count())
            
            # 打印每条历史记录
            for history in task_histories:
                logger.info(
                    "[list_tasks] History: task_id=%d, device_id=%s, task_code=%s, completed_at=%s",
                    history.task_id,
                    history.device_id,
                    history.task.code,
                    history.completed_at
                )
            
            # 3. 获取今日记录
            today = timezone.now().date()
            today_histories = task_histories.filter(completed_at__date=today)
            
            # 4. 获取已完成的不可重复任务
            completed_tasks = task_histories.filter(
                task__is_repeatable=False
            ).values_list('task_id', flat=True).distinct()
            
            logger.info("[list_tasks] Completed task IDs: %s", list(completed_tasks))
            
            # 5. 准备任务数据
            task_list = []
            for task in tasks:
                task_data = TaskSerializer(task).data
                
                # 检查完成状态
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
                
                # 获取今日完成次数
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
        """检查任务完成状态"""
        try:
            device_id = request.query_params.get('device_id')
            task_code = request.query_params.get('task_code')
            
            if not device_id or not task_code:
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=400)
            
            try:
                task = Task.objects.get(code=task_code)
            except Task.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': 'Task not found'
                }, status=404)
            
            # 检查任务完成状态
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
            
            success, message = complete_task(device_id, task_code)
            
            return Response({
                'status': 'success' if success else 'error',
                'message': message
            }, status=200 if success else 400)
            
        except Exception as e:
            logger.error("[complete_task] 处理任务出错: %s", str(e), exc_info=True)
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)

class ShareTaskTokenViewSet(viewsets.ModelViewSet):
    """分享任务代币管理"""
    queryset = ShareTaskToken.objects.all()
    serializer_class = ShareTaskTokenSerializer

    @action(detail=False, methods=['GET'])
    def available_tasks(self, request):
        """获取当前可用的分享任务"""
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response({
                'status': 'error',
                'message': 'Device ID is required'
            }, status=400)

        try:
            # 获取当前有效的分享任务
            share_tasks = ShareTaskToken.objects.filter(
                is_active=True
            ).select_related('token')

            # 获取用户今日已分享记录
            today_shares = TaskHistory.objects.filter(
                device_id=device_id,
                task__task_type='SHARE_TOKEN',
                completed_at__date=timezone.now().date()
            ).values('extra_data__token_address').annotate(
                share_count=Count('id')
            )

            # 构建分享记录字典
            share_counts = {
                share['extra_data__token_address']: share['share_count']
                for share in today_shares
            }

            task_list = []
            for share_task in share_tasks:
                # 移除 is_valid() 检查，直接使用 is_active 字段
                if not share_task.is_active:
                    continue

                token = share_task.token
                today_count = share_counts.get(token.address, 0)
                
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
                    'price': token.last_price,
                    'price_change_24h': token.last_price_change,
                })

            return Response({
                'status': 'success',
                'data': task_list
            })

        except Exception as e:
            logger.error(f"获取分享任务列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)

class ShareTaskViewSet(viewsets.ViewSet):
    twitter_validator = TwitterValidator()

    @action(detail=False, methods=['POST'])
    def verify_share(self, request):
        """验证代币分享"""
        try:
            device_id = request.data.get('device_id')
            tweet_id = request.data.get('tweet_id')

            if not all([device_id, tweet_id]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=400)

            # 根据 tweet_id 查找对应的分享任务
            share_task = ShareTaskToken.objects.filter(
                official_tweet_id=tweet_id,
                is_active=True
            ).first()

            if not share_task:
                return Response({
                    'status': 'error',
                    'message': '无效的推文ID或该推文不是官方分享任务'
                }, status=400)

            # 检查今日完成次数
            cache_key = f"share_task_{device_id}_{share_task.token.address}_{timezone.now().date()}"
            today_count = cache.get(cache_key, 0)

            if today_count >= share_task.daily_limit:
                return Response({
                    'status': 'error',
                    'message': '已达到今日分享上限'
                }, status=400)

            # 验证推文
            token_data = {
                'symbol': share_task.token.symbol,
                'name': share_task.token.name,
                'official_tweet_id': share_task.official_tweet_id
            }
            is_valid, message = self.twitter_validator.verify_tweet(tweet_id, token_data)

            if not is_valid:
                return Response({
                    'status': 'error',
                    'message': message
                }, status=400)

            # 记录任务完成
            TaskHistory.objects.create(
                device_id=device_id,
                task=share_task.task,
                points_awarded=share_task.points,
                extra_data={
                    'token_address': share_task.token.address,
                    'tweet_id': tweet_id
                }
            )

            # 添加积分
            user_points = UserPoints.get_or_create_user_points(device_id)
            user_points.add_points(
                points=share_task.points,
                action_type='SHARE_TOKEN',
                description=f"分享代币 {share_task.token.symbol}",
                related_device_id=device_id
            )

            # 更新缓存
            cache.set(cache_key, today_count + 1, timeout=86400)  # 24小时过期

            return Response({
                'status': 'success',
                'message': f'分享验证成功，获得 {share_task.points} 积分'
            })

        except Exception as e:
            logger.error(f"验证分享失败: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': str(e)
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
    """通用的任务完成处理方法"""
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
            extra_data={'task_code': task_code}
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