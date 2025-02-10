from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from datetime import datetime

class BaseHistoryService(ABC):
    """交易历史服务的基础接口类"""
    
    @abstractmethod
    async def get_native_transactions(
        self,
        address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """获取原生代币交易历史"""
        pass
    
    @abstractmethod
    async def get_token_transactions(
        self,
        address: str,
        token_address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """获取代币交易历史"""
        pass
    
    @abstractmethod
    async def get_transaction_details(self, tx_hash: str) -> Dict:
        """获取交易详情"""
        pass 