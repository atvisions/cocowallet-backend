"""EVM 代币兑换服务"""
import logging
from typing import Dict, List, Any, Optional
from decimal import Decimal
import aiohttp
from web3 import Web3
from django.utils import timezone
from asgiref.sync import sync_to_async

from ...models import Token, Wallet
from ...api_config import RPCConfig, MoralisConfig
from .utils import EVMUtils

logger = logging.getLogger(__name__)

class EVMSwapService:
    """EVM 代币兑换服务实现类"""

    def __init__(self, chain: str):
        """初始化
        
        Args:
            chain: 链标识(ETH/BSC/POLYGON/AVAX/BASE)
        """
        self.chain = chain
        self.chain_config = EVMUtils.get_chain_config(chain)
        self.web3 = EVMUtils.get_web3(chain)
        
        # Moralis API 配置
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "X-API-Key": MoralisConfig.API_KEY
        }
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def get_quote(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        slippage: float = 1.0
    ) -> Dict:
        """获取兑换报价
        
        Args:
            from_token: 源代币地址
            to_token: 目标代币地址
            amount: 兑换数量(已包含精度)
            slippage: 滑点百分比(默认1%)
            
        Returns:
            报价信息字典
        """
        try:
            url = f"{MoralisConfig.BASE_URL}/dex/quote"
            params = {
                'chain': self.chain.lower(),
                'fromTokenAddress': from_token,
                'toTokenAddress': to_token,
                'amount': amount,
                'slippage': slippage
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"获取兑换报价失败: {await response.text()}")
                    
                    result = await response.json()
                    return {
                        'from_token': result.get('fromToken'),
                        'to_token': result.get('toToken'),
                        'from_amount': result.get('fromAmount'),
                        'to_amount': result.get('toAmount'),
                        'estimated_gas': result.get('estimatedGas'),
                        'price_impact': result.get('priceImpact'),
                        'minimum_received': result.get('minimumReceived'),
                        'protocols': result.get('protocols', [])
                    }
                    
        except Exception as e:
            logger.error(f"获取兑换报价失败: {str(e)}")
            return {}

    async def build_swap_transaction(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        from_address: str,
        slippage: float = 1.0
    ) -> Dict:
        """构建兑换交易
        
        Args:
            from_token: 源代币地址
            to_token: 目标代币地址
            amount: 兑换数量(已包含精度)
            from_address: 发送方地址
            slippage: 滑点百分比(默认1%)
            
        Returns:
            交易数据字典
        """
        try:
            url = f"{MoralisConfig.BASE_URL}/dex/swap"
            params = {
                'chain': self.chain.lower(),
                'fromTokenAddress': from_token,
                'toTokenAddress': to_token,
                'amount': amount,
                'fromAddress': from_address,
                'slippage': slippage
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"构建兑换交易失败: {await response.text()}")
                    
                    result = await response.json()
                    tx = result.get('tx', {})
                    return {
                        'from': tx.get('from'),
                        'to': tx.get('to'),
                        'data': tx.get('data'),
                        'value': tx.get('value', '0'),
                        'gas_price': tx.get('gasPrice'),
                        'gas': tx.get('gas'),
                        'estimated_gas': result.get('estimatedGas'),
                        'price_impact': result.get('priceImpact'),
                        'minimum_received': result.get('minimumReceived'),
                        'protocols': result.get('protocols', [])
                    }
                    
        except Exception as e:
            logger.error(f"构建兑换交易失败: {str(e)}")
            return {}

    async def get_supported_tokens(self) -> List[Dict]:
        """获取支持的代币列表"""
        try:
            url = f"{MoralisConfig.BASE_URL}/dex/tokens"
            params = {'chain': self.chain.lower()}
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"获取支持的代币列表失败: {await response.text()}")
                    
                    result = await response.json()
                    return result.get('tokens', [])
                    
        except Exception as e:
            logger.error(f"获取支持的代币列表失败: {str(e)}")
            return []

    async def get_token_allowance(
        self,
        token_address: str,
        wallet_address: str,
        spender: str
    ) -> str:
        """获取代币授权额度"""
        try:
            url = f"{MoralisConfig.BASE_URL}/erc20/{token_address}/allowance"
            params = {
                'chain': self.chain.lower(),
                'owner_address': wallet_address,
                'spender_address': spender
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"获取代币授权额度失败: {await response.text()}")
                    
                    result = await response.json()
                    return result.get('allowance', '0')
                    
        except Exception as e:
            logger.error(f"获取代币授权额度失败: {str(e)}")
            return '0'

    async def build_approve_transaction(
        self,
        token_address: str,
        spender: str,
        amount: str
    ) -> Dict:
        """构建授权交易
        
        Args:
            token_address: 代币地址
            spender: 授权地址
            amount: 授权数量
            
        Returns:
            交易数据字典
        """
        try:
            # 获取 ERC20 合约 ABI
            abi = [{
                "constant": False,
                "inputs": [
                    {"name": "_spender", "type": "address"},
                    {"name": "_value", "type": "uint256"}
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function"
            }]
            
            # 创建合约实例
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=abi
            )
            
            # 构建授权数据
            data = contract.encodeABI(
                fn_name="approve",
                args=[Web3.to_checksum_address(spender), int(amount)]
            )
            
            # 估算 gas
            gas_limit = EVMUtils.estimate_gas_limit(
                self.chain,
                token_address,
                0,
                data
            )
            
            return {
                'to': token_address,
                'data': data,
                'value': '0',
                'gas': gas_limit,
                'gas_price': await self.web3.eth.gas_price
            }
                    
        except Exception as e:
            logger.error(f"构建授权交易失败: {str(e)}")
            return {} 