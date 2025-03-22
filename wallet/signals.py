from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Wallet
from .views.referral import ReferralViewSet
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Wallet)
def wallet_created(sender, instance, created, **kwargs):
    """当钱包被创建时触发"""
    logger.info(f"钱包保存事件触发: 实例={instance.id}, 创建={created}, 设备ID={instance.device_id}")
    
    if created:  # 只在新创建钱包时触发
        try:
            device_id = instance.device_id
            if device_id:
                logger.info(f"尝试为设备 {device_id} 记录钱包创建")
                # 直接调用 record_wallet_creation_internal 方法
                from .views.referral import record_wallet_creation_internal
                result = record_wallet_creation_internal(device_id)
                logger.info(f"记录钱包创建结果: {result}")
            else:
                logger.warning("钱包创建事件没有设备ID")
        except Exception as e:
            logger.error(f"记录钱包创建失败: {str(e)}", exc_info=True) 