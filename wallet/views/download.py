from django.shortcuts import render, redirect
from django.http import HttpResponse, FileResponse
from django.views.decorators.http import require_GET
from ..models import ReferralLink
from django.views.decorators.csrf import csrf_exempt
import os
from django.conf import settings
import time
import json
import base64
import hmac
import hashlib

def generate_signature(params):
    """生成签名"""
    # 按键排序
    sorted_params = dict(sorted(params.items()))
    
    # 构建签名字符串
    sign_str = '&'.join([f"{k}={v}" for k, v in sorted_params.items()])
    
    # 使用 HMAC-SHA256 生成签名
    secret_key = getattr(settings, 'REFERRAL_SECRET_KEY', 'your-secret-key')
    signature = hmac.new(
        secret_key.encode(),
        sign_str.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return signature

@csrf_exempt
@require_GET
def download_app(request):
    """智能下载处理函数"""
    ref_code = request.GET.get('ref')
    temp_id = request.GET.get('temp_id')
    
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
    
    # 如果是 iframe 内的请求，返回 HTML 页面
    if is_iframe:
        context = {
            'referrer_code': ref_code,
            'is_iframe': True
        }
        return render(request, 'wallet/download.html', context)
    
    # 构建下载参数
    download_params = {
        'referrer': ref_code,
        'temp_device_id': temp_id,
        'timestamp': int(time.time())
    }
    
    # 生成签名
    signature = generate_signature(download_params)
    download_params['sign'] = signature
    
    # 编码参数
    encoded_params = base64.urlsafe_b64encode(
        json.dumps(download_params).encode()
    ).decode()
    
    # 根据用户设备类型重定向到相应的应用商店或提供直接下载
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    
    if 'iphone' in user_agent or 'ipad' in user_agent or 'ipod' in user_agent:
        # iOS 设备 - 跳转到 App Store
        # 添加自定义URL scheme参数以便iOS app检测安装来源
        ios_url = f"https://apps.apple.com/app/coco-wallet/id123456789?install_params={encoded_params}"
        return redirect(ios_url)
    elif 'android' in user_agent:
        # Android 设备 - 直接下载APK
        apk_path = os.path.join(settings.STATIC_ROOT if not settings.DEBUG else settings.STATICFILES_DIRS[0], 
                              'website/apk/cocowallet-1.0.0.apk')
        
        # 检查文件是否存在
        if not os.path.exists(apk_path):
            return HttpResponse('APK file not found', status=404)
        
        # 返回文件响应
        response = FileResponse(
            open(apk_path, 'rb'),
            content_type='application/vnd.android.package-archive'
        )
        response['Content-Disposition'] = 'attachment; filename="cocowallet-1.0.0.apk"'
        
        # 添加安装参数
        response['X-Install-Params'] = encoded_params
        
        return response
    else:
        # 其他设备，显示下载页面
        context = {
            'referrer_code': ref_code,
            'temp_id': temp_id,
            'is_iframe': False
        }
        return render(request, 'wallet/download.html', context) 