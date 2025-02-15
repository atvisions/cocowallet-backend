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
class RPCConfig:
    """RPC 节点配置"""
    
    # API密钥配置
    ALCHEMY_API_KEY: str = os.getenv('ALCHEMY_API_KEY', '')
    QUICKNODE_API_KEY: str = os.getenv('QUICKNODE_API_KEY', '')
    
    # Alchemy API 配置
    ALCHEMY_BASE_URL = "https://{}.g.alchemy.com/v2"
    
    # 原生代币配置
    NATIVE_TOKENS = {
        'ETH': {
            'address': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',  # WETH
            'name': 'Ethereum',
            'symbol': 'ETH',
            'decimals': 18,
            'logo': 'https://assets.coingecko.com/coins/images/279/large/ethereum.png'
        },
        'BSC': {
            'address': '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',  # WBNB
            'name': 'BNB',
            'symbol': 'BNB',
            'decimals': 18,
            'logo': 'https://assets.coingecko.com/coins/images/825/large/bnb-icon2_2x.png'
        },
        'MATIC': {
            'address': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270',  # WMATIC
            'name': 'Polygon',
            'symbol': 'MATIC',
            'decimals': 18,
            'logo': 'https://assets.coingecko.com/coins/images/4713/large/matic-token-icon.png'
        },
        'AVAX': {
            'address': '0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7',  # WAVAX
            'name': 'Avalanche',
            'symbol': 'AVAX',
            'decimals': 18,
            'logo': 'https://assets.coingecko.com/coins/images/12559/large/coin-round-red.png'
        },
        'ARBITRUM': {
            'address': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',  # WETH
            'name': 'Ethereum',
            'symbol': 'ETH',
            'decimals': 18,
            'logo': 'https://assets.coingecko.com/coins/images/279/large/ethereum.png'
        },
        'OPTIMISM': {
            'address': '0x4200000000000000000000000000000000000006',  # WETH
            'name': 'Ethereum',
            'symbol': 'ETH',
            'decimals': 18,
            'logo': 'https://assets.coingecko.com/coins/images/279/large/ethereum.png'
        },
        'BASE': {
            'address': '0x4200000000000000000000000000000000000006',  # WETH
            'name': 'Ethereum',
            'symbol': 'ETH',
            'decimals': 18,
            'logo': 'https://assets.coingecko.com/coins/images/279/large/ethereum.png'
        }
    }
    
    # 链到 Alchemy 网络的映射
    ALCHEMY_NETWORKS = {
        'ETH': 'eth-mainnet',
        'MATIC': 'polygon-mainnet',
        'AVAX': 'avalanche-mainnet',
        'BASE': 'base-mainnet',
        'ARBITRUM': 'arb-mainnet',
        'OPTIMISM': 'opt-mainnet'
    }
    
    @classmethod
    def get_alchemy_url(cls, chain: str) -> str:
        """获取 Alchemy API URL
        
        Args:
            chain: 链标识
            
        Returns:
            str: Alchemy API URL
        """
        network = cls.ALCHEMY_NETWORKS.get(chain)
        if not network:
            raise ValueError(f"不支持的链: {chain}")
        return f"{cls.ALCHEMY_BASE_URL.format(network)}/{cls.ALCHEMY_API_KEY}"
    
    # EVM 链 RPC 节点
    ETH_RPC_URL: str = os.getenv('ETH_RPC_URL', f'https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}')
    BSC_RPC_URL: str = os.getenv('BSC_RPC_URL', 'https://bsc-dataseed.binance.org')
    POLYGON_RPC_URL: str = os.getenv('POLYGON_RPC_URL', f'https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}')
    AVAX_RPC_URL: str = os.getenv('AVAX_RPC_URL', f'https://avalanche-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}')
    ARBITRUM_RPC_URL: str = os.getenv('ARBITRUM_RPC_URL', f'https://arb-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}')
    OPTIMISM_RPC_URL: str = os.getenv('OPTIMISM_RPC_URL', f'https://opt-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}')
    BASE_RPC_URL: str = os.getenv('BASE_RPC_URL', f'https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}')
    
    # Solana RPC 节点配置
    SOLANA_MAINNET_RPC_URL: str = os.getenv('SOLANA_MAINNET_RPC_URL', 
        # 主要RPC节点
        f'https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}' if ALCHEMY_API_KEY else 
        # 公共RPC节点
        'https://api.mainnet-beta.solana.com'
    )
    SOLANA_TESTNET_RPC_URL: str = os.getenv('SOLANA_TESTNET_RPC_URL', 'https://api.testnet.solana.com')
    SOLANA_DEVNET_RPC_URL: str = os.getenv('SOLANA_DEVNET_RPC_URL', 'https://api.devnet.solana.com')
    
    # RPC 节点映射
    @classmethod
    def get_rpc_endpoints(cls) -> Dict:
        """获取所有 RPC 节点配置"""
        return {
            'ETH': cls.ETH_RPC_URL,
            'BSC': cls.BSC_RPC_URL,
            'MATIC': cls.POLYGON_RPC_URL,
            'AVAX': cls.AVAX_RPC_URL,
            'ARBITRUM': cls.ARBITRUM_RPC_URL,
            'OPTIMISM': cls.OPTIMISM_RPC_URL,
            'BASE': cls.BASE_RPC_URL,
            'SOL': {
                'mainnet': cls.SOLANA_MAINNET_RPC_URL,
                'testnet': cls.SOLANA_TESTNET_RPC_URL,
                'devnet': cls.SOLANA_DEVNET_RPC_URL
            }
        }

