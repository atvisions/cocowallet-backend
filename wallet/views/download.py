from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.views.decorators.http import require_GET
from ..models import ReferralLink

@require_GET
def download_app(request):
    """处理下载链接，记录推荐关系"""
    ref_code = request.GET.get('ref')
    
    # 如果有推荐码，尝试查找对应的推荐链接
    if ref_code:
        try:
            referral_link = ReferralLink.objects.get(code=ref_code, is_active=True)
            referral_link.increment_clicks()
            
            # 将推荐码存储在会话中，以便在用户下载应用后使用
            request.session['referrer_code'] = ref_code
        except ReferralLink.DoesNotExist:
            # 推荐码无效，忽略
            pass
    
    # 检查是否是 iframe 内的请求
    is_iframe = request.GET.get('iframe', 'false') == 'true'
    
    # 如果是 iframe 内的请求，总是返回 HTML 页面
    if is_iframe:
        context = {
            'referrer_code': ref_code,
            'is_iframe': True
        }
        return render(request, 'wallet/download.html', context)
    
    # 否则，根据用户设备类型重定向到相应的应用商店
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    
    if 'iphone' in user_agent or 'ipad' in user_agent or 'ipod' in user_agent:
        # iOS 设备
        return redirect('https://apps.apple.com/app/coco-wallet/id123456789')
    elif 'android' in user_agent:
        # Android 设备
        return redirect('https://play.google.com/store/apps/details?id=io.cocowallet.app')
    else:
        # 其他设备，显示下载页面
        context = {
            'referrer_code': ref_code,
            'is_iframe': False
        }
        return render(request, 'wallet/download.html', context) 