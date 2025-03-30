from django.shortcuts import render
from django.views.decorators.http import require_GET
from ..models import ReferralLink, ReferralRelationship, UserPoints
import os
from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)

@csrf_exempt
@require_GET
def home(request):
    """网站主页"""
    ref_code = request.GET.get('ref')
    
    # 如果有推荐码，尝试查找对应的推荐链接
    if ref_code:
        try:
            ReferralLink.objects.get(code=ref_code, is_active=True)
        except ReferralLink.DoesNotExist:
            ref_code = None
    
    context = {
        'referrer_code': ref_code
    }
    return render(request, 'wallet/home.html', context)

@csrf_exempt
@require_GET
def download_app(request):
    """处理应用下载请求"""
    ref_code = request.GET.get('ref')
    client_ip = request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR')
    
    logger.info(f"收到下载请求: ref={ref_code}, ip={client_ip}")
    
    # 直接重定向到静态文件URL
    static_apk_url = f"{settings.API_DOMAIN}/static/website/apk/cocowallet-1.0.0.apk"
    
    # 如果有推荐码，先处理推荐逻辑
    if ref_code:
        try:
            referral_link = ReferralLink.objects.get(code=ref_code, is_active=True)
            
            # 检查是否是自己推荐自己（IP检查）
            referrer_downloads = cache.get(f"referrer_ip_{client_ip}_{ref_code}") or []
            if client_ip in referrer_downloads:
                logger.warning(f"检测到重复下载: ip={client_ip}, ref={ref_code}")
                return HttpResponse('Please do not download repeatedly', status=400)
            
            # 检查24小时内该IP的下载次数
            ip_download_count = cache.get(f"ip_downloads_{client_ip}") or 0
            if ip_download_count >= 3:  # 每个IP 24小时内最多3次下载
                logger.warning(f"IP下载次数超限: ip={client_ip}, count={ip_download_count}")
                return HttpResponse('Download limit exceeded, please try again in 24 hours', status=400)
            
            # 增加点击次数
            referral_link.increment_clicks()
            
            # 获取或创建推荐关系
            relationship, created = ReferralRelationship.objects.get_or_create(
                referrer_device_id=referral_link.device_id,
                defaults={'download_completed': True}
            )
            
            # 如果未发放过下载奖励
            if not relationship.download_points_awarded:
                # 检查推荐人24小时内获得的积分
                referrer_points = cache.get(f"referrer_points_{referral_link.device_id}") or 0
                if referrer_points >= 500:  # 改为500积分（100次推荐）
                    logger.warning(f"推荐人积分超限: device_id={referral_link.device_id}, points={referrer_points}")
                    return HttpResponse('推荐人今日积分已达上限', status=400)
                
                # 获取推荐人的积分账户
                user_points = UserPoints.get_or_create_user_points(
                    referral_link.device_id
                )
                
                # 添加积分奖励
                user_points.add_points(
                    points=5,
                    action_type='DOWNLOAD_REFERRAL',
                    description=f'New user downloaded the app through referral code {ref_code}',
                    related_device_id=referral_link.device_id
                )
                
                # 更新缓存
                cache.set(f"referrer_points_{referral_link.device_id}", referrer_points + 5, 86400)  # 24小时
                cache.set(f"ip_downloads_{client_ip}", ip_download_count + 1, 86400)  # 24小时
                referrer_downloads.append(client_ip)
                cache.set(f"referrer_ip_{client_ip}_{ref_code}", referrer_downloads, 86400)  # 24小时
                
                # 标记已发放奖励
                relationship.download_points_awarded = True
                relationship.save()
                
                logger.info(f"已发放下载奖励: 推荐人={referral_link.device_id}, 积分=5")
            
        except ReferralLink.DoesNotExist:
            logger.error(f"无效的推荐码: {ref_code}")
        except Exception as e:
            logger.error(f"处理推荐下载失败: {str(e)}")
    
    # 最后重定向到APK文件
    return HttpResponseRedirect(static_apk_url)