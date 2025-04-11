from django.core.management.base import BaseCommand
from wallet.models import PaymentPassword, encrypt_string

class Command(BaseCommand):
    help = '重置所有支付密码为默认密码'

    def handle(self, *args, **options):
        # 默认密码
        default_password = '888888'
        
        # 获取所有支付密码记录
        payment_passwords = PaymentPassword.objects.all()
        
        # 重置密码
        for payment_password in payment_passwords:
            payment_password.set_password(default_password)
            self.stdout.write(self.style.SUCCESS(f'重置设备 {payment_password.device_id} 的支付密码成功'))
        
        self.stdout.write(self.style.SUCCESS('所有支付密码已重置为 888888')) 