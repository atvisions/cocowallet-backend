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
    
    # 添加更详细的日志
    logger.info(f"Wallet data - referral_info: {instance.referral_info}")
    
    if created:  # Only trigger on new wallet creation
        try:
            device_id = instance.device_id
            if device_id:
                logger.info(f"Attempting to record wallet creation for device {device_id}")
                # 调用记录钱包创建函数
                from .views.referral import record_wallet_creation_internal
                result = record_wallet_creation_internal(device_id)
                logger.info(f"Wallet creation record result: {result}")
            
            # 添加条件检查日志
            logger.info(f"Checking referral_info condition: {bool(instance.referral_info)}")
            
            # 处理推荐奖励
            if created and instance.referral_info:
                try:
                    ref_code = instance.referral_info.get('ref_code')
                    temp_id = instance.referral_info.get('temp_id')
                    
                    logger.info(f"Processing referral with code: {ref_code}, temp_id: {temp_id}")
                    
                    # 查找推荐链接
                    try:
                        referral_link = ReferralLink.objects.get(code=ref_code)
                        logger.info(f"Found referral link: {referral_link.id} for device: {referral_link.device_id}")
                    except ReferralLink.DoesNotExist:
                        logger.error(f"Referral link not found for code: {ref_code}")
                        return
                    
                    # 创建或更新推荐关系
                    relationship, created_rel = ReferralRelationship.objects.get_or_create(
                        referrer_device_id=referral_link.device_id,
                        referred_device_id=instance.device_id,
                        defaults={
                            'download_completed': True,
                            'wallet_created': True
                        }
                    )
                    
                    logger.info(f"Relationship: {relationship.id}, new created: {created_rel}")
                    logger.info(f"Current award status: wallet_points_awarded={relationship.wallet_points_awarded}")
                    
                    # 如果未发放过钱包创建奖励
                    if not relationship.wallet_points_awarded:
                        # 获取推荐人积分账户
                        user_points = UserPoints.get_or_create_user_points(
                            referral_link.device_id
                        )
                        
                        logger.info(f"Adding points to user: {referral_link.device_id}, current points: {user_points.total_points}")
                        
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
                        
                        logger.info(f"Points awarded successfully, new total: {user_points.total_points}")
                    else:
                        logger.info("Wallet points already awarded, skipping")
                        
                except Exception as e:
                    logger.error(f"Failed to process referral reward: {str(e)}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to record wallet creation: {str(e)}", exc_info=True) 