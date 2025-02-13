from typing import Dict, Type, Optional

from .base.balance import BaseBalanceService
from .base.transfer import BaseTransferService
from .base.price import BasePriceService
from .base.history import BaseHistoryService
from .base.token_info import BaseTokenInfoService
from .base.swap import BaseSwapService
from .base.nft import BaseNFTService

from .solana.balance import SolanaBalanceService
from .solana.transfer import SolanaTransferService
from .solana.price import SolanaPriceService
from .solana.history import SolanaHistoryService
from .solana.token_info import SolanaTokenInfoService
from .solana.swap import SolanaSwapService
from .solana.nft import SolanaNFTService

# TODO: 添加 Ethereum 服务实现

class ChainServiceFactory:
    """链服务工厂类"""
    
    _balance_services = {}
    
    _transfer_services: Dict[str, Type[BaseTransferService]] = {
        'SOL': SolanaTransferService,
        # TODO: 添加其他链的转账服务
    }
    
    _price_services: Dict[str, Type[BasePriceService]] = {
        'SOL': SolanaPriceService,
        # TODO: 添加其他链的价格服务
    }
    
    _history_services: Dict[str, Type[BaseHistoryService]] = {
        'SOL': SolanaHistoryService,
        # TODO: 添加其他链的历史记录服务
    }
    
    _token_info_services: Dict[str, Type[BaseTokenInfoService]] = {
        'SOL': SolanaTokenInfoService,
        # TODO: 添加其他链的代币信息服务
    }

    _swap_services: Dict[str, Type[BaseSwapService]] = {
        'SOL': SolanaSwapService,
        # TODO: 添加其他链的兑换服务
    }

    _nft_services: Dict[str, Type[BaseNFTService]] = {
        'SOL': SolanaNFTService,
        # TODO: 添加其他链的 NFT 服务
    }
    
    @classmethod
    def get_balance_service(cls, chain: str) -> Optional[BaseBalanceService]:
        """获取指定链的余额服务实例"""
        if chain not in cls._balance_services:
            if chain == 'SOL':
                cls._balance_services[chain] = SolanaBalanceService()
            # TODO: 添加其他链的服务实例
        
        return cls._balance_services.get(chain)
    
    @classmethod
    def get_transfer_service(cls, chain: str) -> Optional[BaseTransferService]:
        """获取转账服务实例"""
        service_class = cls._transfer_services.get(chain.upper())
        return service_class() if service_class else None
    
    @classmethod
    def get_price_service(cls, chain: str) -> Optional[BasePriceService]:
        """获取价格服务实例"""
        service_class = cls._price_services.get(chain.upper())
        return service_class() if service_class else None
    
    @classmethod
    def get_history_service(cls, chain: str) -> Optional[BaseHistoryService]:
        """获取历史记录服务实例"""
        service_class = cls._history_services.get(chain.upper())
        return service_class() if service_class else None
    
    @classmethod
    def get_token_info_service(cls, chain: str) -> Optional[BaseTokenInfoService]:
        """获取代币信息服务实例"""
        service_class = cls._token_info_services.get(chain.upper())
        return service_class() if service_class else None

    @classmethod
    def get_swap_service(cls, chain: str) -> Optional[BaseSwapService]:
        """获取代币兑换服务实例"""
        service_class = cls._swap_services.get(chain.upper())
        return service_class() if service_class else None

    @classmethod
    def get_nft_service(cls, chain: str) -> Optional[BaseNFTService]:
        """获取 NFT 服务实例"""
        service_class = cls._nft_services.get(chain.upper())
        return service_class() if service_class else None