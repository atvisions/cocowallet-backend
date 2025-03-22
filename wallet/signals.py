from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Wallet
from .views.referral import ReferralViewSet
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Wallet)
def wallet_created(sender, instance, created, **kwargs):
    """当钱包被创建时触发"""
    if created:  # 只在新创建钱包时触发
        try:
            device_id = instance.device_id
            if device_id:
                # 创建一个模拟请求对象
                class MockRequest:
                    def __init__(self, data):
                        self.data = data
                
                # 创建推荐视图集实例
                referral_viewset = ReferralViewSet()
                # 调用记录钱包创建的方法
                response = referral_viewset.record_wallet_creation(
                    request=MockRequest(data={'device_id': device_id})
                )
                logger.info(f"记录钱包创建结果: {response.data}")
        except Exception as e:
            logger.error(f"记录钱包创建失败: {str(e)}") 