from typing import Dict, Optional, List
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
class QuickNodeConfig:
    """QuickNode API 配置"""
    # Multi-chain RPC（用于 ETH、BSC、MATIC 等）
    MULTI_CHAIN_URL: str = os.getenv('QUICKNODE_MULTI_CHAIN_URL', '')
    MULTI_CHAIN_KEY: str = os.getenv('QUICKNODE_MULTI_CHAIN_KEY', '')
    
    # Solana RPC 和 DAS API
    SOLANA_URL: str = os.getenv(
        'QUICKNODE_SOLANA_URL',
        'https://serene-sly-voice.solana-mainnet.quiknode.pro/6a79cc4a87b9f9024abafc0783211ea381c4d181'
    )
    SOLANA_DAS_URL: str = SOLANA_URL
    SOLANA_DAS_KEY: str = os.getenv('QUICKNODE_SOLANA_DAS_KEY', '')
    SOLANA_ADDON_URL: str = f"{SOLANA_URL}/addon/748/v1"

@dataclass
class CryptoPriceConfig:
    """Crypto Price API 配置"""
    BASE_URL: str = os.getenv('CRYPTO_PRICE_API_URL', '')
    KEY: str = os.getenv('CRYPTO_PRICE_API_KEY', '')

@dataclass
class BTCConfig:
    """比特币 API 配置"""
    NODE_URL: str = os.getenv('BTC_NODE_URL', '')
    BLOCKCYPHER_URL: str = 'https://api.blockcypher.com/v1/btc/main'
    BLOCKCYPHER_TOKEN: str = os.getenv('BLOCKCYPHER_TOKEN', '')

class APIEndpoints:
    """API 端点配置"""
    
    # QuickNode Multi-chain 接口
    class MultiChain:
        GET_TOKEN_BALANCE = 'qn_getWalletTokenBalance'
        GET_TOKEN_METADATA = 'qn_getTokenMetadata'
        GET_NFT_BALANCE = 'qn_getWalletNFTBalance'
        GET_TRANSACTION_COUNT = 'eth_getTransactionCount'
        ESTIMATE_GAS = 'eth_estimateGas'
        GET_GAS_PRICE = 'eth_gasPrice'
        SEND_RAW_TRANSACTION = 'eth_sendRawTransaction'
    
    # Solana DAS 接口
    class SolanaDAS:
        # RPC 方法
        GET_TOKEN_ACCOUNTS = 'getTokenAccounts'
        GET_BALANCE = 'getBalance'
        GET_TOKEN_BALANCE = 'getTokenAccountBalance'
        
        # Addon API 端点
        GET_COINS = '/coins'  # 获取所有支持的代币列表
        GET_COIN_INFO = '/coins/{coin_id}'  # 获取代币详细信息
        GET_COIN_TICKERS = '/tickers/{coin_id}'  # 获取代币行情
        GET_TOKENS = '/tokens'  # 获取钱包代币列表
        GET_NFTS = '/nfts'  # 获取 NFT 列表
        GET_PORTFOLIO = '/portfolio'  # 获取投资组合
        GET_TOKEN_TRANSFERS = '/token-transfers'  # 获取代币转账记录
    
    # 价格 API 接口
    class Price:
        GET_SIMPLE_PRICE = '/simple/price'  # 获取简单价格
        GET_TOKEN_PRICE = '/coins/{id}/market_chart'  # 获取代币价格走势
        GET_MARKET_DATA = '/coins/markets'  # 获取市场数据
        GET_TICKERS = '/tickers'  # 获取行情数据
        GET_GLOBAL = '/global'  # 获取全局市场数据
    
    # BTC 接口
    class BTC:
        GET_BALANCE = '/addrs/{address}/balance'
        GET_UTXO = '/addrs/{address}?unspentOnly=true'
        PUSH_TRANSACTION = '/txs/push'

class APIConfig:
    """API 配置类"""
    
    # 当前环境
    ENVIRONMENT: Environment = Environment(os.getenv('ENVIRONMENT', Environment.DEVELOPMENT))
    
    # API 配置实例
    QUICKNODE = QuickNodeConfig()
    CRYPTO_PRICE = CryptoPriceConfig()
    BTC = BTCConfig()
    
    # 链对应的 RPC URL
    CHAIN_RPC_URLS: Dict[Chain, str] = {
        Chain.ETH: QUICKNODE.MULTI_CHAIN_URL,
        Chain.BNB: QUICKNODE.MULTI_CHAIN_URL,
        Chain.MATIC: QUICKNODE.MULTI_CHAIN_URL,
        Chain.AVAX: QUICKNODE.MULTI_CHAIN_URL,
        Chain.SOL: QUICKNODE.SOLANA_URL,
        Chain.BTC: BTC.NODE_URL,
    }
    
    # API 请求配置
    REQUEST_TIMEOUT = 30  # 请求超时时间（秒）
    MAX_RETRIES = 3      # 最大重试次数
    
    # 缓存配置
    CACHE_CONFIG = {
        Environment.DEVELOPMENT: {
            'TIMEOUT': 300,           # 缓存超时时间（秒）
            'MAX_TOKENS': 100,        # 每次请求最大代币数量
            'PRICE_UPDATE': 60,       # 价格更新间隔（秒）
        },
        Environment.PRODUCTION: {
            'TIMEOUT': 60,
            'MAX_TOKENS': 500,
            'PRICE_UPDATE': 30,
        }
    }
    
    @classmethod
    def get_cache_config(cls) -> Dict:
        """获取当前环境的缓存配置"""
        return cls.CACHE_CONFIG[cls.ENVIRONMENT]
    
    @classmethod
    def get_rpc_url(cls, chain: Chain) -> str:
        """获取 RPC URL"""
        return cls.CHAIN_RPC_URLS[chain]
    
    @classmethod
    def get_das_url(cls) -> str:
        """获取 Solana DAS URL"""
        return os.getenv('SOLANA_DAS_URL', cls.QUICKNODE.SOLANA_URL)
    
    @classmethod
    def get_btc_api_url(cls) -> str:
        """获取比特币 API URL"""
        return cls.BTC.NODE_URL
    
    @classmethod
    def get_price_api_url(cls) -> str:
        """获取价格 API URL"""
        return cls.CRYPTO_PRICE.BASE_URL
    
    @classmethod
    def get_solana_api_url(cls) -> str:
        """获取 Solana API URL"""
        return cls.QUICKNODE.SOLANA_URL
    
    @classmethod
    def get_solana_addon_url(cls) -> str:
        """获取 Solana Addon API URL"""
        return f"{cls.QUICKNODE.SOLANA_URL}/addon/748/v1"
    
    @classmethod
    def get_solana_rpc_payload(cls, method: str, params: List = None) -> Dict:
        """获取 Solana RPC 请求负载"""
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or []
        }
    
    @classmethod
    def get_headers(cls, chain: Chain = None) -> Dict:
        """获取请求头"""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        if chain in [Chain.ETH, Chain.BNB, Chain.MATIC, Chain.AVAX]:
            if cls.QUICKNODE.MULTI_CHAIN_KEY:
                headers['x-api-key'] = cls.QUICKNODE.MULTI_CHAIN_KEY
        elif chain == Chain.SOL:
            if cls.QUICKNODE.SOLANA_DAS_KEY:
                headers['x-api-key'] = cls.QUICKNODE.SOLANA_DAS_KEY
        elif chain == Chain.BTC:
            if cls.BTC.BLOCKCYPHER_TOKEN:
                headers['Authorization'] = f'Token {cls.BTC.BLOCKCYPHER_TOKEN}'
        
        return headers 