from typing import Dict, List
import os
from enum import Enum
from dataclasses import dataclass

class Chain(str, Enum):
    """支持的区块链枚举"""
    BTC = 'BTC'
    ETH = 'ETH'
    BNB = 'BNB'
    MATIC = 'MATIC'
    AVAX = 'AVAX'
    SOL = 'SOL'

class Environment(str, Enum):
    """环境枚举"""
    DEVELOPMENT = 'development'
    PRODUCTION = 'production'

@dataclass
class MoralisConfig:
    """Moralis API 配置"""
    API_KEY: str = os.getenv('MORALIS_API_KEY', '')
    BASE_URL: str = 'https://deep-index.moralis.io/api/v2.2'
    SOLANA_URL: str = 'https://solana-gateway.moralis.io'
    
    # EVM价格和元数据查询接口
    EVM_TOKEN_PRICE_URL: str = f"{BASE_URL}/erc20/{{}}/price"
    EVM_TOKEN_PRICE_HISTORY_URL: str = f"{BASE_URL}/erc20/{{}}/price/history"
    EVM_TOKEN_METADATA_URL: str = f"{BASE_URL}/erc20/metadata"
    EVM_WALLET_TOKENS_URL: str = f"{BASE_URL}/wallets/{{0}}/tokens"
    EVM_WALLET_NATIVE_BALANCE_URL: str = f"{BASE_URL}/{{0}}/balance"
    EVM_TOKEN_PRICE_BATCH_URL: str = f"{BASE_URL}/chains/{{0}}/native-price"
    
    # Solana价格和元数据查询接口
    SOLANA_TOKEN_PRICE_URL: str = f"{SOLANA_URL}/token/mainnet/{{}}/price"
    SOLANA_TOKEN_PRICE_HISTORY_URL: str = f"{SOLANA_URL}/token/mainnet/pairs/{{}}/ohlcv"
    SOLANA_TOKEN_METADATA_URL: str = f"{SOLANA_URL}/token/mainnet/{{}}/metadata"
    SOLANA_ACCOUNT_BALANCE_URL: str = f"{SOLANA_URL}/account/mainnet/{{}}/balance"
    SOLANA_ACCOUNT_TOKENS_URL: str = f"{SOLANA_URL}/account/mainnet/{{}}/tokens"

class APIEndpoints:
    """API 端点配置"""
    
    # Moralis API 接口
    class Moralis:
        # EVM 链接口
        GET_NATIVE_BALANCE = '/wallets/{address}/balance'
        GET_TOKEN_BALANCES = '/{address}/erc20'
        GET_NFT_COLLECTIONS = '/{address}/nft/collections'
        GET_NFTS = '/{address}/nft'
        GET_NFT_TRANSFERS = '/{address}/nft/transfers'
        GET_TOKEN_TRANSFERS = '/{address}/erc20/transfers'
        GET_NATIVE_TRANSFERS = '/{address}/transfers'
        GET_TOKEN_METADATA = '/erc20/metadata'
        GET_NFT_METADATA = '/nft/{address}/{token_id}'
        
        # Solana 接口
        SOLANA_GET_BALANCE = '/account/{address}/balance'
        SOLANA_GET_NFTS = '/account/{address}/nft'
        SOLANA_GET_PORTFOLIO = '/account/{address}/portfolio'
        SOLANA_GET_TOKEN_TRANSFERS = '/account/{address}/transfers'
        SOLANA_GET_TOKEN_METADATA = '/token/metadata'
        SOLANA_GET_TOKEN_PRICE = '/token/mainnet/{address}/price'
        SOLANA_GET_NFT_METADATA = '/nft/{address}/metadata'
        SOLANA_GET_NFT_PRICE = '/nft/{address}/price'
        SOLANA_GET_TOKEN_TRANSFERS = '/account/{address}/token/transfers'
        SOLANA_GET_SPL_TOKENS = '/account/{address}/tokens'

class APIConfig:
    """API 配置类"""
    
    # 当前环境
    ENVIRONMENT: Environment = Environment(os.getenv('ENVIRONMENT', Environment.DEVELOPMENT))
    
    # API 配置实例
    MORALIS = MoralisConfig()
    
    # 链到 Moralis 链 ID 的映射
    CHAIN_TO_MORALIS = {
        Chain.ETH: 'eth',
        Chain.BNB: 'bsc',
        Chain.MATIC: 'polygon',
        Chain.AVAX: 'avalanche',
        Chain.SOL: 'solana'
    }
    
    @staticmethod
    def get_cache_config():
        """获取缓存配置"""
        return {
            'TIMEOUT': 300  # 5分钟缓存时间
        }