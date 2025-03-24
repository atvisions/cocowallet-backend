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
from django.views.decorators.csrf import csrf_exempt
import logging

logger = logging.getLogger(__name__)

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

@csrf_exempt
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

@csrf_exempt
@require_GET
def download_app(request):
    """处理应用下载请求 - 简化版，直接提供APK下载"""
    ref_code = request.GET.get('ref')
    temp_id = request.GET.get('temp_id')
    
    # 记录下载请求
    logger.info(f"收到下载请求: ref={ref_code}, temp_id={temp_id}")
    
    # 如果有推荐码，尝试记录点击
    if ref_code:
        try:
            referral_link = ReferralLink.objects.get(code=ref_code, is_active=True)
            referral_link.increment_clicks()
            
            # 将推荐码存储在会话中，以便在用户下载应用后使用
            request.session['referrer_code'] = ref_code
            logger.info(f"记录推荐点击: ref={ref_code}, 累计点击={referral_link.clicks}")
        except ReferralLink.DoesNotExist:
            # 推荐码无效，忽略
            logger.warning(f"无效的推荐码: {ref_code}")
            pass
    
    # 构建下载参数
    download_params = {
        'referrer': ref_code or '',
        'temp_device_id': temp_id or '',
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
        logger.error(f"APK文件未找到: {apk_path}")
        return HttpResponse('抱歉，APK文件未找到。请联系客服。', status=404)
    
    # 返回文件响应
    try:
        response = FileResponse(
            open(apk_path, 'rb'),
            content_type='application/vnd.android.package-archive'
        )
        response['Content-Disposition'] = 'attachment; filename="cocowallet-1.0.0.apk"'
        
        # 添加安装参数
        response['X-Install-Params'] = encoded_params
        
        # 记录成功的下载响应
        file_size = os.path.getsize(apk_path)
        logger.info(f"成功提供APK下载: size={file_size} bytes")
        
        return response
    except Exception as e:
        logger.error(f"提供APK下载时出错: {str(e)}")
        return HttpResponse('下载过程中出现错误，请稍后重试。', status=500) 