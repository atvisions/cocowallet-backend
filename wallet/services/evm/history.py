"""EVM 历史记录服务"""
import logging
from typing import Dict, List, Any, Optional
from decimal import Decimal
import aiohttp
import asyncio
from web3 import Web3
from django.utils import timezone
from asgiref.sync import sync_to_async
from datetime import datetime
from hexbytes import HexBytes

from ...models import Transaction, Token, Wallet
from ...api_config import RPCConfig, MoralisConfig
from .utils import EVMUtils

logger = logging.getLogger(__name__)

class EVMHistoryService:
    """EVM 历史记录服务实现类"""

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

    async def get_native_transactions(
        self,
        address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """获取原生代币交易历史"""
        try:
            url = f"{MoralisConfig.BASE_URL}/{address}"
            params = {
                'chain': self.chain.lower(),
                'limit': str(limit),
                'offset': str(offset)
            }
            
            if start_time:
                params['from_date'] = start_time.isoformat()
            if end_time:
                params['to_date'] = end_time.isoformat()
                
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"获取交易历史失败: {await response.text()}")
                    
                    result = await response.json()
                    if not result:
                        return []
                    
                    transactions = []
                    for tx in result:
                        if tx.get('value') == '0':  # 跳过零值交易
                            continue
                            
                        transactions.append({
                            'tx_hash': tx.get('hash'),
                            'block_number': tx.get('block_number'),
                            'timestamp': tx.get('block_timestamp'),
                            'from_address': tx.get('from_address'),
                            'to_address': tx.get('to_address'),
                            'value': EVMUtils.from_wei(int(tx.get('value', '0'), 16)),
                            'gas_price': EVMUtils.from_wei(int(tx.get('gas_price', '0'), 16)),
                            'gas_used': int(tx.get('receipt_gas_used', '0'), 16),
                            'status': 'SUCCESS' if tx.get('receipt_status') == '1' else 'FAILED',
                            'is_native': True
                        })
                    
                    return transactions
            
        except Exception as e:
            logger.error(f"获取原生代币交易历史失败: {str(e)}")
            return []

    async def get_token_transactions(
        self,
        address: str,
        token_address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """获取代币交易历史"""
        try:
            url = f"{MoralisConfig.BASE_URL}/erc20/transfers"
            params = {
                'chain': self.chain.lower(),
                'address': address,
                'contract_addresses': [token_address],
                'limit': str(limit),
                'offset': str(offset)
            }
            
            if start_time:
                params['from_date'] = start_time.isoformat()
            if end_time:
                params['to_date'] = end_time.isoformat()
                
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"获取代币交易历史失败: {await response.text()}")
                    
                    result = await response.json()
                    if not result:
                        return []
                    
                    # 获取代币信息
                    token = await sync_to_async(Token.objects.filter(
                        chain=self.chain,
                        address=token_address
                    ).first)()
                    
                    transactions = []
                    for tx in result:
                        value = Decimal(tx.get('value', '0'))
                        if value == 0:  # 跳过零值交易
                            continue
                            
                        # 如果有代币信息，使用代币精度
                        if token:
                            value = value / Decimal(str(10 ** token.decimals))
                            
                        transactions.append({
                            'tx_hash': tx.get('transaction_hash'),
                            'block_number': tx.get('block_number'),
                            'timestamp': tx.get('block_timestamp'),
                            'from_address': tx.get('from_address'),
                            'to_address': tx.get('to_address'),
                            'value': str(value),
                            'token_address': token_address,
                            'token_name': token.name if token else 'Unknown Token',
                            'token_symbol': token.symbol if token else 'Unknown',
                            'token_decimals': token.decimals if token else 18,
                            'gas_price': EVMUtils.from_wei(int(tx.get('gas_price', '0'), 16)),
                            'gas_used': int(tx.get('receipt_gas_used', '0'), 16),
                            'status': 'SUCCESS',  # ERC20 transfer 通常都是成功的
                            'is_native': False
                        })
                    
                    return transactions
            
        except Exception as e:
            logger.error(f"获取代币交易历史失败: {str(e)}")
            return []

    async def get_transaction_details(self, tx_hash: str) -> Dict:
        """获取交易详情"""
        try:
            # 获取交易信息
            tx = await self.web3.eth.get_transaction(tx_hash)
            if not tx:
                return {}
                
            # 获取交易收据
            receipt = await self.web3.eth.get_transaction_receipt(tx_hash)
            if not receipt:
                return {}
                
            # 获取区块信息
            block = await self.web3.eth.get_block(tx['blockNumber'])
            if not block:
                return {}
                
            # 检查是否是代币转账
            is_token_transfer = False
            token_address = None
            token_info = None
            
            if tx['input'].startswith('0xa9059cbb'):  # transfer method signature
                is_token_transfer = True
                token_address = tx['to']
                
                # 获取代币信息
                token = await sync_to_async(Token.objects.filter(
                    chain=self.chain,
                    address=token_address
                ).first)()
                
                if token:
                    token_info = {
                        'name': token.name,
                        'symbol': token.symbol,
                        'decimals': token.decimals
                    }
            
            return {
                'tx_hash': tx_hash,
                'block_number': tx['blockNumber'],
                'timestamp': datetime.fromtimestamp(block['timestamp']),
                'from_address': tx['from'],
                'to_address': tx['to'],
                'value': EVMUtils.from_wei(tx['value']),
                'gas_price': EVMUtils.from_wei(tx['gasPrice']),
                'gas_used': receipt['gasUsed'],
                'status': 'SUCCESS' if receipt['status'] == 1 else 'FAILED',
                'is_token_transfer': is_token_transfer,
                'token_address': token_address,
                'token_info': token_info,
                'raw_data': {
                    'transaction': dict(tx),
                    'receipt': dict(receipt),
                    'block': dict(block)
                }
            }
            
        except Exception as e:
            logger.error(f"获取交易详情失败: {str(e)}")
            return {} 