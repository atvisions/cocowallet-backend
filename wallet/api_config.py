from typing import Dict, List
import os
from enum import Enum
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

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
            'BNB': cls.BSC_RPC_URL,  # 添加 BNB 作为 BSC 的别名
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
    
    @classmethod
    def get_headers(cls) -> Dict:
        """获取请求头"""
        if not cls.API_KEY:
            logger.error("未配置 MORALIS_API_KEY")
            raise ValueError("未配置 MORALIS_API_KEY")
            
        return {
            "accept": "application/json",
            "content-type": "application/json",
            "X-API-Key": cls.API_KEY
        }
    
    @classmethod
    def get_chain_id(cls, chain: str) -> str:
        """获取链 ID"""
        chain_id = cls.CHAIN_MAPPING.get(chain)
        if not chain_id:
            logger.error(f"不支持的链: {chain}")
            raise ValueError(f"不支持的链: {chain}")
        return chain_id

    @classmethod
    async def make_request(cls, url: str, params: Dict = None, method: str = 'GET', retry_count: int = 0) -> Dict:
        """发送API请求，包含重试机制
        
        Args:
            url: 请求URL
            params: 请求参数
            method: 请求方法
            retry_count: 当前重试次数
            
        Returns:
            Dict: 响应数据
        """
        import aiohttp
        import asyncio
        from aiohttp import ClientTimeout
        
        if retry_count >= cls.MAX_RETRIES:
            logger.error(f"达到最大重试次数: {cls.MAX_RETRIES}")
            raise Exception(f"达到最大重试次数: {cls.MAX_RETRIES}")
            
        try:
            logger.debug(f"发送请求到 Moralis API: {url}")
            logger.debug(f"请求参数: {params}")
            logger.debug(f"请求方法: {method}")
            logger.debug(f"重试次数: {retry_count}")
            
            timeout = ClientTimeout(total=cls.TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if method == 'GET':
                    async with session.get(url, headers=cls.get_headers(), params=params) as response:
                        response_text = await response.text()
                        logger.debug(f"Moralis API 响应状态码: {response.status}")
                        logger.debug(f"Moralis API 响应头: {response.headers}")
                        logger.debug(f"Moralis API 响应内容: {response_text}")
                        
                        if response.status == 429:  # Rate limit
                            wait_time = int(response.headers.get('Retry-After', cls.RETRY_INTERVAL))
                            logger.warning(f"触发 Moralis API 限流，等待 {wait_time} 秒后重试")
                            await asyncio.sleep(wait_time)
                            return await cls.make_request(url, params, method, retry_count + 1)
                            
                        if response.status != 200:
                            if retry_count < cls.MAX_RETRIES:
                                logger.warning(f"Moralis API 请求失败，状态码: {response.status}，{retry_count + 1} 秒后重试")
                                await asyncio.sleep(cls.RETRY_INTERVAL)
                                return await cls.make_request(url, params, method, retry_count + 1)
                            logger.error(f"Moralis API 请求失败: {response_text}")
                            raise Exception(f"请求失败: {response_text}")
                            
                        try:
                            return await response.json()
                        except Exception as e:
                            logger.error(f"解析 Moralis API 响应 JSON 失败: {str(e)}")
                            raise Exception(f"解析响应数据失败: {str(e)}")
                else:
                    async with session.post(url, headers=cls.get_headers(), json=params) as response:
                        response_text = await response.text()
                        logger.debug(f"Moralis API 响应状态码: {response.status}")
                        logger.debug(f"Moralis API 响应头: {response.headers}")
                        logger.debug(f"Moralis API 响应内容: {response_text}")
                        
                        if response.status == 429:  # Rate limit
                            wait_time = int(response.headers.get('Retry-After', cls.RETRY_INTERVAL))
                            logger.warning(f"触发 Moralis API 限流，等待 {wait_time} 秒后重试")
                            await asyncio.sleep(wait_time)
                            return await cls.make_request(url, params, method, retry_count + 1)
                            
                        if response.status != 200:
                            if retry_count < cls.MAX_RETRIES:
                                logger.warning(f"Moralis API 请求失败，状态码: {response.status}，{retry_count + 1} 秒后重试")
                                await asyncio.sleep(cls.RETRY_INTERVAL)
                                return await cls.make_request(url, params, method, retry_count + 1)
                            logger.error(f"Moralis API 请求失败: {response_text}")
                            raise Exception(f"请求失败: {response_text}")
                            
                        try:
                            return await response.json()
                        except Exception as e:
                            logger.error(f"解析 Moralis API 响应 JSON 失败: {str(e)}")
                            raise Exception(f"解析响应数据失败: {str(e)}")
                        
        except asyncio.TimeoutError:
            logger.error(f"Moralis API 请求超时")
            if retry_count < cls.MAX_RETRIES:
                logger.warning(f"请求超时，{retry_count + 1} 秒后重试")
                await asyncio.sleep(cls.RETRY_INTERVAL)
                return await cls.make_request(url, params, method, retry_count + 1)
            raise Exception("请求超时")
            
        except Exception as e:
            logger.error(f"Moralis API 请求出错: {str(e)}")
            if retry_count < cls.MAX_RETRIES:
                logger.warning(f"请求出错，{retry_count + 1} 秒后重试")
                await asyncio.sleep(cls.RETRY_INTERVAL)
                return await cls.make_request(url, params, method, retry_count + 1)
            raise e
    
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
    
    # API 请求超时时间(秒)
    TIMEOUT = 30
    
    # 最大重试次数
    MAX_RETRIES = 3
    
    # 重试间隔(秒)
    RETRY_INTERVAL = 1

class HeliusConfig:
    """Helius API 配置"""
    API_KEY = os.getenv('HELIUS_API_KEY', '')
    BASE_URL = "https://api.helius.xyz/v0"
    
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
        return f"https://rpc.helius.xyz/?api-key={cls.API_KEY}"
    
    @classmethod
    def get_headers(cls) -> Dict:
        """获取请求头
        
        Returns:
            Dict: 请求头
        """
        return {
            'Content-Type': 'application/json'
        }
        
    @classmethod
    def get_transactions_url(cls, address: str, before: str = None) -> str:
        """获取交易记录URL
        
        Args:
            address: 钱包地址
            before: 分页参数，上一页最后一条记录的签名
            
        Returns:
            str: 完整的API URL
        """
        params = {
            'api-key': cls.API_KEY,
            'type': ['TRANSFER', 'TOKEN_TRANSFER', 'NFT_TRANSFER', 'NFT_MINT', 'NFT_BURN', 'NFT_SALE', 'SWAP'],  # 指定交易类型
            'commitment': 'confirmed',  # 只获取已确认的交易
            'limit': '100'  # 每页返回的记录数
        }
        
        if before:
            params['before'] = before
            
        base_url = cls.TRANSACTIONS_URL.format(address=address)
        query_params = []
        for k, v in params.items():
            if v:
                if isinstance(v, list):
                    query_params.append(f"{k}={','.join(v)}")
                else:
                    query_params.append(f"{k}={v}")
        return f"{base_url}?{'&'.join(query_params)}"

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