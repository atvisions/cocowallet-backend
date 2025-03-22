from django.shortcuts import render
from django.views.decorators.http import require_GET
from ..models import ReferralLink

@require_GET
def home(request):
    """网站主页"""
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
    
    context = {
        'referrer_code': ref_code
    }
    return render(request, 'wallet/home.html', context) 