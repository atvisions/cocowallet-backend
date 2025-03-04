from typing import Dict, Optional, Union, Any

from .evm.balance import EVMBalanceService
from .evm.token_info import EVMTokenInfoService
from .evm.transfer import EVMTransferService
from .evm.swap import EVMSwapService
from .evm.nft import EVMNFTService
from .evm.history import EVMHistoryService
from .evm.price import EVMPriceService

from .solana.balance import SolanaBalanceService
from .solana.token_info import SolanaTokenInfoService
from .solana.transfer import SolanaTransferService
from .solana.swap import SolanaSwapService
from .solana.nft import SolanaNFTService
from .solana.history import SolanaHistoryService
from .solana.price import SolanaPriceService

# TODO: 添加 Ethereum 服务实现

class ChainServiceFactory:
    """链服务工厂类"""
    
    _balance_services: Dict[str, Union[EVMBalanceService, SolanaBalanceService]] = {}
    _token_info_services: Dict[str, Union[EVMTokenInfoService, SolanaTokenInfoService]] = {}
    _transfer_services: Dict[str, Union[EVMTransferService, SolanaTransferService]] = {}
    _swap_services: Dict[str, Union[EVMSwapService, SolanaSwapService]] = {}
    _nft_services: Dict[str, Union[EVMNFTService, SolanaNFTService]] = {}
    _history_services: Dict[str, Union[EVMHistoryService, SolanaHistoryService]] = {}
    _price_services: Dict[str, Union[EVMPriceService, SolanaPriceService]] = {}
    
    @classmethod
    def get_service(cls, chain: str, service_type: str) -> Any:
        """获取指定类型的链服务实例
        
        Args:
            chain: 链类型（如'SOL'、'ETH'等）
            service_type: 服务类型（如'balance'、'token_info'等）
            
        Returns:
            对应的服务实例
        """
        service_map = {
            'balance': cls.get_balance_service,
            'token_info': cls.get_token_info_service,
            'transfer': cls.get_transfer_service,
            'swap': cls.get_swap_service,
            'nft': cls.get_nft_service,
            'history': cls.get_history_service,
            'price': cls.get_price_service
        }
        
        if service_type not in service_map:
            raise ValueError(f'不支持的服务类型: {service_type}')
            
        return service_map[service_type](chain)
    
    @classmethod
    def get_balance_service(cls, chain: str) -> Union[EVMBalanceService, SolanaBalanceService]:
        """获取余额服务"""
        if chain not in cls._balance_services:
            if chain == 'SOL':
                cls._balance_services[chain] = SolanaBalanceService()
            else:
                cls._balance_services[chain] = EVMBalanceService(chain)
        return cls._balance_services[chain]
    
    @classmethod
    def get_token_info_service(cls, chain: str) -> Union[EVMTokenInfoService, SolanaTokenInfoService]:
        """获取代币信息服务"""
        if chain not in cls._token_info_services:
            if chain == 'SOL':
                cls._token_info_services[chain] = SolanaTokenInfoService()
            else:
                cls._token_info_services[chain] = EVMTokenInfoService(chain)
        return cls._token_info_services[chain]
    
    @classmethod
    def get_transfer_service(cls, chain: str) -> Any:
        """获取转账服务"""
        if chain == 'SOL':
            from .solana.transfer import SolanaTransferService
            return SolanaTransferService()
        # ... 其他链的处理 ...
    
    @classmethod
    def get_swap_service(cls, chain: str) -> Union[EVMSwapService, SolanaSwapService]:
        """获取兑换服务"""
        if chain not in cls._swap_services:
            if chain == 'SOL':
                cls._swap_services[chain] = SolanaSwapService()
            else:
                cls._swap_services[chain] = EVMSwapService(chain)
        return cls._swap_services[chain]
    
    @classmethod
    def get_nft_service(cls, chain: str) -> Union[EVMNFTService, SolanaNFTService]:
        """获取NFT服务"""
        if chain not in cls._nft_services:
            if chain == 'SOL':
                cls._nft_services[chain] = SolanaNFTService()
            else:
                cls._nft_services[chain] = EVMNFTService(chain)
        return cls._nft_services[chain]
    
    @classmethod
    def get_history_service(cls, chain: str) -> Union[EVMHistoryService, SolanaHistoryService]:
        """获取历史记录服务"""
        if chain not in cls._history_services:
            if chain == 'SOL':
                cls._history_services[chain] = SolanaHistoryService()
            else:
                cls._history_services[chain] = EVMHistoryService(chain)
        return cls._history_services[chain]
    
    @classmethod
    def get_price_service(cls, chain: str) -> Union[EVMPriceService, SolanaPriceService]:
        """获取价格服务"""
        if chain not in cls._price_services:
            if chain == 'SOL':
                cls._price_services[chain] = SolanaPriceService()
            else:
                cls._price_services[chain] = EVMPriceService(chain)
        return cls._price_services[chain]