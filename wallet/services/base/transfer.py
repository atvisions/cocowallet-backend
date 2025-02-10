from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
from decimal import Decimal

from .base_service import BaseService

class BaseTransferService(BaseService):
    """转账服务的基础接口类"""
    
    def get_health_check_url(self) -> str:
        """获取健康检查URL"""
        return ""  # 基类返回空字符串，子类需要重写此方法
    
    @abstractmethod
    async def transfer_native(
        self,
        from_address: str,
        to_address: str,
        amount: Decimal,
        private_key: str,
        **kwargs
    ) -> Dict[str, Any]:
        """转账原生代币"""
        pass
    
    @abstractmethod
    async def transfer_token(
        self,
        from_address: str,
        to_address: str,
        token_address: str,
        amount: Decimal,
        private_key: str,
        **kwargs
    ) -> Dict[str, Any]:
        """转账代币"""
        pass
    
    @abstractmethod
    async def estimate_native_transfer_fee(
        self,
        from_address: str,
        to_address: str,
        amount: Decimal,
        **kwargs
    ) -> Dict:
        """估算原生代币转账费用"""
        pass
    
    @abstractmethod
    async def estimate_token_transfer_fee(
        self,
        from_address: str,
        to_address: str,
        token_address: str,
        amount: Decimal,
        **kwargs
    ) -> Dict:
        """估算代币转账费用"""
        pass 