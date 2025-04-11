from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny
from django.conf import settings
from django.core.paginator import Paginator
import logging

from ..models import (
    Task, TaskHistory, UserPoints, ReferralRelationship, 
    ShareTaskToken, PointsHistory, ReferralLink
)
from ..serializers import (
    TaskSerializer, ShareTaskTokenSerializer,
    UserPointsSerializer, PointsHistorySerializer
)

logger = logging.getLogger(__name__)

@method_decorator(csrf_exempt, name='dispatch')
class TaskSystemViewSet(viewsets.GenericViewSet):
    """任务系统视图集"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get_referral_stats(self, device_id):
        """获取推荐统计数据"""
        total_referrals = ReferralRelationship.objects.filter(
            referrer_device_id=device_id
        ).count()
        
        # 获取积分统计
        user_points = UserPoints.get_or_create_user_points(device_id)
        total_points = user_points.total_points
        
        # 获取下载积分
        download_points = PointsHistory.objects.filter(
            device_id=device_id,
            action_type='DOWNLOAD_REFERRAL'
        ).aggregate(total=Sum('points'))['total'] or 0
        
        return {
            'total_referrals': total_referrals,
            'total_points': total_points,
            'download_points': download_points
        }

    # 任务相关方法
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
                # 计算下次签到时间（明天 00:00）
                tomorrow = (timezone.now() + timezone.timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                return Response({
                    'status': 'error',
                    'message': 'Already checked in today. Please come back tomorrow.',
                    'next_check_in': tomorrow
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

            # 计算下次签到时间
            next_check_in = (timezone.now() + timezone.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            return Response({
                'status': 'success',
                'message': f'Check-in successful! You earned {task.points} points',
                'data': {
                    'points_awarded': task.points,
                    'next_check_in': next_check_in
                }
            })

        except Exception as e:
            logger.error(f"Daily check-in failed: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': 'Check-in failed. Please try again.'
            }, status=500)

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

            # 获取所有活跃任务
            tasks = Task.objects.filter(
                is_active=True
            ).exclude(
                code='SHARE_TOKEN'
            )

            # 获取任务历史
            task_histories = TaskHistory.objects.filter(
                device_id=device_id
            ).select_related('task')

            # 准备任务列表
            task_list = []
            now = timezone.now()
            today = now.date()
            
            for task in tasks:
                task_data = TaskSerializer(task).data
                
                if task.code == 'DAILY_CHECK_IN':
                    # 检查今日是否已签到
                    is_completed = task_histories.filter(
                        task=task,
                        completed_at__date=today
                    ).exists()
                    
                    if is_completed:
                        # 设置下次可用时间为明天 00:00
                        next_available = (now + timezone.timedelta(days=1)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                        task_data['next_available'] = next_available.isoformat()
                else:
                    # 其他任务的逻辑
                    if task.is_repeatable:
                        is_completed = task_histories.filter(
                            task=task,
                            completed_at__date=today
                        ).exists()
                    else:
                        is_completed = task_histories.filter(
                            task=task
                        ).exists()
                
                task_data['is_completed'] = is_completed
                task_list.append(task_data)

            return Response({
                'status': 'success',
                'data': task_list
            })
            
        except Exception as e:
            logger.error("[list_tasks] Error: %s", str(e), exc_info=True)
            return Response({
                'status': 'error',
                'message': 'Failed to get task list. Please try again.'
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
                    'message': 'Missing required parameters'
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
            
            # 获取任务
            try:
                task = Task.objects.get(code=task_code, is_active=True)
            except Task.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': 'Task not found'
                }, status=404)
            
            # 检查是否已完成（对于不可重复任务）
            if not task.is_repeatable:
                completed = TaskHistory.objects.filter(
                    device_id=device_id,
                    task=task
                ).exists()
                if completed:
                    return Response({
                        'status': 'error',
                        'message': f'Task {task.name} has already been completed'
                    }, status=400)
            
            # 检查每日完成次数
            today = timezone.now().date()
            today_count = TaskHistory.objects.filter(
                device_id=device_id,
                task=task,
                completed_at__date=today
            ).count()
            
            if today_count >= task.daily_limit:
                return Response({
                    'status': 'error',
                    'message': 'Daily limit reached. Please try again tomorrow.'
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
                'message': f'Task completed! You earned {task.points} points',
                'data': {
                    'points_awarded': task.points
                }
            })
            
        except Exception as e:
            logger.error(f"Task completion failed: {str(e)}")
            return Response({
                'status': 'error',
                'message': 'Task completion failed. Please try again later.'
            }, status=500)

    # 分享任务相关方法
    @action(detail=False, methods=['POST'])
    def verify_share(self, request):
        """验证分享任务"""
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

    # 推荐系统相关方法
    @action(detail=False, methods=['GET'], url_name='get-link')
    def get_link(self, request):
        """获取推荐链接"""
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': 'Device ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 获取或创建推荐链接
            referral_link = ReferralLink.get_or_create_link(device_id)
            
            return Response({
                'status': 'success',
                'data': {
                    'code': referral_link.code,
                    'link': referral_link.get_full_link(),
                    'created_at': referral_link.created_at
                }
            })
        except Exception as e:
            logger.error(f"获取推荐链接失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': f'获取推荐链接失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['GET'])
    def track_click(self, request):
        """跟踪推荐链接点击"""
        code = request.query_params.get('code')
        
        if not code:
            return Response(
                {'status': 'error', 'message': 'Referral code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 查找推荐链接
            referral_link = get_object_or_404(ReferralLink, code=code, is_active=True)
            
            # 增加点击次数
            referral_link.increment_clicks()
            
            return Response({
                'status': 'success',
                'message': '点击已记录'
            })
        except Exception as e:
            logger.error(f"记录点击失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': f'记录点击失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['POST'])
    def record_web_download(self, request):
        """记录网页下载并奖励积分"""
        try:
            referrer_code = request.data.get('referrer_code')
            device_id = request.data.get('device_id')
            
            if not all([referrer_code, device_id]):
                return Response({
                    'status': 'error',
                    'message': 'Device ID is required'
                }, status=400)
            
            # 查找推荐链接
            referral_link = ReferralLink.objects.get(code=referrer_code, is_active=True)
            
            # 防止自己推荐自己
            if referral_link.device_id == device_id:
                return Response({
                    'status': 'error',
                    'message': 'Cannot refer yourself'
                }, status=400)
            
            # 获取或创建推荐关系
            relationship, created = ReferralRelationship.objects.get_or_create(
                referrer_device_id=referral_link.device_id,
                referred_device_id=device_id,
                defaults={'download_completed': True}
            )
            
            # 如果未发放过下载奖励
            if not relationship.download_points_awarded:
                # 获取邀请下载任务配置
                task_config = settings.TASK_REWARDS.get('INVITE_DOWNLOAD')
                if not task_config:
                    raise ValueError('Invite download task configuration not found')
                
                # 查找或创建邀请下载任务
                invite_task, _ = Task.objects.get_or_create(
                    code='INVITE_DOWNLOAD',
                    defaults={
                        'name': task_config['name'],
                        'task_type': 'INVITE_DOWNLOAD',
                        'description': task_config['description'],
                        'points': task_config['points'],
                        'is_repeatable': task_config['is_repeatable'],
                        'stages_config': task_config.get('stages', [])
                    }
                )
                
                # 获取当前邀请总数
                current_invites = ReferralRelationship.objects.filter(
                    referrer_device_id=referral_link.device_id,
                    download_completed=True
                ).count()
                
                # 获取阶段奖励
                stage_reward = invite_task.get_stage_reward(current_invites)
                points_to_award = stage_reward['points'] if stage_reward else task_config['regular_points']
                reward_description = stage_reward['description'] if stage_reward else '邀请好友下载奖励'
                
                # 创建任务记录
                TaskHistory.objects.create(
                    device_id=referral_link.device_id,
                    task=invite_task,
                    status='COMPLETED',
                    completed_at=timezone.now(),
                    points_awarded=True,
                    extra_data={
                        'referred_device_id': device_id,
                        'referral_code': referrer_code,
                        'current_invites': current_invites,
                        'is_stage_reward': bool(stage_reward)
                    }
                )
                
                # 获取推荐人的积分账户并添加积分
                user_points = UserPoints.get_or_create_user_points(referral_link.device_id)
                user_points.add_points(
                    points=points_to_award,
                    action_type='INVITE_DOWNLOAD',
                    description=reward_description,
                    related_device_id=device_id
                )
                
                # 标记已发放奖励
                relationship.download_points_awarded = True
                relationship.save()
                
                return Response({
                    'status': 'success',
                    'message': 'Download recorded and points awarded',
                    'data': {
                        'points_awarded': points_to_award,
                        'current_invites': current_invites,
                        'is_stage_reward': bool(stage_reward)
                    }
                })
            else:
                return Response({
                    'status': 'success',
                    'message': 'Download recorded, points already awarded previously'
                })
        except Exception as e:
            logger.error(f"记录下载失败: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)

    @action(detail=False, methods=['POST'])
    def record_wallet_creation(self, request):
        """记录钱包创建并奖励积分"""
        device_id = request.data.get('device_id')
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': 'Device ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 获取或创建用户积分记录
            user_points = UserPoints.get_or_create_user_points(device_id)
            
            # 检查是否已创建过钱包
            if user_points.wallet_created:
                return Response({
                    'status': 'error',
                    'message': 'Wallet already created'
                }, status=400)
            
            # 获取创建钱包任务配置
            task_config = settings.TASK_REWARDS.get('CREATE_WALLET')
            if not task_config:
                raise ValueError('Create wallet task configuration not found')
            
            # 查找或创建创建钱包任务
            create_wallet_task, _ = Task.objects.get_or_create(
                code='CREATE_WALLET',
                defaults={
                    'name': task_config['name'],
                    'task_type': 'CREATE_WALLET',
                    'description': task_config['description'],
                    'points': task_config['points'],
                    'is_repeatable': False
                }
            )
            
            # 创建任务记录
            TaskHistory.objects.create(
                device_id=device_id,
                task=create_wallet_task,
                status='COMPLETED',
                completed_at=timezone.now(),
                points_awarded=True
            )
            
            # 添加积分
            user_points.add_points(
                points=task_config['points'],
                action_type='CREATE_WALLET',
                description='创建钱包奖励'
            )
            
            # 标记已创建钱包
            user_points.wallet_created = True
            user_points.save()
            
            return Response({
                'status': 'success',
                'message': 'Wallet creation recorded and points awarded',
                'data': {
                    'points_awarded': task_config['points']
                }
            })
            
        except Exception as e:
            logger.error(f"记录钱包创建失败: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)

    # 积分相关方法
    @action(detail=False, methods=['GET'])
    def get_points(self, request):
        """获取用户积分"""
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': 'Device ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 获取或创建用户积分记录
            user_points = UserPoints.get_or_create_user_points(device_id)
            serializer = UserPointsSerializer(user_points)
            
            return Response({
                'status': 'success',
                'data': serializer.data
            })
        except Exception as e:
            logger.error(f"获取用户积分失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': f'获取用户积分失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['GET'])
    def get_points_history(self, request):
        """获取积分历史"""
        try:
            device_id = request.query_params.get('device_id')
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 10))
            
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': 'Device ID is required'
                }, status=400)
            
            histories = PointsHistory.objects.filter(
                device_id=device_id
            ).order_by('-created_at')
            
            # 分页
            paginator = Paginator(histories, page_size)
            current_page = paginator.page(page)
            
            data = []
            for history in current_page:
                data.append({
                    'points': history.points,
                    'action_type': history.action_type,
                    'description': history.description,
                    'created_at': history.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })
            
            return Response({
                'status': 'success',
                'data': {
                    'items': data,
                    'total': paginator.count,
                    'pages': paginator.num_pages,
                    'current_page': page
                }
            })
            
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)

    # 推荐记录相关方法
    @action(detail=False, methods=['GET'])
    def get_referrals(self, request):
        """获取推荐记录"""
        device_id = request.query_params.get('device_id')
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': 'Device ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 获取推荐记录
            referrals = ReferralRelationship.objects.filter(
                referrer_device_id=device_id
            ).order_by('-created_at')
            
            # 简单分页
            start = (page - 1) * page_size
            end = start + page_size
            paginated_referrals = referrals[start:end]
            
            # 准备数据
            results = []
            for referral in paginated_referrals:
                results.append({
                    'referred_device_id': referral.referred_device_id,
                    'download_completed': referral.download_completed,
                    'wallet_created': referral.wallet_created,
                    'download_points_awarded': referral.download_points_awarded,
                    'wallet_points_awarded': referral.wallet_points_awarded,
                    'created_at': referral.created_at
                })
            
            return Response({
                'status': 'success',
                'data': {
                    'total': referrals.count(),
                    'page': page,
                    'page_size': page_size,
                    'results': results
                }
            })
        except Exception as e:
            logger.error(f"获取推荐记录失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': f'获取推荐记录失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['GET'])
    def get_stats(self, request):
        """获取推荐统计数据"""
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': 'Device ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 获取统计数据
            stats = self.get_referral_stats(device_id)
            
            return Response({
                'status': 'success',
                'data': stats
            })
        except Exception as e:
            logger.error(f"获取推荐统计失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': f'获取推荐统计失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['POST'])
    def record_visit(self, request):
        """记录网站访问"""
        try:
            referrer_code = request.data.get('referrer_code')
            device_id = request.data.get('device_id')
            
            if not all([referrer_code, device_id]):
                return Response({
                    'status': 'error',
                    'message': 'Device ID is required'
                }, status=400)
            
            # 查找推荐链接
            referral_link = get_object_or_404(ReferralLink, code=referrer_code, is_active=True)
            
            # 增加点击次数
            referral_link.increment_clicks()
            
            return Response({
                'status': 'success',
                'message': '访问已记录'
            })
            
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)

    def list(self, request):
        """测试路由是否正确注册"""
        return Response({
            'status': 'success',
            'message': 'API is working'
        }) 