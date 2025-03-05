"""EVM 余额查询服务"""
import logging
from typing import Dict, List, Optional
from decimal import Decimal
import aiohttp
import json
from web3 import Web3
from django.core.cache import cache
from asgiref.sync import sync_to_async

from ...models import Wallet, Token
from ..evm_config import MoralisConfig, RPCConfig
from ...exceptions import WalletNotFoundError, ChainNotSupportError, GetBalanceError
from .utils import EVMUtils
from .token_info import EVMTokenInfoService

logger = logging.getLogger(__name__)

# ERC20 代币 ABI
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    }
]

class EVMBalanceService:
    """EVM 余额查询服务实现类"""

    def __init__(self, chain: str):
        """初始化
        
        Args:
            chain: 链标识(ETH/BSC/POLYGON/AVAX/BASE)
        """
        self.chain = chain
        self.chain_config = EVMUtils.get_chain_config(chain)
        self.web3 = EVMUtils.get_web3(chain)
        self.token_info_service = EVMTokenInfoService(chain)
        
        # Moralis API 配置
        self.chain_id = MoralisConfig.get_chain_id(chain)
        self.headers = MoralisConfig.get_headers()
        self.timeout = aiohttp.ClientTimeout(total=MoralisConfig.TIMEOUT)

    async def get_wallet(self, wallet_id: int) -> Optional[Wallet]:
        """获取钱包
        
        Args:
            wallet_id: 钱包ID
            
        Returns:
            Optional[Wallet]: 钱包对象
        """
        try:
            wallet = await sync_to_async(Wallet.objects.get)(id=wallet_id, is_active=True)
            return wallet
        except Wallet.DoesNotExist:
            return None

    async def get_native_balance(self, address: str) -> Decimal:
        """获取原生代币余额
        
        Args:
            address: 钱包地址
            
        Returns:
            Decimal: 余额
        """
        try:
            # 使用 web3 获取原生代币余额
            balance_wei = self.web3.eth.get_balance(Web3.to_checksum_address(address))
            return EVMUtils.from_wei(balance_wei)
                        
        except Exception as e:
            logger.error(f"获取原生代币余额失败: {str(e)}")
            return Decimal('0')

    async def get_token_balance(self, wallet_id: int, token_address: Optional[str] = None) -> dict:
        """获取代币余额
        
        Args:
            wallet_id: 钱包ID
            token_address: 代币合约地址，如果是原生代币则使用 NATIVE_TOKEN_ADDRESS
            
        Returns:
            dict: 代币余额信息
        """
        try:
            wallet = await self.get_wallet(wallet_id)
            if not wallet:
                raise WalletNotFoundError()
                
            # 获取链配置
            chain_config = EVMUtils.get_chain_config(wallet.chain)
            if not chain_config:
                raise ChainNotSupportError()
                
            # 获取 Web3 实例
            w3 = Web3(Web3.HTTPProvider(chain_config['rpc_url']))
            
            # 查询余额
            if token_address == EVMUtils.NATIVE_TOKEN_ADDRESS or not token_address:
                # 原生代币余额
                balance = w3.eth.get_balance(wallet.address)
                decimals = chain_config['decimals']
                symbol = chain_config['symbol']
                name = chain_config['name']
            else:
                # ERC20 代币余额
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=ERC20_ABI
                )
                balance = contract.functions.balanceOf(wallet.address).call()
                decimals = contract.functions.decimals().call()
                symbol = contract.functions.symbol().call()
                name = contract.functions.name().call()
                
            # 格式化余额
            balance_formatted = balance / (10 ** decimals)
            
            return {
                'address': token_address or EVMUtils.NATIVE_TOKEN_ADDRESS,
                'name': name,
                'symbol': symbol,
                'decimals': decimals,
                'balance': str(balance),
                'balance_formatted': str(balance_formatted)
            }
            
        except Exception as e:
            logger.error(f"获取代币余额失败: {str(e)}")
            raise GetBalanceError(str(e))

    async def get_token_price(self, token_address: Optional[str] = None) -> Dict:
        """获取代币价格
        
        Args:
            token_address: 代币合约地址，如果为 None 则获取原生代币价格
            
        Returns:
            Dict: 价格信息
        """
        try:
            if token_address:
                return await self.token_info_service.get_token_price(token_address)
            else:
                # 获取原生代币价格
                native_token = self.chain_config['native_token']
                if not native_token or 'address' not in native_token:
                    return {
                        'price_usd': '0',
                        'price_change_24h': '+0.00%'
                    }
                return await self.token_info_service.get_token_price(native_token['address'])
                
        except Exception as e:
            logger.error(f"获取代币价格失败: {str(e)}")
            return {
                'price_usd': '0',
                'price_change_24h': '+0.00%'
            }

    async def get_all_token_balances(self, address: str, include_hidden: bool = False) -> Dict:
        """获取所有代币余额
        
        Args:
            address: 钱包地址
            include_hidden: 是否包含隐藏的代币，默认为 False
            
        Returns:
            Dict: 代币余额信息
        """
        try:
            tokens = []
            total_value = 0
            
            # 获取原生代币余额
            native_balance = await self.get_native_balance(address)
            if native_balance > 0:  # 只有当余额大于0时才添加
                native_token = self.chain_config['native_token']
                
                # 获取原生代币价格
                # 对于 ETH 和其他使用 ETH 作为原生代币的链，使用 ETH 主网的 WETH 价格
                if self.chain in ['ETH', 'BASE', 'ARBITRUM', 'OPTIMISM']:
                    eth_mainnet_weth = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'  # ETH 主网 WETH 地址
                    temp_service = EVMTokenInfoService('ETH')  # 临时创建 ETH 主网的服务
                    native_price_data = await temp_service.get_token_price(eth_mainnet_weth)
                else:
                    native_price_data = await self.token_info_service.get_token_price(native_token['address'])
                    
                native_price = float(native_price_data.get('price_usd', '0'))
                native_value = float(native_balance) * native_price
                total_value += native_value
                
                tokens.append({
                    'chain': self.chain,
                    'address': EVMUtils.NATIVE_TOKEN_ADDRESS,  # 使用统一的原生代币地址
                    'name': native_token['name'],
                    'symbol': native_token['symbol'],
                    'decimals': native_token['decimals'],
                    'logo': native_token.get('logo', ''),
                    'balance': str(native_balance),
                    'balance_formatted': str(native_balance),
                    'price_usd': native_price_data.get('price_usd', '0'),
                    'value_usd': str(native_value),
                    'price_change_24h': native_price_data.get('price_change_24h', '+0.00%'),
                    'is_native': True,
                    'is_visible': True  # 原生代币始终可见
                })
            
            # 获取 ERC20 代币余额
            url = MoralisConfig.EVM_WALLET_TOKENS_URL.format(Web3.to_checksum_address(address))
            params = {
                'chain': self.chain_id
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        logger.error(f"获取代币列表失败: {await response.text()}")
                        return {
                            'total_value_usd': str(total_value),
                            'tokens': tokens
                        }
                    
                    token_balances = await response.json()
                    
                    # 获取所有代币的显示状态
                    token_addresses = [token['token_address'] for token in token_balances]
                    db_tokens = await sync_to_async(list)(Token.objects.filter(
                        chain=self.chain,
                        address__in=token_addresses
                    ).values('address', 'is_visible'))
                    
                    # 创建地址到显示状态的映射
                    visibility_map = {t['address']: t['is_visible'] for t in db_tokens}
                    
                    # 处理 ERC20 代币
                    for token_data in token_balances:
                        try:
                            token_address = token_data['token_address']
                            
                            # 如果代币被隐藏且不包含隐藏代币，则跳过
                            if not include_hidden and not visibility_map.get(token_address, True):
                                continue
                                
                            decimals = int(token_data.get('decimals', 18))
                            
                            # 跳过 decimals 为 0 的代币（可能是 NFT）
                            if decimals == 0:
                                continue
                                
                            # 计算余额
                            balance = int(token_data.get('balance', '0'))
                            if balance <= 0:  # 跳过余额为0的代币
                                continue
                                
                            formatted_balance = str(EVMUtils.from_wei(balance, decimals))
                            
                            # 获取代币价格
                            price_data = await self.token_info_service.get_token_price(token_address)
                            price = float(price_data.get('price_usd', '0'))
                            value = float(formatted_balance) * price
                            total_value += value
                            
                            token_info = {
                                'chain': self.chain,
                                'address': token_address,
                                'name': token_data.get('name', ''),
                                'symbol': token_data.get('symbol', ''),
                                'decimals': decimals,
                                'logo': token_data.get('logo', ''),
                                'balance': str(balance),
                                'balance_formatted': formatted_balance,
                                'price_usd': price_data.get('price_usd', '0'),
                                'value_usd': str(value),
                                'price_change_24h': price_data.get('price_change_24h', '+0.00%'),
                                'is_native': False,
                                'is_visible': visibility_map.get(token_address, True)
                            }
                            
                            tokens.append(token_info)
                            
                        except Exception as e:
                            logger.error(f"处理代币数据失败: {str(e)}")
                            continue
                    
                    # 按价值排序
                    tokens.sort(key=lambda x: float(x['value_usd']), reverse=True)
                    
                    return {
                        'total_value_usd': str(total_value),
                        'tokens': tokens
                    }
                    
        except Exception as e:
            logger.error(f"获取代币列表失败: {str(e)}")
            return {
                'total_value_usd': '0',
                'tokens': []
            }