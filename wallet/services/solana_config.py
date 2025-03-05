import os
from typing import Dict
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class RPCConfig:
    """Solana RPC 节点配置"""
    
    # API密钥配置
    ALCHEMY_API_KEY: str = os.getenv('ALCHEMY_API_KEY', '')
    
    # Solana RPC 节点配置
    SOLANA_MAINNET_RPC_URL: str = os.getenv('SOLANA_MAINNET_RPC_URL', 
        # 主要RPC节点
        f'https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}' if ALCHEMY_API_KEY else 
        # 公共RPC节点
        'https://api.mainnet-beta.solana.com'
    )
    SOLANA_TESTNET_RPC_URL: str = os.getenv('SOLANA_TESTNET_RPC_URL', 'https://api.testnet.solana.com')
    SOLANA_DEVNET_RPC_URL: str = os.getenv('SOLANA_DEVNET_RPC_URL', 'https://api.devnet.solana.com')
    
    @classmethod
    def get_rpc_endpoints(cls) -> Dict:
        """获取所有 RPC 节点配置"""
        return {
            'SOL': {
                'mainnet': cls.SOLANA_MAINNET_RPC_URL,
                'testnet': cls.SOLANA_TESTNET_RPC_URL,
                'devnet': cls.SOLANA_DEVNET_RPC_URL
            }
        }

class MoralisConfig:
    """Moralis Solana API 配置"""
    API_KEY: str = settings.MORALIS_API_KEY  # 从 Django settings 获取
    SOLANA_URL: str = 'https://solana-gateway.moralis.io'
    
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

class HeliusConfig:
    """Helius API 配置"""
    API_KEY = os.getenv('HELIUS_API_KEY')
    BASE_URL = "https://api.helius.xyz/v0"  # Helius API 基础URL
    
    # RPC 方法
    GET_ASSETS_BY_OWNER = "getAssetsByOwner"  # 获取用户的所有资产
    GET_TOKEN_ACCOUNTS = "getTokenAccounts"  # 获取代币账户
    GET_ASSET = "getAsset"  # 获取单个NFT详情
    GET_TOKEN_METADATA = "getTokenMetadata"  # 获取代币元数据
    GET_TOKEN_PRICES = "getTokenPrices"  # 获取代币价格
    
    # 转账记录接口
    TRANSACTIONS_URL = f"{BASE_URL}/addresses/{{address}}/transactions"  # 使用 transactions 端点
    
    @classmethod
    def get_rpc_url(cls) -> str:
        """获取 RPC URL"""
        if not cls.API_KEY:
            raise ValueError("未配置 HELIUS_API_KEY")
        return f"https://rpc.helius.xyz/?api-key={cls.API_KEY}"