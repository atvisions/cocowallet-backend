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
            # 分别获取作为发送方和接收方的交易
            sent_params = {
                'chain': self.chain.lower(),
                'from_address': address,
                'contract_addresses': [token_address],
                'limit': str(limit),
                'offset': str(offset)
            }
            
            received_params = {
                'chain': self.chain.lower(),
                'to_address': address,
                'contract_addresses': [token_address],
                'limit': str(limit),
                'offset': str(offset)
            }
            
            if start_time:
                sent_params['from_date'] = start_time.isoformat()
                received_params['from_date'] = start_time.isoformat()
            if end_time:
                sent_params['to_date'] = end_time.isoformat()
                received_params['to_date'] = end_time.isoformat()
                
            url = f"{MoralisConfig.BASE_URL}/erc20/transfers"
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # 获取发送的交易
                async with session.get(url, headers=self.headers, params=sent_params) as sent_response:
                    if sent_response.status != 200:
                        logger.error(f"获取发送交易失败: {await sent_response.text()}")
                        sent_result = []
                    else:
                        sent_result = await sent_response.json()
                
                # 获取接收的交易
                async with session.get(url, headers=self.headers, params=received_params) as received_response:
                    if received_response.status != 200:
                        logger.error(f"获取接收交易失败: {await received_response.text()}")
                        received_result = []
                    else:
                        received_result = await received_response.json()
                    
                # 合并结果
                all_results = sent_result + received_result
                
                # 去重（根据交易哈希）
                seen_tx_hashes = set()
                unique_results = []
                for tx in all_results:
                    tx_hash = tx.get('transaction_hash')
                    if tx_hash and tx_hash not in seen_tx_hashes:
                        seen_tx_hashes.add(tx_hash)
                        unique_results.append(tx)
                
                # 获取代币信息
                token = await sync_to_async(Token.objects.filter(
                    chain=self.chain,
                    address=token_address
                ).first)()
                
                # 如果数据库中没有代币信息，尝试从链上获取
                if not token and token_address:
                    try:
                        token_contract = self.web3.eth.contract(
                            address=Web3.to_checksum_address(token_address),
                            abi=ERC20_ABI
                        )
                        name = await token_contract.functions.name().call()
                        symbol = await token_contract.functions.symbol().call()
                        decimals = await token_contract.functions.decimals().call()
                        
                        token_info = {
                            'logo': '',
                            'name': name,
                            'symbol': symbol,
                            'address': token_address,
                            'decimals': decimals,
                            'verified': False,
                            'thumbnail': ''
                        }
                    except Exception as e:
                        logger.error(f"获取代币信息失败: {str(e)}")
                        token_info = {
                            'logo': '',
                            'name': 'Unknown Token',
                            'symbol': 'Unknown',
                            'address': token_address,
                            'decimals': 18,
                            'verified': False,
                            'thumbnail': ''
                        }
                else:
                    token_info = {
                        'logo': token.logo if token else '',
                        'name': token.name if token else 'Unknown Token',
                        'symbol': token.symbol if token else 'Unknown',
                        'address': token_address,
                        'decimals': token.decimals if token else 18,
                        'verified': token.verified if token else False,
                        'thumbnail': token.thumbnail if token else ''
                    }
                
                transactions = []
                for tx in unique_results:
                    try:
                        # 获取原始金额
                        raw_value = tx.get('value', '0')
                        if raw_value == '0':  # 跳过零值交易
                            continue
                            
                        # 将原始金额转换为十进制数
                        value = Decimal(raw_value)
                        # 使用代币精度格式化金额
                        formatted_value = str(value / Decimal(str(10 ** token_info['decimals'])))
                        
                        transactions.append({
                            'tx_hash': tx.get('transaction_hash'),
                            'block_number': tx.get('block_number'),
                            'timestamp': tx.get('block_timestamp'),
                            'from_address': tx.get('from_address'),
                            'to_address': tx.get('to_address'),
                            'value': formatted_value,
                            'token_address': token_address,  # 确保设置正确的代币地址
                            'token_info': token_info,  # 使用完整的代币信息
                            'gas_price': EVMUtils.from_wei(int(tx.get('gas_price', '0'), 16)),
                            'gas_used': int(tx.get('receipt_gas_used', '0'), 16),
                            'status': 'SUCCESS',
                            'is_native': False
                        })
                    except Exception as e:
                        logger.error(f"处理代币交易记录失败: {str(e)}, 交易数据: {tx}")
                        continue
                
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