from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List

class BaseBalanceService(ABC):
    """余额查询基础服务类"""

    @abstractmethod
    def get_health_check_url(self) -> str:
        """获取健康检查URL"""
        pass

    @abstractmethod
    async def get_native_balance(self, address: str) -> Decimal:
        """获取原生代币余额"""
        pass

    @abstractmethod
    async def get_token_balance(self, address: str, token_address: str) -> Decimal:
        """获取指定代币余额"""
        pass

    @abstractmethod
    async def get_all_token_balances(self, address: str) -> List[Dict]:
        """获取所有代币余额"""
        pass 