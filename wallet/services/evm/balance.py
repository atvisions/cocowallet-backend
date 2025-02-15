"""EVM 余额查询服务"""
import logging
from typing import Dict, List, Optional
from decimal import Decimal
import aiohttp
import json
from web3 import Web3
from django.core.cache import cache

from ...api_config import MoralisConfig
from .utils import EVMUtils
from .token_info import EVMTokenInfoService

logger = logging.getLogger(__name__)

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

    async def get_token_balance(self, address: str, token_address: str) -> Decimal:
        """获取代币余额
        
        Args:
            address: 钱包地址
            token_address: 代币合约地址
            
        Returns:
            Decimal: 余额
        """
        try:
            # 使用 Moralis API 获取代币余额
            url = MoralisConfig.EVM_WALLET_TOKENS_URL.format(Web3.to_checksum_address(address))
            params = {
                'chain': self.chain_id,
                'token_addresses': [Web3.to_checksum_address(token_address)]
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result:
                            for token in result:
                                if token['token_address'].lower() == token_address.lower():
                                    balance = int(token.get('balance', '0'))
                                    decimals = int(token.get('decimals', 18))
                                    return EVMUtils.from_wei(balance, decimals)
                    else:
                        logger.error(f"获取代币余额失败: {await response.text()}")
                        
            return Decimal('0')
            
        except Exception as e:
            logger.error(f"获取代币余额失败: {str(e)}")
            return Decimal('0')

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

    async def get_all_token_balances(self, address: str) -> Dict:
        """获取所有代币余额"""
        try:
            tokens = []
            total_value = 0
            
            # 获取原生代币余额
            native_balance = await self.get_native_balance(address)
            if native_balance > 0:  # 只有当余额大于0时才添加
                native_token = self.chain_config['native_token']
                
                # 获取原生代币价格
                native_price_data = await self.token_info_service.get_token_price(native_token['address'])
                native_price = float(native_price_data.get('price_usd', '0'))
                native_value = float(native_balance) * native_price
                total_value += native_value
                
                tokens.append({
                    'chain': self.chain,
                    'address': native_token['address'],
                    'name': native_token['name'],
                    'symbol': native_token['symbol'],
                    'decimals': native_token['decimals'],
                    'logo': native_token.get('logo', ''),
                    'balance': str(native_balance),
                    'balance_formatted': str(native_balance),
                    'price_usd': native_price_data.get('price_usd', '0'),
                    'value_usd': str(native_value),
                    'price_change_24h': native_price_data.get('price_change_24h', '+0.00%'),
                    'is_native': True
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
                    
                    # 处理 ERC20 代币
                    for token_data in token_balances:
                        token_address = token_data['token_address']
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
                        
                        tokens.append({
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
                            'is_native': False
                        })
                    
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