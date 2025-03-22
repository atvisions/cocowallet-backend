from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Wallet
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
        except Exception as e:
            logger.error(f"Failed to record wallet creation: {str(e)}", exc_info=True) 