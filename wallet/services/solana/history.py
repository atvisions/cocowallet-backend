"""Solana 交易历史服务"""
import logging
from typing import Dict, List, Optional
from decimal import Decimal
import aiohttp
import asyncio
from datetime import datetime
from asgiref.sync import sync_to_async
import json
from django.utils import timezone

from ...models import Transaction, Token, Wallet
from ...services.solana_config import MoralisConfig

logger = logging.getLogger(__name__)

class SolanaHistoryService:
    """Solana 交易历史服务实现类"""

    def __init__(self):
        self.headers = {
            "accept": "application/json",
            "X-API-Key": MoralisConfig.API_KEY
        }
        self.timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_connect=5, sock_read=10)

    async def get_native_transactions(
        self,
        address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """获取 SOL 原生代币交易历史"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{address}/transfers"
                params = {
                    "limit": str(limit),
                    "offset": str(offset)
                }
                
                if start_time:
                    params["from_date"] = start_time.isoformat()
                if end_time:
                    params["to_date"] = end_time.isoformat()

                response = await self._fetch_with_retry(session, url, params=params)
                if not response:
                    return []

                transactions = []
                for tx in response:
                    if tx.get('type') == 'sol':  # 只处理 SOL 转账
                        transactions.append({
                            'tx_hash': tx.get('signature'),
                            'from_address': tx.get('from_address'),
                            'to_address': tx.get('to_address'),
                            'amount': tx.get('amount', '0'),
                            'timestamp': tx.get('block_timestamp'),
                            'fee': tx.get('fee', '0'),
                            'status': tx.get('status', 'success'),
                            'is_native': True
                        })

                return transactions

            except Exception as e:
                logger.error(f"获取SOL交易历史时出错: {str(e)}")
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
        """获取 SPL 代币交易历史"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{address}/transfers"
                params = {
                    "limit": str(limit),
                    "offset": str(offset)
                }
                
                if start_time:
                    params["from_date"] = start_time.isoformat()
                if end_time:
                    params["to_date"] = end_time.isoformat()

                response = await self._fetch_with_retry(session, url, params=params)
                if not response:
                    return []

                # 获取代币信息
                token_info = await sync_to_async(Token.objects.filter(
                    chain='SOL',
                    address=token_address
                ).first)()

                transactions = []
                for tx in response:
                    if (tx.get('type') == 'spl' and 
                        tx.get('token_address') == token_address):
                        
                        transactions.append({
                            'tx_hash': tx.get('signature'),
                            'from_address': tx.get('from_address'),
                            'to_address': tx.get('to_address'),
                            'amount': tx.get('amount', '0'),
                            'timestamp': tx.get('block_timestamp'),
                            'fee': tx.get('fee', '0'),
                            'status': tx.get('status', 'success'),
                            'token_address': token_address,
                            'token_name': token_info.name if token_info else 'Unknown Token',
                            'token_symbol': token_info.symbol if token_info else 'Unknown',
                            'token_decimals': token_info.decimals if token_info else 0,
                            'is_native': False
                        })

                return transactions

            except Exception as e:
                logger.error(f"获取SPL代币交易历史时出错: {str(e)}")
                return []

    async def get_transaction_details(self, tx_hash: str) -> Dict:
        """获取交易详情"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                url = f"{MoralisConfig.SOLANA_URL}/transaction/mainnet/{tx_hash}"
                response = await self._fetch_with_retry(session, url)
                
                if not response:
                    return {}

                # 检查是否是 SPL 代币交易
                is_spl = response.get('type') == 'spl'
                token_address = response.get('token_address') if is_spl else None

                # 如果是 SPL 代币交易，获取代币信息
                token_info = None
                if token_address:
                    token_info = await sync_to_async(Token.objects.filter(
                        chain='SOL',
                        address=token_address
                    ).first)()

                return {
                    'tx_hash': response.get('signature'),
                    'block_number': response.get('block_number'),
                    'timestamp': response.get('block_timestamp'),
                    'from_address': response.get('from_address'),
                    'to_address': response.get('to_address'),
                    'amount': response.get('amount', '0'),
                    'fee': response.get('fee', '0'),
                    'status': response.get('status', 'success'),
                    'is_native': not is_spl,
                    'token_address': token_address,
                    'token_name': token_info.name if token_info else None,
                    'token_symbol': token_info.symbol if token_info else None,
                    'token_decimals': token_info.decimals if token_info else None,
                    'raw_data': response
                }

            except Exception as e:
                logger.error(f"获取交易详情时出错: {str(e)}")
                return {}

    async def _fetch_with_retry(self, session, url, method="get", **kwargs):
        """带重试的HTTP请求函数"""
        kwargs['headers'] = self.headers
        for attempt in range(3):
            try:
                async with getattr(session, method)(url, **kwargs) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:  # Rate limit
                        retry_after = int(response.headers.get('Retry-After', 2))
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.error(f"请求失败: {url}, 状态码: {response.status}")
                        return None
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                logger.error(f"请求失败: {url}, 错误: {str(e)}")
                return None
        return None