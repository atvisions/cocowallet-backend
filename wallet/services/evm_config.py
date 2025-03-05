from typing import Dict
import os
from enum import Enum
from dataclasses import dataclass
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class RPCConfig:
    """RPC 节点配置"""
    
    # API密钥配置
    ALCHEMY_API_KEY: str = os.getenv('ALCHEMY_API_KEY', '')
    QUICKNODE_API_KEY: str = os.getenv('QUICKNODE_API_KEY', '')
    
    # Alchemy API 配置
    ALCHEMY_BASE_URL = "https://{}.g.alchemy.com/v2"
    
    # DEX 配置
    DEX_CONFIG = {
        'ETH': {
            'router_address': '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',  # Uniswap V2 Router
            'factory_address': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f',  # Uniswap V2 Factory
            'name': 'Uniswap V2'
        },
        'BSC': {
            'router_address': '0x10ED43C718714eb63d5aA57B78B54704E256024E',  # PancakeSwap V2 Router
            'factory_address': '0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73',  # PancakeSwap V2 Factory
            'name': 'PancakeSwap V2'
        },
        'MATIC': {
            'router_address': '0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff',  # QuickSwap Router
            'factory_address': '0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32',  # QuickSwap Factory
            'name': 'QuickSwap'
        },
        'AVAX': {
            'router_address': '0x60aE616a2155Ee3d9A68541Ba4544862310933d4',  # TraderJoe Router
            'factory_address': '0x9Ad6C38BE94206cA50bb0d90783181662f0Cfa10',  # TraderJoe Factory
            'name': 'TraderJoe'
        },
        'BASE': {
            'router_address': '0x327Df1E6de05895d2ab08513aaDD9313Fe505d86',  # BaseSwap Router
            'factory_address': '0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB',  # BaseSwap Factory
            'name': 'BaseSwap'
        },
        'ARBITRUM': {
            'router_address': '0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506',  # SushiSwap Router
            'factory_address': '0xc35DADB65012eC5796536bD9864eD8773aBc74C4',  # SushiSwap Factory
            'name': 'SushiSwap'
        },
        'OPTIMISM': {
            'router_address': '0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45',  # Uniswap V3 Router
            'factory_address': '0x1F98431c8aD98523631AE4a59f267346ea31F984',  # Uniswap V3 Factory
            'name': 'Uniswap V3'
        }
    }
    
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
        'OPTIMISM': 'opt-mainnet',
        'BNB': 'bsc',  # 添加 BNB 映射
        'BSC': 'bsc'
    }
    
    @classmethod
    def get_alchemy_url(cls, chain: str) -> str:
        """获取 Alchemy API URL
        
        Args:
            chain: 链标识
            
        Returns:
            str: Alchemy API URL
        """
        # 对于 BNB/BSC 链，直接返回 BSC RPC URL
        if chain in ['BNB', 'BSC']:
            return cls.BSC_RPC_URL
            
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
    
    @classmethod
    def get_rpc_endpoints(cls) -> Dict:
        """获取所有 RPC 节点配置"""
        return {
            'ETH': cls.ETH_RPC_URL,
            'BSC': cls.BSC_RPC_URL,
            'BNB': cls.BSC_RPC_URL,  # 添加 BNB 作为 BSC 的别名
            'MATIC': cls.POLYGON_RPC_URL,
            'AVAX': cls.AVAX_RPC_URL,
            'ARBITRUM': cls.ARBITRUM_RPC_URL,
            'OPTIMISM': cls.OPTIMISM_RPC_URL,
            'BASE': cls.BASE_RPC_URL
        }

class MoralisConfig:
    """Moralis API 配置"""
    API_KEY: str = settings.MORALIS_API_KEY
    BASE_URL: str = 'https://deep-index.moralis.io/api/v2.2'
    TIMEOUT: int = 30  # 添加超时配置，单位为秒
    
    # 链 ID 映射
    CHAIN_MAPPING = {
        'ETH': 'eth',
        'BSC': 'bsc',
        'BNB': 'bsc',  # 添加 BNB 作为 BSC 的别名
        'MATIC': 'polygon',
        'AVAX': 'avalanche',
        'ARBITRUM': 'arbitrum',
        'OPTIMISM': 'optimism',
        'BASE': 'base'
    }
    
    # EVM 代币相关接口
    EVM_TOKEN_PRICE_URL: str = f"{BASE_URL}/erc20/{{0}}/price"  # 获取代币价格
    EVM_TOKEN_PAIRS_URL: str = f"{BASE_URL}/erc20/{{0}}/pairs"  # 获取代币交易对
    EVM_TOKEN_PRICE_CHART_URL: str = f"{BASE_URL}/pairs/{{0}}/ohlcv"  # 获取代币价格历史
    EVM_TOKEN_METADATA_URL: str = f"{BASE_URL}/erc20/metadata"  # 获取代币元数据
    EVM_WALLET_TOKENS_URL: str = f"{BASE_URL}/{{0}}/erc20"  # 获取钱包代币列表
    EVM_TOKEN_TRANSFERS_URL: str = f"{BASE_URL}/{{0}}/erc20/transfers"  # 获取代币转账历史
    EVM_TOKEN_HOLDERS_URL: str = f"{BASE_URL}/erc20/{{0}}/holders"  # 获取代币持有者
    
    # EVM Swap 相关接口
    EVM_SWAP_QUOTE_URL: str = f"{BASE_URL}/erc20/{{0}}/swaps"  # 获取兑换历史
    EVM_SWAP_EXECUTE_URL: str = f"{BASE_URL}/erc20/{{0}}/swaps"  # 获取兑换历史
    EVM_SWAP_PAIRS_URL: str = f"{BASE_URL}/pairs/{{0}}/swaps"  # 获取交易对兑换历史
    EVM_SWAP_WALLET_URL: str = f"{BASE_URL}/wallets/{{0}}/swaps"  # 获取钱包兑换历史
    EVM_SWAP_TOKEN_URL: str = f"{BASE_URL}/erc20/{{0}}/swaps"  # 获取代币兑换历史

    @classmethod
    def get_chain_id(cls, chain: str) -> str:
        """根据链名称获取对应的链ID"""
        chain = chain.upper()
        if chain not in cls.CHAIN_MAPPING:
            raise ValueError(f"不支持的链类型: {chain}")
        return cls.CHAIN_MAPPING[chain]

    @classmethod
    def get_headers(cls) -> dict:
        """获取API请求头"""
        return {"X-API-Key": cls.API_KEY}