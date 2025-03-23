from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from django.shortcuts import get_object_or_404
import logging
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny

from ..models import ReferralLink, ReferralRelationship, UserPoints, PointsHistory
from ..serializers import (
    ReferralLinkSerializer, ReferralRelationshipSerializer,
    UserPointsSerializer, PointsHistorySerializer, ReferralStatsSerializer
)

logger = logging.getLogger(__name__)

@method_decorator(csrf_exempt, name='dispatch')
class ReferralViewSet(viewsets.ViewSet):
    """推荐系统视图集"""
    
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def get_referral_stats(self, device_id):
        """获取推荐统计数据"""
        # 获取推荐关系统计
        total_referrals = ReferralRelationship.objects.filter(
            referrer_device_id=device_id
        ).count()
        
        completed_referrals = ReferralRelationship.objects.filter(
            referrer_device_id=device_id,
            wallet_created=True
        ).count()
        
        pending_referrals = total_referrals - completed_referrals
        
        # 获取积分统计
        user_points = UserPoints.get_or_create_user_points(device_id)
        total_points = user_points.total_points
        
        # 获取不同类型的积分
        download_points = PointsHistory.objects.filter(
            device_id=device_id,
            action_type='DOWNLOAD_REFERRAL'
        ).aggregate(total=Sum('points'))['total'] or 0
        
        wallet_points = PointsHistory.objects.filter(
            device_id=device_id,
            action_type='WALLET_REFERRAL'
        ).aggregate(total=Sum('points'))['total'] or 0
        
        return {
            'total_referrals': total_referrals,
            'completed_referrals': completed_referrals,
            'pending_referrals': pending_referrals,
            'total_points': total_points,
            'download_points': download_points,
            'wallet_points': wallet_points
        }
    
    @action(detail=False, methods=['get'])
    def get_link(self, request):
        """获取或创建推荐链接"""
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': '缺少设备ID参数'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 获取或创建推荐链接
            referral_link = ReferralLink.get_or_create_link(device_id)
            serializer = ReferralLinkSerializer(referral_link)
            
            return Response({
                'status': 'success',
                'data': serializer.data
            })
        except Exception as e:
            logger.error(f"获取推荐链接失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': f'获取推荐链接失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def track_click(self, request):
        """跟踪推荐链接点击"""
        code = request.query_params.get('code')
        
        if not code:
            return Response(
                {'status': 'error', 'message': '缺少推荐码参数'},
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
    
    @action(detail=False, methods=['post'])
    def record_web_download(self, request):
        """记录网页下载并奖励积分"""
        try:
            referrer_code = request.data.get('referrer_code')
            device_id = request.data.get('device_id')
            
            if not all([referrer_code, device_id]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=400)
            
            # 查找推荐链接
            referral_link = get_object_or_404(ReferralLink, code=referrer_code, is_active=True)
            
            # 记录下载
            success = referral_link.record_download(device_id)
            
            if success:
                # 获取或创建用户积分
                user_points = UserPoints.get_or_create_user_points(referral_link.device_id)
                
                # 添加下载积分
                points_awarded = user_points.add_points(
                    points=5,  # 下载奖励5分
                    action_type='DOWNLOAD_REFERRAL',
                    description=f'User {device_id} downloaded app',
                    related_device_id=device_id
                )
                
                return Response({
                    'status': 'success',
                    'message': '下载记录已保存，积分已奖励',
                    'points_awarded': points_awarded
                })
            else:
                return Response({
                    'status': 'error',
                    'message': '不能推荐自己'
                }, status=400)
            
        except ReferralLink.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '无效的推荐码'
            }, status=404)
        except Exception as e:
            logger.error(f"记录下载失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=500)
    
    @action(detail=False, methods=['post'])
    def record_wallet_creation(self, request):
        """记录钱包创建并奖励积分"""
        device_id = request.data.get('device_id')
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': '缺少设备ID参数'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        result = self.record_wallet_creation_internal(device_id)
        
        if result['status'] == 'success':
            return Response({
                'status': 'success',
                'message': result['message']
            })
        else:
            return Response(
                {'status': 'error', 'message': result['message']},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def record_wallet_creation_internal(self, device_id):
        """内部函数：记录钱包创建并奖励积分"""
        try:
            # 查找推荐关系，不考虑 wallet_created 状态
            relationship = ReferralRelationship.objects.filter(
                referred_device_id=device_id,
                download_completed=True
            ).first()
            
            if not relationship:
                # 没有找到符合条件的推荐关系，可能不是通过推荐下载的
                logger.info(f"设备 {device_id} 没有找到推荐关系")
                return {
                    'status': 'success',
                    'message': '没有找到推荐关系，不奖励积分'
                }
            
            logger.info(f"找到推荐关系: 推荐人={relationship.referrer_device_id}, 被推荐人={relationship.referred_device_id}")
            
            # 更新推荐关系
            relationship.wallet_created = True
            relationship.save()
            
            # 如果还没有奖励钱包创建积分
            if not relationship.wallet_points_awarded:
                logger.info(f"为推荐人 {relationship.referrer_device_id} 奖励积分")
                
                # 获取或创建推荐人积分记录
                user_points = UserPoints.get_or_create_user_points(relationship.referrer_device_id)
                
                # 添加积分 (5分)
                user_points.add_points(
                    points=5,
                    action_type='WALLET_REFERRAL',
                    description=f'用户 {device_id} 通过您的推荐创建了钱包',
                    related_device_id=device_id
                )
                
                # 标记已奖励钱包创建积分
                relationship.wallet_points_awarded = True
                relationship.save()
                
                logger.info(f"积分奖励成功，当前积分: {user_points.total_points}")
            else:
                logger.info(f"已经奖励过积分，不重复奖励")
            
            return {
                'status': 'success',
                'message': '钱包创建已记录，积分已奖励'
            }
        except Exception as e:
            logger.error(f"记录钱包创建失败: {str(e)}", exc_info=True)
            return {
                'status': 'error',
                'message': f'记录钱包创建失败: {str(e)}'
            }
    
    @action(detail=False, methods=['get'])
    def get_points(self, request):
        """获取用户积分"""
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': '缺少设备ID参数'},
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
    
    @action(detail=False, methods=['get'])
    def get_points_history(self, request):
        """获取积分历史"""
        device_id = request.query_params.get('device_id')
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': '缺少设备ID参数'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 获取积分历史记录
            history = PointsHistory.objects.filter(device_id=device_id)
            
            # 简单分页
            start = (page - 1) * page_size
            end = start + page_size
            paginated_history = history[start:end]
            
            serializer = PointsHistorySerializer(paginated_history, many=True)
            
            return Response({
                'status': 'success',
                'data': {
                    'total': history.count(),
                    'page': page,
                    'page_size': page_size,
                    'results': serializer.data
                }
            })
        except Exception as e:
            logger.error(f"获取积分历史失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': f'获取积分历史失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def get_referrals(self, request):
        """获取推荐记录"""
        device_id = request.query_params.get('device_id')
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': '缺少设备ID参数'},
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
            
            serializer = ReferralRelationshipSerializer(paginated_referrals, many=True)
            
            return Response({
                'status': 'success',
                'data': {
                    'total': referrals.count(),
                    'page': page,
                    'page_size': page_size,
                    'results': serializer.data
                }
            })
        except Exception as e:
            logger.error(f"获取推荐记录失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': f'获取推荐记录失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def get_stats(self, request):
        """获取推荐统计数据"""
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response(
                {'status': 'error', 'message': '缺少设备ID参数'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 获取统计数据
            stats = self.get_referral_stats(device_id)
            serializer = ReferralStatsSerializer(stats)
            
            return Response({
                'status': 'success',
                'data': serializer.data
            })
        except Exception as e:
            logger.error(f"获取推荐统计失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': f'获取推荐统计失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def update_device_id(self, request):
        """更新设备ID"""
        old_device_id = request.data.get('old_device_id')
        new_device_id = request.data.get('new_device_id')
        
        if not all([old_device_id, new_device_id]):
            return Response(
                {'status': 'error', 'message': '缺少必要参数'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 查找指定的临时设备ID
            relationships = ReferralRelationship.objects.filter(
                referred_device_id=old_device_id
            )
            
            updated_count = 0
            for relationship in relationships:
                # 更新设备ID
                relationship.referred_device_id = new_device_id
                relationship.save()
                updated_count += 1
                logger.info(f"更新设备 ID: {old_device_id} -> {new_device_id}")
            
            return Response({
                'status': 'success',
                'message': f'成功更新 {updated_count} 条推荐关系',
                'data': {'updated_count': updated_count}
            })
        except Exception as e:
            logger.error(f"更新设备ID失败: {str(e)}", exc_info=True)
            return Response(
                {'status': 'error', 'message': f'更新设备ID失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def record_visit(self, request):
        """记录网站访问"""
        try:
            referrer_code = request.data.get('referrer_code')
            device_id = request.data.get('device_id')
            
            if not all([referrer_code, device_id]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
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