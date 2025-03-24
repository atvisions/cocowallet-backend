from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from django.shortcuts import get_object_or_404
import logging
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny
from django.http import HttpResponse
from django.core.cache import cache
import time
from datetime import datetime, timedelta

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
    
    # 添加防刷接口的方法
    def rate_limit(self, key, limit=10, period=60):
        """简单的速率限制
        key: 缓存键
        limit: 时间段内允许的最大请求数
        period: 时间段(秒)
        """
        current_time = int(time.time())
        cache_key = f"rate_limit:{key}:{current_time // period}"
        
        # 获取当前计数
        count = cache.get(cache_key, 0)
        
        # 如果超出限制
        if count >= limit:
            return False
        
        # 增加计数
        cache.set(cache_key, count + 1, period)
        return True
    
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
            
            # 速率限制 - 每设备每小时最多5次下载
            if not self.rate_limit(f"download:{device_id}", limit=5, period=3600):
                return Response({
                    'status': 'error',
                    'message': '请求过于频繁，请稍后再试'
                }, status=429)
            
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
            # 1. 更新推荐关系中的被推荐人设备ID
            relationships = ReferralRelationship.objects.filter(
                referred_device_id=old_device_id
            )
            
            updated_rel_count = 0
            for relationship in relationships:
                relationship.referred_device_id = new_device_id
                relationship.save()
                updated_rel_count += 1
                logger.info(f"更新推荐关系中的设备ID: {old_device_id} -> {new_device_id}")
            
            # 2. 更新推荐关系中的推荐人设备ID（如果有）
            referrer_relationships = ReferralRelationship.objects.filter(
                referrer_device_id=old_device_id
            )
            
            updated_referrer_count = 0
            for rel in referrer_relationships:
                rel.referrer_device_id = new_device_id
                rel.save()
                updated_referrer_count += 1
                logger.info(f"更新推荐人设备ID: {old_device_id} -> {new_device_id}")
            
            # 3. 更新用户积分记录
            try:
                user_points = UserPoints.objects.get(device_id=old_device_id)
                user_points.device_id = new_device_id
                user_points.save()
                logger.info(f"更新用户积分设备ID: {old_device_id} -> {new_device_id}")
            except UserPoints.DoesNotExist:
                logger.info(f"未找到设备ID为 {old_device_id} 的用户积分记录")
            
            # 4. 更新积分历史记录
            points_history_count = PointsHistory.objects.filter(
                device_id=old_device_id
            ).update(device_id=new_device_id)
            
            if points_history_count > 0:
                logger.info(f"更新了 {points_history_count} 条积分历史记录的设备ID")
            
            # 5. 更新推荐链接的设备ID（如果有）
            try:
                referral_link = ReferralLink.objects.get(device_id=old_device_id)
                referral_link.device_id = new_device_id
                referral_link.save()
                logger.info(f"更新推荐链接设备ID: {old_device_id} -> {new_device_id}")
            except ReferralLink.DoesNotExist:
                logger.info(f"未找到设备ID为 {old_device_id} 的推荐链接")
            
            # 汇总更新结果
            total_updated = updated_rel_count + updated_referrer_count + points_history_count + (1 if 'user_points' in locals() else 0) + (1 if 'referral_link' in locals() else 0)
            
            return Response({
                'status': 'success',
                'message': f'成功更新 {total_updated} 条记录的设备ID',
                'data': {
                    'referred_relationships': updated_rel_count,
                    'referrer_relationships': updated_referrer_count,
                    'points_histories': points_history_count,
                    'user_points_updated': 'user_points' in locals(),
                    'referral_link_updated': 'referral_link' in locals()
                }
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
            
            # 速率限制 - 每设备每分钟最多3次访问记录
            if not self.rate_limit(f"visit:{device_id}", limit=3, period=60):
                return Response({
                    'status': 'success',  # 返回成功但不实际记录
                    'message': '访问已记录'
                })
            
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