class MoralisConfig:
    """Moralis API 配置"""
    API_KEY: str = os.getenv('MORALIS_API_KEY', '')
    BASE_URL: str = 'https://deep-index.moralis.io/api/v2.2'
    SOLANA_URL: str = 'https://solana-gateway.moralis.io'
    
    # EVM 代币相关接口
    EVM_TOKEN_PRICE_URL: str = f"{BASE_URL}/erc20/{{0}}/price"  # 获取代币价格
    EVM_TOKEN_PAIRS_URL: str = f"{BASE_URL}/erc20/{{0}}/pairs"  # 获取代币交易对
    EVM_TOKEN_PRICE_CHART_URL: str = f"{BASE_URL}/pairs/{{0}}/ohlcv"  # 获取代币价格历史
    EVM_TOKEN_METADATA_URL: str = f"{BASE_URL}/erc20/metadata"  # 获取代币元数据
    EVM_WALLET_TOKENS_URL: str = f"{BASE_URL}/{{0}}/erc20"  # 获取钱包代币列表
    EVM_TOKEN_TRANSFERS_URL: str = f"{BASE_URL}/{{0}}/erc20/transfers"  # 获取代币转账历史
    EVM_TOKEN_HOLDERS_URL: str = f"{BASE_URL}/erc20/{{0}}/holders"  # 获取代币持有者
    
    # Solana 价格和元数据查询接口
    SOLANA_TOKEN_PRICE_URL: str = f"{SOLANA_URL}/token/mainnet/{{}}/price"  # 获取代币价格
    SOLANA_TOKEN_PAIRS_URL: str = f"{SOLANA_URL}/token/mainnet/{{}}/pairs"  # 获取代币交易对
    SOLANA_TOKEN_PAIRS_PRICE_URL: str = f"{SOLANA_URL}/token/mainnet/pairs/{{}}/price"  # 获取交易对价格
    SOLANA_TOKEN_PAIRS_OHLCV_URL: str = f"{SOLANA_URL}/token/mainnet/pairs/{{}}/ohlcv"  # 获取K线数据
    SOLANA_TOKEN_METADATA_URL: str = f"{SOLANA_URL}/token/mainnet/{{}}/metadata"  # 获取代币元数据
    SOLANA_ACCOUNT_BALANCE_URL: str = f"{SOLANA_URL}/account/mainnet/{{}}/balance"  # 获取账户余额
    SOLANA_ACCOUNT_TOKENS_URL: str = f"{SOLANA_URL}/account/mainnet/{{}}/tokens"  # 获取账户代币列表
    
    # Solana NFT 相关接口（未启用）
    SOLANA_NFT_LIST_URL: str = f"{SOLANA_URL}/account/{{0}}/{{1}}/nft"  # 获取地址的NFTs，参数: network, address
    SOLANA_NFT_METADATA_URL: str = f"{SOLANA_URL}/nft/{{0}}/{{1}}/metadata"  # 获取NFT元数据，参数: network, address
    
    # Solana Swap 相关接口，（未启用）
    SOLANA_ACCOUNT_SWAPS_URL: str = f"{SOLANA_URL}/account/mainnet/{{}}/swaps"  # 获取账户 swap 历史
    SOLANA_SWAP_QUOTE_URL: str = f"{SOLANA_URL}/swap/mainnet/quote"  # 获取 swap 报价
    SOLANA_SWAP_EXECUTE_URL: str = f"{SOLANA_URL}/swap/mainnet/execute"  # 执行 swap 交易
    
    # API 请求头
    @classmethod
    def get_headers(cls) -> Dict:
        """获取请求头"""
        return {
            "accept": "application/json",
            "X-API-Key": cls.API_KEY
        }
    
    # 链 ID 映射
    CHAIN_MAPPING = {
        'ETH': 'eth',
        'BSC': 'bsc',
        'MATIC': 'polygon',
        'AVAX': 'avalanche',
        'ARBITRUM': 'arbitrum',
        'OPTIMISM': 'optimism',
        'BASE': 'base'
    }
    
    @classmethod
    def get_chain_id(cls, chain: str) -> str:
        """获取链 ID"""
        chain_id = cls.CHAIN_MAPPING.get(chain)
        if not chain_id:
            raise ValueError(f"不支持的链: {chain}")
        return chain_id
    
    # API 请求超时时间(秒)
    TIMEOUT = 30
    
    # 最大重试次数
    MAX_RETRIES = 3
    
    # 重试间隔(秒)
    RETRY_INTERVAL = 1

class HeliusConfig:
    """Helius API 配置"""
    API_KEY = os.getenv('HELIUS_API_KEY', '')
    BASE_URL = f"https://rpc.helius.xyz/?api-key={API_KEY}"

    # RPC 方法
    GET_ASSETS_BY_OWNER = "getAssetsByOwner"  # 获取用户的所有资产
    GET_TOKEN_ACCOUNTS = "getTokenAccounts"  # 获取代币账户
    GET_ASSET = "getAsset"  # 获取单个NFT详情
    GET_TOKEN_METADATA = "getTokenMetadata"  # 获取代币元数据
    GET_TOKEN_PRICES = "getTokenPrices"  # 获取代币价格
    
    @classmethod
    def get_rpc_url(cls) -> str:
        """获取 RPC URL"""
        return cls.BASE_URL

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
    
    # RPC 配置实例
    RPC = RPCConfig()