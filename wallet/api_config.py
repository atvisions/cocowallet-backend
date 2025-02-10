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
    
    # EVM 链 RPC 节点
    ETH_RPC_URL: str = os.getenv('ETH_RPC_URL', 'https://eth-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7')
    BSC_RPC_URL: str = os.getenv('BSC_RPC_URL', 'https://bsc-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7')
    POLYGON_RPC_URL: str = os.getenv('POLYGON_RPC_URL', 'https://polygon-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7')
    AVAX_RPC_URL: str = os.getenv('AVAX_RPC_URL', 'https://avalanche-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7')
    ARBITRUM_RPC_URL: str = os.getenv('ARBITRUM_RPC_URL', 'https://arb-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7')
    OPTIMISM_RPC_URL: str = os.getenv('OPTIMISM_RPC_URL', 'https://opt-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7')
    BASE_RPC_URL: str = os.getenv('BASE_RPC_URL', 'https://base-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7')
    
    # Solana RPC 节点
    SOLANA_MAINNET_RPC_URL: str = os.getenv('SOLANA_MAINNET_RPC_URL', 'https://api.mainnet-beta.solana.com')
    SOLANA_TESTNET_RPC_URL: str = os.getenv('SOLANA_TESTNET_RPC_URL', 'https://api.testnet.solana.com')
    SOLANA_DEVNET_RPC_URL: str = os.getenv('SOLANA_DEVNET_RPC_URL', 'https://api.devnet.solana.com')
    
    # Solana 备用节点
    @property
    def SOLANA_BACKUP_NODES(self) -> List[str]:
        """获取 Solana 备用节点列表"""
        return [
            'https://api.mainnet-beta.solana.com',
            'https://solana.public-rpc.com',
            'https://rpc.ankr.com/solana',
            'https://solana-api.projectserum.com',
            'https://solana.getblock.io/mainnet',
            'https://mainnet.rpcpool.com',
            'https://free.rpcpool.com',
            'https://solana.api.chainstack.com/mainnet',
            'https://solana-mainnet.rpc.extrnode.com',
            'https://solana.api.onfinality.io/public',
            'https://solana.publicnode.com',
            'https://solana-mainnet.g.alchemy.com/v2/demo'
        ]
    
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
                'devnet': cls.SOLANA_DEVNET_RPC_URL,
                'backup': cls.SOLANA_BACKUP_NODES
            }
        }

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
    SOLANA_TOKEN_PRICE_URL: str = f"{SOLANA_URL}/token/mainnet/{{}}/price"  # 获取代币价格
    SOLANA_TOKEN_PAIRS_URL: str = f"{SOLANA_URL}/token/mainnet/{{}}/pairs"  # 获取代币交易对
    SOLANA_TOKEN_PAIRS_PRICE_URL: str = f"{SOLANA_URL}/token/mainnet/pairs/{{}}/price"  # 获取交易对价格
    SOLANA_TOKEN_PAIRS_OHLCV_URL: str = f"{SOLANA_URL}/token/mainnet/pairs/{{}}/ohlcv"  # 获取K线数据
    SOLANA_TOKEN_METADATA_URL: str = f"{SOLANA_URL}/token/mainnet/{{}}/metadata"  # 获取代币元数据
    SOLANA_ACCOUNT_BALANCE_URL: str = f"{SOLANA_URL}/account/mainnet/{{}}/balance"  # 获取账户余额
    SOLANA_ACCOUNT_TOKENS_URL: str = f"{SOLANA_URL}/account/mainnet/{{}}/tokens"  # 获取账户代币列表
    
    # API 请求超时时间(秒)
    TIMEOUT = 30
    
    # 最大重试次数
    MAX_RETRIES = 3
    
    # 重试间隔(秒)
    RETRY_INTERVAL = 1

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