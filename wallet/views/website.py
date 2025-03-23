from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET
from ..models import ReferralLink
import time
import json
import base64
from django.templatetags.static import static
import uuid
import hmac
import hashlib
from django.conf import settings
from django.http import FileResponse, HttpResponse
import os

def generate_signature(params):
    """
    生成签名
    params: 需要签名的参数字典
    """
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

@require_GET
def home(request):
    """网站主页"""
    ref_code = request.GET.get('ref')
    temp_device_id = f'web_{uuid.uuid4().hex}'  # 生成临时设备ID
    
    # 如果有推荐码，尝试查找对应的推荐链接
    if ref_code:
        try:
            referral_link = ReferralLink.objects.get(code=ref_code, is_active=True)
            
            # 将推荐码存储在会话中，以便在用户下载应用后使用
            request.session['referrer_code'] = ref_code
        except ReferralLink.DoesNotExist:
            # 推荐码无效，忽略
            pass
    
    context = {
        'referrer_code': ref_code,
        'temp_device_id': temp_device_id
    }
    return render(request, 'wallet/home.html', context)

@require_GET
def download_app(request):
    ref_code = request.GET.get('ref')
    temp_id = request.GET.get('temp_id')
    
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
    
    # APK文件路径
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