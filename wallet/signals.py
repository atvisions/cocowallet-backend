from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Wallet, ReferralLink, ReferralRelationship, UserPoints
from .views.referral import ReferralViewSet
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Wallet)
def wallet_created(sender, instance, created, **kwargs):
    """Triggered when wallet is created"""
    logger.info(f"Wallet save event triggered: instance={instance.id}, created={created}, device_id={instance.device_id}")
    
    if created:  # Only trigger on new wallet creation
        try:
            device_id = instance.device_id
            if device_id:
                logger.info(f"Attempting to record wallet creation for device {device_id}")
                # Directly call record_wallet_creation_internal method
                from .views.referral import record_wallet_creation_internal
                result = record_wallet_creation_internal(device_id)
                logger.info(f"Wallet creation record result: {result}")
            else:
                logger.warning("Wallet creation event has no device ID")

            if created and instance.referral_info:
                try:
                    ref_code = instance.referral_info.get('ref_code')
                    temp_id = instance.referral_info.get('temp_id')
                    
                    # 查找推荐关系
                    referral_link = ReferralLink.objects.get(code=ref_code)
                    
                    # 创建或更新推荐关系
                    relationship, _ = ReferralRelationship.objects.get_or_create(
                        referrer_device_id=referral_link.device_id,
                        referred_device_id=instance.device_id,
                        defaults={
                            'download_completed': True,
                            'wallet_created': True
                        }
                    )
                    
                    # 如果未发放过钱包创建奖励
                    if not relationship.wallet_points_awarded:
                        # 获取推荐人积分账户
                        user_points = UserPoints.get_or_create_user_points(
                            referral_link.device_id
                        )
                        
                        # 添加积分奖励
                        user_points.add_points(
                            points=10,  # 钱包创建奖励10积分
                            action_type='WALLET_REFERRAL',
                            description=f'User {instance.device_id} created wallet',
                            related_device_id=instance.device_id
                        )
                        
                        # 标记已发放奖励
                        relationship.wallet_points_awarded = True
                        relationship.save()
                        
                except Exception as e:
                    logger.error(f"Failed to process referral reward: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to record wallet creation: {str(e)}", exc_info=True) 