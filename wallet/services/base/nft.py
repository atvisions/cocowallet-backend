from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseNFTService(ABC):
    """NFT 服务基类"""

    @abstractmethod
    async def transfer_nft(self, from_address: str, to_address: str, nft_address: str, private_key: str) -> Dict[str, Any]:
        """转移 NFT
        
        Args:
            from_address: 发送方地址
            to_address: 接收方地址
            nft_address: NFT 地址
            private_key: 发送方私钥
            
        Returns:
            Dict[str, Any]: 转账结果
        """
        pass 