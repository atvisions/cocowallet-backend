from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action

from ..models import MnemonicBackup, PaymentPassword
from ..serializers import MnemonicBackupSerializer

class MnemonicBackupViewSet(viewsets.ModelViewSet):
    """助记词备份视图集"""
    serializer_class = MnemonicBackupSerializer
    
    def get_queryset(self):
        """获取助记词备份列表"""
        device_id = self.request.query_params.get('device_id')
        if not device_id:
            return MnemonicBackup.objects.none()
        return MnemonicBackup.objects.filter(device_id=device_id)
    
    def create(self, request, *args, **kwargs):
        """创建助记词备份"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # 验证支付密码
        device_id = serializer.validated_data['device_id']
        payment_password = request.data.get('payment_password')
        if not payment_password:
            return Response({
                'status': 'error',
                'message': '请提供支付密码'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        payment_pwd = PaymentPassword.objects.filter(device_id=device_id).first()
        if not payment_pwd or not payment_pwd.verify_password(payment_password):
            return Response({
                'status': 'error',
                'message': '支付密码错误'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 创建备份
        backup = serializer.save()
        
        return Response({
            'status': 'success',
            'message': '助记词备份创建成功',
            'data': MnemonicBackupSerializer(backup).data
        })
    
    def retrieve(self, request, *args, **kwargs):
        """获取助记词备份"""
        instance = self.get_object()
        
        # 验证支付密码
        payment_password = request.query_params.get('payment_password')
        if not payment_password:
            return Response({
                'status': 'error',
                'message': '请提供支付密码'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        payment_pwd = PaymentPassword.objects.filter(device_id=instance.device_id).first()
        if not payment_pwd or not payment_pwd.verify_password(payment_password):
            return Response({
                'status': 'error',
                'message': '支付密码错误'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = self.get_serializer(instance)
        return Response({
            'status': 'success',
            'data': serializer.data
        }) 