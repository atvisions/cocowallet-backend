from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class BaseSwapService(ABC):
    """代币兑换服务基类"""

    @abstractmethod
    def get_quote(self, wallet_id: str, device_id: str, from_token: str, to_token: str, amount: str, slippage: Optional[str] = None) -> Dict[str, Any]:
        """获取兑换报价

        Args:
            wallet_id: 钱包ID
            device_id: 设备ID
            from_token: 源代币地址
            to_token: 目标代币地址
            amount: 兑换数量
            slippage: 滑点容忍度（可选）

        Returns:
            Dict[str, Any]: 报价信息
        """
        pass

    @abstractmethod
    def execute_swap(self, wallet_id: str, device_id: str, quote_id: str, from_token: str, to_token: str, amount: str, slippage: Optional[str] = None) -> Dict[str, Any]:
        """执行代币兑换

        Args:
            wallet_id: 钱包ID
            device_id: 设备ID
            quote_id: 报价ID
            from_token: 源代币地址
            to_token: 目标代币地址
            amount: 兑换数量
            slippage: 滑点容忍度（可选）

        Returns:
            Dict[str, Any]: 兑换结果
        """
        pass