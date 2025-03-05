"""Solana 转账服务"""
import logging
from decimal import Decimal
from typing import Dict, Any, Optional, cast, Union, Callable
import asyncio
import aiohttp
from django.utils import timezone
import base58
import time

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solana.transaction import Transaction as SolanaTransaction
from solana.keypair import Keypair
from solana.publickey import PublicKey
from solana.system_program import TransferParams, transfer
from spl.token.instructions import create_associated_token_account, transfer_checked, TransferCheckedParams
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
from solana.rpc.types import TxOpts
from solana.blockhash import Blockhash
from spl.token.client import Token

from ...models import Wallet, Transaction as DBTransaction, Token
from ...exceptions import InsufficientBalanceError, InvalidAddressError, TransferError
from ...services.solana_config import RPCConfig, MoralisConfig
import json

logger = logging.getLogger(__name__)

class SolanaTransferService:
    """Solana 转账服务实现类"""
    def __init__(self):
        """初始化 Solana 转账服务"""
        # 初始化 RPC 配置
        self.primary_rpc_url = RPCConfig.SOLANA_MAINNET_RPC_URL
        self.backup_rpc_urls = [
            "https://api.mainnet-beta.solana.com",
            "https://solana-api.projectserum.com"
        ]
        self.current_rpc_url = self.primary_rpc_url
        self.rpc_url = self.current_rpc_url
        
        # 初始化 RPC 客户端
        self.client = AsyncClient(
            endpoint=self.current_rpc_url,
            timeout=30,
            commitment=Commitment("confirmed")
        )
        
        # 重试配置
        self.max_retries = 3
        self.retry_delay = 1
        self.max_delay = 10
        
        # 设置请求头
        self.request_headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        # 如果是 Alchemy API，添加认证头
        if "alchemy" in self.current_rpc_url.lower():
            api_key = self.current_rpc_url.split("/")[-1] if "/" in self.current_rpc_url else ""
            if api_key:
                self.request_headers.update({
                    'Authorization': f'Bearer {api_key}',
                    'Alchemy-API-Key': api_key,
                    'Alchemy-Web3-Version': '2.0.0'
                })
        
        # RPC 节点健康状态
        self.rpc_health = {
            'last_check': 0,
            'check_interval': 300,  # 5分钟检查一次
            'is_healthy': True
        }
        
        # 设置 aiohttp 会话配置
        self.timeout = aiohttp.ClientTimeout(
            total=30,
            connect=5,
            sock_connect=5,
            sock_read=10
        )
        
        # 创建 aiohttp 会话
        self._session = None
        self._session_lock = asyncio.Lock()
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                connector = aiohttp.TCPConnector(ssl=False)
                self._session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=self.timeout,
                    headers=self.request_headers
                )
            return self._session
        
    async def _fetch_with_retry(self, method: str, *args, **kwargs) -> Any:
        """带重试的 RPC 请求"""
        max_retries = kwargs.pop('max_retries', self.max_retries)
        timeout = kwargs.pop('timeout', self.timeout.total)
        
        # 构建请求体
        params = kwargs.get('params', [])
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),  # 使用时间戳作为唯一ID
            "method": method,
            "params": params
        }

        # 添加备用RPC节点
        rpc_urls = [self.primary_rpc_url] + self.backup_rpc_urls
        
        for attempt in range(max_retries):
            for rpc_url in rpc_urls:
                try:
                    session = await self._get_session()
                    async with session.post(
                        rpc_url,
                        json=payload,
                        timeout=timeout
                    ) as response:
                        if response.status == 429:  # 速率限制
                            wait_time = int(response.headers.get('Retry-After', 2 ** attempt))
                            logger.warning(f"RPC节点 {rpc_url} 触发速率限制,等待 {wait_time} 秒")
                            await asyncio.sleep(wait_time)
                            continue
                            
                        if response.status == 200:
                            result = await response.json()
                            if 'error' in result:
                                error = result['error']
                                error_msg = error.get('message', str(error))
                                
                                if 'BlockhashNotFound' in error_msg:
                                    logger.warning(f"区块哈希已过期,重试请求")
                                    break  # 尝试下一个重试
                                    
                                raise TransferError(f"RPC请求失败: {error_msg}")
                                
                            return result.get('result')
                            
                        logger.error(f"HTTP {response.status}: {await response.text()}")
                        
                except asyncio.TimeoutError:
                    logger.warning(f"RPC节点 {rpc_url} 超时")
                    continue
                    
                except Exception as e:
                    logger.error(f"请求RPC节点 {rpc_url} 失败: {str(e)}")
                    continue
                    
            # 所有节点都失败,等待后重试
            wait_time = min(2 ** attempt, self.max_delay)
            logger.warning(f"所有RPC节点请求失败,等待 {wait_time} 秒后重试")
            await asyncio.sleep(wait_time)
        
        raise TransferError("多次重试后仍无法完成RPC请求")

    async def _get_recent_blockhash(self) -> str:
        """获取最新区块哈希"""
        try:
            logger.debug("开始获取最新区块哈希")
            
            response = await self._fetch_with_retry(
                'getLatestBlockhash',
                params=[{"commitment": "confirmed"}]
            )
            
            if isinstance(response, dict):
                value = response.get('value', {})
                if isinstance(value, dict):
                    blockhash = value.get('blockhash')
                    if blockhash:
                        logger.info(f"成功获取区块哈希: {blockhash}")
                        return blockhash
            
            raise Exception(f"无效的区块哈希响应格式: {response}")
            
        except Exception as e:
            error_msg = f"获取区块哈希失败: {str(e)}"
            if hasattr(e, '__class__'):
                error_msg += f" ({e.__class__.__name__})"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_health_check_url(self) -> str:
        """获取健康检查URL"""
        return self.rpc_url
        
    async def check_health(self) -> Dict[str, Any]:
        """检查服务健康状态
        
        Returns:
            Dict[str, Any]: 包含服务健康状态信息的字典
        """
        try:
            # 使用父类的健康检查方法
            health_status = await super().check_health() # type: ignore
            
            # 检查 Solana RPC 节点状态
            try:
                response = await self._fetch_with_retry(
                    'get_latest_blockhash',
                    commitment=Commitment("confirmed")
                )
                
                if response and 'result' in response:
                    health_status['solana_rpc'] = {
                        'status': 'ok',
                        'message': '节点连接正常',
                        'timestamp': timezone.now().isoformat()
                    }
                else:
                    health_status['solana_rpc'] = {
                        'status': 'error',
                        'message': '无法获取区块哈希',
                        'timestamp': timezone.now().isoformat()
                    }
            except Exception as e:
                health_status['solana_rpc'] = {
                    'status': 'error',
                    'message': f'RPC 节点异常: {str(e)}',
                    'error_type': e.__class__.__name__,
                    'timestamp': timezone.now().isoformat()
                }
            
            return health_status
            
        except Exception as e:
            error_status = {
                'status': 'error',
                'message': f'服务异常: {str(e)}',
                'error_type': e.__class__.__name__,
                'timestamp': timezone.now().isoformat(),
                'solana_rpc': {
                    'status': 'error',
                    'message': str(e),
                    'error_type': e.__class__.__name__,
                    'timestamp': timezone.now().isoformat()
                }
            }
            logger.error(f"健康检查失败: {error_status}")
            return error_status

    async def _get_wallet_keypair(self, wallet: Wallet) -> Keypair:
        """从钱包获取密钥对"""
        try:
            # 解密私钥
            private_key = wallet.decrypt_private_key()
            if isinstance(private_key, str):
                # 如果是Base58格式的字符串，先解码
                private_key = base58.b58decode(private_key)
            # 创建密钥对
            return Keypair.from_seed(private_key[:32])  # 只使用前32字节作为种子
        except Exception as e:
            logger.error(f"获取钱包密钥对失败: {str(e)}")
            raise TransferError("无法获取钱包密钥对")

    async def _get_token_decimals(self, token_address: str) -> int:
        """获取代币精度"""
        try:
            # 从数据库获取代币信息
            token = await Token.objects.aget(chain='SOL', address=token_address)
            if token and token.decimals is not None:
                return token.decimals
                
            # 如果数据库中没有，从链上获取
            try:
                response = await self.client.get_token_supply(token_address)
                if response and 'result' in response and 'decimals' in response['result']:
                    decimals = int(response['result']['decimals'])
                    # 更新数据库
                    await Token.objects.aupdate_or_create(
                        chain='SOL',
                        address=token_address,
                        defaults={'decimals': decimals}
                    )
                    return decimals
            except Exception as e:
                logger.error(f"从链上获取代币精度失败: {str(e)}")
                
            raise TransferError("无法获取代币精度")
            
        except Token.DoesNotExist:
            logger.error(f"代币 {token_address} 不存在")
            raise TransferError("代币不存在")
        except Exception as e:
            logger.error(f"获取代币精度失败: {str(e)}")
            raise TransferError(f"无法获取代币精度: {str(e)}")

    async def _get_associated_token_address(self, wallet_address: str, token_address: str) -> str:
        """获取关联代币账户地址"""
        try:
            wallet_pubkey = PublicKey(wallet_address)
            token_pubkey = PublicKey(token_address)
            
            # 使用 find_program_address 查找关联代币账户地址
            seeds = [
                bytes(wallet_pubkey),
                bytes(TOKEN_PROGRAM_ID),
                bytes(token_pubkey)
            ]
            ata, _ = PublicKey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
            return str(ata)
        except Exception as e:
            logger.error(f"获取关联代币账户失败: {str(e)}")
            raise TransferError("无法获取关联代币账户")

    async def _check_token_account_exists(self, account_address: str) -> bool:
        """检查代币账户是否存在"""
        try:
            logger.debug(f"检查账户 {account_address} 是否存在")
            response = await self._fetch_with_retry(
                'getAccountInfo',
                params=[
                    account_address,
                    {
                        "encoding": "base64",
                        "commitment": "confirmed"
                    }
                ]
            )
            
            if response and isinstance(response, dict):
                value = response.get('value')
                exists = value is not None and len(value) > 0
                logger.debug(f"账户 {account_address} 存在: {exists}")
                return exists
            return False
        except Exception as e:
            error_msg = f"检查代币账户失败: {str(e)}"
            if hasattr(e, '__class__'):
                error_msg += f" ({e.__class__.__name__})"
            logger.error(error_msg)
            return False

    async def _create_token_account(self, wallet: Wallet, token_address: str, private_key: str) -> str:
        """创建代币账户"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"第 {attempt + 1} 次尝试创建代币账户")
                logger.info(f"钱包地址: {wallet.address}, 代币地址: {token_address}")
                
                # 使用提供的私钥创建密钥对
                keypair = Keypair.from_seed(base58.b58decode(private_key)[:32])
                wallet_pubkey = keypair.public_key
                token_pubkey = PublicKey(token_address)
                
                # 获取关联代币账户地址
                ata = await self._get_associated_token_address(wallet.address, token_address)
                logger.info(f"关联代币账户地址: {ata}")
                
                # 创建交易
                transaction = SolanaTransaction()
                create_ata_ix = create_associated_token_account(
                    payer=wallet_pubkey,
                    owner=wallet_pubkey,
                    mint=token_pubkey
                )
                logger.info(f"创建ATA指令: {create_ata_ix}")
                transaction.add(create_ata_ix)
                
                # 获取最新区块哈希并设置
                recent_blockhash = await self._get_recent_blockhash()
                logger.info(f"获取到的区块哈希: {recent_blockhash}")
                transaction.recent_blockhash = cast(Blockhash, recent_blockhash)
                
                # 签名并发送交易
                transaction.sign(keypair)
                logger.info("交易已签名，准备发送")
                
                # 使用 send_raw_transaction 而不是 send_transaction
                serialized_transaction = transaction.serialize()
                result = await self.client.send_raw_transaction(
                    serialized_transaction,
                    opts=TxOpts(skip_preflight=True)  # 使用 TxOpts 类
                )
                logger.info(f"发送交易结果: {result}")
                
                # 处理响应结果
                if isinstance(result, dict):
                    if 'error' in result:
                        error_data = result.get('error', {})
                        if isinstance(error_data, dict):
                            error_msg = error_data.get('message', str(error_data))
                        else:
                            error_msg = str(error_data)
                        if 'BlockhashNotFound' in str(error_msg):
                            logger.warning(f"区块哈希已过期，将在下一次重试中重新获取")
                            await asyncio.sleep(1)
                            continue
                        raise TransferError(f"创建代币账户失败: {error_msg}")
                    
                    transaction_hash = result.get('result')
                    if not transaction_hash:
                        raise TransferError("无法获取交易哈希")
                    
                    # 等待交易确认
                    await asyncio.sleep(2)
                    
                    # 验证账户是否创建成功
                    for check_attempt in range(3):
                        if await self._check_token_account_exists(ata):
                            logger.info(f"代币账户创建成功: {ata}")
                            return ata
                        logger.warning(f"第 {check_attempt + 1} 次检查账户创建状态")
                        await asyncio.sleep(2)
                    
                    if attempt < max_retries - 1:
                        logger.warning("账户创建验证失败，将重试")
                        continue
                    else:
                        raise TransferError("代币账户创建后验证失败")
                
            except Exception as e:
                logger.error(f"第 {attempt + 1} 次创建代币账户失败: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                raise TransferError(f"创建代币账户失败: {str(e)}")
                
        raise TransferError("多次尝试后仍无法创建代币账户")

    async def _get_transaction_details(self, tx_hash: str) -> Dict[str, Any]:
        """获取详细的交易信息"""
        try:
            response = await self._fetch_with_retry(
                'getTransaction',
                params=[
                    tx_hash,
                    {"commitment": "confirmed", "encoding": "json"}
                ],
                max_retries=3
            )
            
            if response and isinstance(response, dict):
                meta = response.get('meta', {})
                transaction = response.get('transaction', {})
                message = transaction.get('message', {})
                
                # 获取代币转账信息
                token_transfers = []
                if meta and 'postTokenBalances' in meta and 'preTokenBalances' in meta:
                    pre_balances = {
                        b['mint']: b['uiTokenAmount'] 
                        for b in meta['preTokenBalances']
                    }
                    post_balances = {
                        b['mint']: b['uiTokenAmount']
                        for b in meta['postTokenBalances']
                    }
                    
                    for mint in set(pre_balances.keys()) | set(post_balances.keys()):
                        pre = pre_balances.get(mint, {'uiAmount': 0})
                        post = post_balances.get(mint, {'uiAmount': 0})
                        token_transfers.append({
                            'mint': mint,
                            'pre_amount': str(pre['uiAmount']),
                            'post_amount': str(post['uiAmount']),
                            'decimals': pre.get('decimals', post.get('decimals')),
                        })
                
                return {
                    'status': 'success' if not meta.get('err') else 'failed',
                    'error': str(meta.get('err')) if meta.get('err') else None,
                    'fee': meta.get('fee', 0),
                    'block_time': response.get('blockTime'),
                    'block_slot': response.get('slot'),
                    'block_hash': message.get('recentBlockhash'),
                    'recent_blockhash': message.get('recentBlockhash'),
                    'compute_units_consumed': meta.get('computeUnitsConsumed'),
                    'logs': meta.get('logMessages', []),
                    'token_transfers': token_transfers,
                    'pre_balances': meta.get('preBalances', []),
                    'post_balances': meta.get('postBalances', []),
                    'confirmations': response.get('confirmations', 0),
                    'signature': tx_hash,
                }
                
            return {}
            
        except Exception as e:
            logger.error(f"获取交易详情失败: {str(e)}")
            return {}

    async def get_transaction_status(self, tx_hash: str) -> Dict[str, Any]:
        """获取交易状态
        
        Args:
            tx_hash: 交易哈希
            
        Returns:
            Dict: {
                'status': 'success' | 'failed' | 'pending',
                'confirmations': int,
                'error': str | None,
                'block_time': int | None,
                'fee': int | None
            }
        """
        try:
            # 获取交易详情
            tx_details = await self._get_transaction_details(tx_hash)
            if not tx_details:
                return {
                    'status': 'pending',
                    'confirmations': 0,
                    'error': None,
                    'block_time': None,
                    'fee': None
                }
            
            # 返回状态信息
            return {
                'status': tx_details.get('status', 'pending'),
                'confirmations': tx_details.get('confirmations', 0),
                'error': tx_details.get('error'),
                'block_time': tx_details.get('block_time'),
                'fee': tx_details.get('fee')
            }
            
        except Exception as e:
            logger.error(f"获取交易状态失败: {str(e)}")
            return {
                'status': 'error',
                'message': f'获取交易状态失败: {str(e)}'
            }

    async def transfer_native(self, from_address: str, to_address: str, amount: Decimal, private_key: str) -> Dict[str, Any]:
        """转账原生SOL代币"""
        try:
            # 添加更详细的日志
            logger.info("=== 开始原生SOL转账 ===")
            logger.info(f"发送方地址: {from_address}")
            logger.info(f"接收方地址: {to_address}")
            logger.info(f"转账金额: {amount} SOL")
            
            # 验证地址
            try:
                to_pubkey = PublicKey(to_address)
                logger.info("接收方地址验证通过")
            except Exception as e:
                logger.error(f"接收方地址验证失败: {str(e)}")
                raise InvalidAddressError("无效的接收地址")
            
            # 获取密钥对
            try:
                keypair = Keypair.from_seed(base58.b58decode(private_key)[:32])
                logger.info("密钥对创建成功")
            except Exception as e:
                logger.error(f"创建密钥对失败: {str(e)}")
                raise TransferError("无效的私钥")

            # 转换金额
            try:
                amount_decimal = Decimal(str(amount))
                lamports = int(amount_decimal * Decimal('1000000000'))
                logger.info(f"转换金额: {amount} SOL = {lamports} lamports")
            except Exception as e:
                logger.error(f"金额转换失败: {str(e)}")
                raise TransferError(f"金额格式错误: {str(e)}")

            # 创建转账交易
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=PublicKey(from_address),
                    to_pubkey=to_pubkey,
                    lamports=lamports
                )
            )
            logger.info("转账指令创建成功")

            # 最大重试次数
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"=== 开始第 {attempt + 1} 次交易尝试 ===")
                    
                    # 创建交易
                    transaction = SolanaTransaction()
                    transaction.add(transfer_instruction)
                    
                    # 获取最新区块哈希
                    recent_blockhash = await self._get_recent_blockhash()
                    logger.info(f"获取到的区块哈希: {recent_blockhash}")
                    transaction.recent_blockhash = cast(Blockhash, recent_blockhash)
                    transaction.fee_payer = PublicKey(from_address)
                    
                    # 签名交易
                    transaction.sign(keypair)
                    logger.info("交易签名完成")
                    
                    # 发送交易
                    response = await self.client.send_raw_transaction(
                        transaction.serialize(),
                        opts=TxOpts(
                            skip_preflight=False,
                            max_retries=5,
                            preflight_commitment=Commitment("confirmed")
                        )
                    )
                    logger.info(f"交易发送响应: {response}")
                    
                    # 获取交易哈希
                    if isinstance(response, dict):
                        if 'error' in response:
                            error_msg = str(response.get('error', {}))
                            logger.error(f"交易发送失败: {error_msg}")
                            if 'BlockhashNotFound' in error_msg:
                                if attempt < max_retries - 1:
                                    logger.warning("区块哈希已过期，重试交易")
                                    await asyncio.sleep(2)
                                    continue
                            raise TransferError(f"发送交易失败: {error_msg}")
                        tx_hash = response.get('result')
                    else:
                        tx_hash = response
                    
                    if not tx_hash:
                        raise TransferError("无法获取交易哈希")
                    
                    logger.info(f"获取到交易哈希: {tx_hash}")
                    
                    # 等待交易确认
                    logger.info("等待交易确认...")
                    confirmation_status = await self._confirm_transaction(str(tx_hash))
                    if not confirmation_status:
                        if attempt < max_retries - 1:
                            logger.warning("交易未确认，重试交易")
                            await asyncio.sleep(2)
                            continue
                        raise TransferError("交易未被确认")
                    
                    logger.info("交易已确认")
                    
                    # 获取交易详情
                    tx_details = await self._get_transaction_details(str(tx_hash))
                    logger.info(f"交易详情: {json.dumps(tx_details, indent=2)}")
                    
                    # 保存交易记录
                    try:
                        await self._save_transaction(
                            wallet_address=from_address,
                            to_address=to_address,
                            amount=amount,
                            token_address=None,  # 原生SOL转账不需要token_address
                            tx_hash=str(tx_hash),
                            tx_info=tx_details
                        )
                        logger.info("交易记录已保存到数据库")
                    except Exception as save_error:
                        logger.error(f"保存交易记录失败: {str(save_error)}")
                        # 不抛出异常，因为交易已经成功了
                    
                    return {
                        'success': tx_details.get('status') == 'success',
                        'transaction_hash': str(tx_hash),
                        'status': tx_details.get('status', 'unknown'),
                        'error': tx_details.get('error'),
                        'fee': str(Decimal(tx_details.get('fee', 0)) / Decimal(1e9)),
                        'block_time': tx_details.get('block_time'),
                        'block_slot': tx_details.get('block_slot'),
                        'confirmations': tx_details.get('confirmations')
                    }
                    
                except Exception as e:
                    logger.error(f"第 {attempt + 1} 次交易尝试失败: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                        continue
                    raise
            
            raise TransferError("多次尝试后交易仍然失败")
            
        except Exception as e:
            logger.error(f"SOL转账失败: {str(e)}")
            return {
                'success': False,
                'status': 'failed',
                'error': str(e),
                'transaction_hash': None
            }

    async def _get_token_info(self, token_address: str) -> Dict[str, Any]:
        """获取代币信息"""
        try:
            # 从数据库获取代币信息
            try:
                token = await Token.objects.aget(chain='SOL', address=token_address)
                return {
                    'name': token.name,
                    'symbol': token.symbol,
                    'decimals': token.decimals,
                    'mint': token_address
                }
            except Token.DoesNotExist:
                logger.warning(f"代币 {token_address} 在数据库中不存在")
            
            # 如果数据库中没有，从链上获取
            response = await self._fetch_with_retry(
                'getTokenMetadata',
                params=[token_address]
            )
            
            if response and isinstance(response, dict):
                token_info = response.get('result', {})
                if token_info:
                    return {
                        'name': token_info.get('name'),
                        'symbol': token_info.get('symbol'),
                        'decimals': token_info.get('decimals', 9),
                        'mint': token_address
                    }
            
            # 如果都获取不到，抛出异常
            raise TransferError(f"无法获取代币 {token_address} 的信息")
            
        except Exception as e:
            logger.error(f"获取代币信息失败: {str(e)}")
            raise TransferError(f"获取代币信息失败: {str(e)}")

    async def transfer_token(self, from_address: str, to_address: str, token_address: str, amount: Decimal, private_key: str) -> Dict[str, Any]:
        """SPL代币转账"""
        try:
            logger.info(f"开始处理转账请求: from={from_address}, to={to_address}, token={token_address}, amount={amount}")
            
            # 验证地址
            if not self._is_valid_address(to_address):
                logger.error(f"无效的接收地址: {to_address}")
                raise InvalidAddressError("无效的接收地址")
            
            # 获取代币精度
            decimals = await self._get_token_decimals(token_address)
            logger.info(f"代币精度: {decimals}")
            
            # 将金额转换为最小单位
            amount_in_smallest = int(amount * Decimal(str(10 ** decimals)))
            logger.info(f"转换后的金额: {amount_in_smallest}")
            
            # 获取发送方代币账户地址
            from_token_account = await self._get_associated_token_address(from_address, token_address)
            logger.info(f"发送方代币账户: {from_token_account}")
            
            # 获取接收方代币账户地址
            to_token_account = await self._get_associated_token_address(to_address, token_address)
            logger.info(f"接收方代币账户: {to_token_account}")
            
            # 检查接收方代币账户是否存在
            to_account_exists = await self._check_token_account_exists(to_token_account)
            logger.info(f"接收方账户是否存在: {to_account_exists}")
            
            # 构建交易指令列表
            instructions = []
            
            # 如果接收方代币账户不存在，添加创建账户指令
            if not to_account_exists:
                create_account_ix = create_associated_token_account(
                    payer=PublicKey(from_address),
                    owner=PublicKey(to_address),
                    mint=PublicKey(token_address)
                )
                instructions.append(create_account_ix)
            
            # 添加转账指令
            transfer_ix = transfer_checked(
                TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=PublicKey(from_token_account),
                    mint=PublicKey(token_address),
                    dest=PublicKey(to_token_account),
                    owner=PublicKey(from_address),
                    amount=amount_in_smallest,
                    decimals=decimals,
                    signers=[]
                )
            )
            instructions.append(transfer_ix)
            
            # 获取最新的 blockhash
            recent_blockhash = await self._get_recent_blockhash()
            
            # 创建交易
            transaction = SolanaTransaction()
            transaction.recent_blockhash = Blockhash(recent_blockhash)
            transaction.fee_payer = PublicKey(from_address)
            
            # 添加所有指令
            for ix in instructions:
                transaction.add(ix)
            
            # 签名交易
            signer = Keypair.from_seed(base58.b58decode(private_key)[:32])
            transaction.sign(signer)
            
            # 发送交易
            logger.info("准备发送交易...")
            
            # 最大重试次数
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # 获取新的区块哈希
                    if attempt > 0:
                        recent_blockhash = await self._get_recent_blockhash()
                        transaction.recent_blockhash = Blockhash(recent_blockhash)
                    
                    response = await self.client.send_transaction(
                        transaction,
                        signer,
                        opts=TxOpts(
                            skip_preflight=True,
                            preflight_commitment=Commitment("confirmed")
                        )
                    )
                    
                    logger.info(f"第 {attempt + 1} 次发送交易响应: {response}")
                    
                    # 获取交易哈希
                    tx_hash = response.get('result') if isinstance(response, dict) else response
                    if not tx_hash:
                        logger.error("无法获取交易哈希")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        raise TransferError("无法获取交易哈希")
                    
                    logger.info(f"交易已发送，hash: {tx_hash}")
                    
                    # 等待交易确认
                    for confirm_attempt in range(5):  # 每次提交尝试5次确认
                        confirmation_status = await self._confirm_transaction(str(tx_hash), max_retries=3)
                        if confirmation_status:
                            logger.info("交易确认成功")
                            # 获取交易详情
                            tx_details = await self._get_transaction_details(str(tx_hash))
                            return {
                                'success': True,
                                'transaction_hash': str(tx_hash),
                                'block_hash': tx_details.get('block_hash') or tx_details.get('recent_blockhash'),
                                'fee': str(Decimal(tx_details.get('fee', 0)) / Decimal(1e9))
                            }
                        logger.warning(f"第 {confirm_attempt + 1} 次确认未成功，继续等待...")
                        await asyncio.sleep(2)
                    
                    # 如果当前提交的确认都失败了，尝试下一次提交
                    logger.warning(f"第 {attempt + 1} 次提交的交易未能确认，尝试重新提交...")
                    await asyncio.sleep(2)
                    continue
                    
                except Exception as e:
                    logger.error(f"第 {attempt + 1} 次发送交易失败: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                        continue
                    raise TransferError(f"发送交易失败: {str(e)}")
            
            raise TransferError("多次尝试后交易仍未成功")
            
        except Exception as e:
            logger.error(f"SPL代币转账失败: {str(e)}")
            return {
                'success': False,
                'status': 'failed',
                'error': str(e),
                'transaction_hash': None
            }

    async def estimate_native_transfer_fee(self, from_address: str, to_address: str, amount: Decimal) -> Decimal:
        """估算SOL转账费用"""
        return Decimal('0.000005')  # SOL转账固定费用

    async def estimate_token_transfer_fee(self, from_address: str, to_address: str, token_address: str, amount: Decimal) -> Decimal:
        """估算SPL代币转账费用"""
        try:
            # 检查目标账户是否存在
            dest_token_account = await self._get_associated_token_address(to_address, token_address)
            if not await self._check_token_account_exists(dest_token_account):
                # 如果目标账户不存在，需要创建账户，费用更高
                return Decimal('0.00205')  # 创建账户 + 转账费用
            return Decimal('0.000005')  # 普通转账费用
        except Exception as e:
            logger.error(f"估算转账费用失败: {str(e)}")
            raise TransferError(f"估算费用失败: {str(e)}")

    def _is_valid_address(self, address: str) -> bool:
        """验证 Solana 地址是否有效"""
        try:
            # 使用 PublicKey 类验证地址
            PublicKey(address)
            return True
        except Exception as e:
            logger.error(f"地址验证失败: {str(e)}")
            return False

    async def _confirm_transaction(self, tx_hash: str, max_retries: int = 15) -> bool:
        """确认交易是否成功"""
        logger.info(f"开始确认交易: {tx_hash}")
        
        try:
            # 初始等待时间改回2秒
            await asyncio.sleep(2)
            
            for attempt in range(max_retries):
                try:
                    logger.debug(f"获取交易状态: {tx_hash}, 尝试次数: {attempt + 1}")
                    
                    # 使用getSignatureStatuses替代getTransaction，更轻量级
                    response = await self._fetch_with_retry(
                        'getSignatureStatuses',
                        params=[[tx_hash]],
                        max_retries=1
                    )
                    
                    if response and isinstance(response, dict):
                        value = response.get('value', [{}])[0]
                        if value:
                            if value.get('err'):
                                logger.error(f"交易执行失败: {value['err']}")
                                return False
                            if value.get('confirmationStatus') in ['confirmed', 'finalized']:
                                logger.info(f"交易确认成功")
                                return True
                    
                    # 固定等待2秒
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"确认交易状态失败: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                        continue
                    return False
            
            logger.error(f"交易确认超时: {tx_hash}")
            return False
            
        except Exception as e:
            logger.error(f"确认交易过程中发生错误: {str(e)}")
            return False

    async def _get_transaction(self, tx_hash: str) -> Dict[str, Any]:
        """获取交易详情"""
        try:
            response = await self.client.get_transaction(tx_hash)
            if response and 'result' in response:
                result = response['result']
                if result:
                    return {
                        'blockhash': result.get('transaction', {}).get('message', {}).get('recentBlockhash', ''),
                        'fee': result.get('meta', {}).get('fee', 0),
                        'status': 'success' if not result.get('meta', {}).get('err') else 'failed'
                    }
            return {}
        except Exception as e:
            logger.error(f"获取交易详情失败: {str(e)}")
            return {}

    async def _save_transaction(self, wallet_address: str, to_address: str, amount: Decimal,
                              token_address: Optional[str], tx_hash: str, tx_info: Dict[str, Any]) -> None:
        """保存交易记录"""
        try:
            logger.info("开始保存交易记录...")
            logger.info(f"交易信息: wallet_address={wallet_address}, to_address={to_address}, amount={amount}")
            logger.info(f"token_address={token_address}, tx_hash={tx_hash}")
            logger.info(f"交易详情: {json.dumps(tx_info, indent=2)}")
            
            # 获取钱包
            wallet = await Wallet.objects.aget(address=wallet_address, chain='SOL', is_active=True)
            logger.info(f"获取到钱包信息: {wallet.address}")
            
            # 准备交易记录数据
            tx_data = {
                'wallet': wallet,
                'chain': 'SOL',
                'tx_hash': tx_hash,
                'tx_type': 'TRANSFER',
                'status': 'SUCCESS' if tx_info.get('status') == 'success' else 'FAILED',
                'from_address': wallet_address,
                'to_address': to_address,
                'amount': amount,
                'token_address': token_address,
                'gas_price': Decimal(str(tx_info.get('fee', 0) / 1e9)),
                'gas_used': Decimal('1'),
                'block_number': tx_info.get('block_slot', 0),
                'block_timestamp': timezone.now()
            }
            logger.info(f"准备保存的交易数据: {json.dumps({k: str(v) for k, v in tx_data.items() if k != 'wallet'}, indent=2)}")
            
            # 创建交易记录
            transaction = await DBTransaction.objects.acreate(**tx_data)
            logger.info(f"交易记录创建成功: id={transaction.id}, tx_hash={tx_hash}")
            
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
            logger.error(f"错误类型: {type(e).__name__}")
            # 不抛出异常，因为交易已经成功了
            pass

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def handle_transfer(self, transfer_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理转账请求"""
        try:
            logger.info(f"收到转账请求数据: {json.dumps(transfer_data, indent=2)}")
            
            # 获取必要参数
            from_address = transfer_data.get('from_address')
            to_address = transfer_data.get('to_address')
            amount = Decimal(str(transfer_data.get('amount', '0')))
            is_native = transfer_data.get('is_native', False)
            private_key = transfer_data.get('private_key')
            
            # 验证基本参数
            if not all([from_address, to_address, amount, private_key]):
                missing_fields = []
                if not from_address: missing_fields.append('from_address')
                if not to_address: missing_fields.append('to_address')
                if not amount: missing_fields.append('amount')
                if not private_key: missing_fields.append('private_key')
                raise TransferError(f"缺少必要参数: {', '.join(missing_fields)}")
            
            logger.info(f"转账类型: {'原生SOL' if is_native else 'SPL代币'}")
            
            # 对于原生 SOL 转账
            if is_native:
                logger.info("执行原生SOL转账")
                result = await self.transfer_native(
                    from_address=from_address,
                    to_address=to_address,
                    amount=amount,
                    private_key=private_key
                )
                # 确保返回值中的 Decimal 转换为字符串
                return {k: str(v) if isinstance(v, Decimal) else v for k, v in result.items()}
            
            # SPL代币转账，才检查 token_address
            token_address = transfer_data.get('token_address')
            if not token_address:
                logger.error("SPL代币转账缺少token_address")
                raise TransferError("代币地址不能为空")
            
            logger.info("执行SPL代币转账")
            result = await self.transfer_token(
                from_address=from_address,
                to_address=to_address,
                token_address=token_address,
                amount=amount,
                private_key=private_key
            )
            # 确保返回值中的 Decimal 转换为字符串
            return {k: str(v) if isinstance(v, Decimal) else v for k, v in result.items()}
            
        except Exception as e:
            logger.error(f"处理转账请求失败: {str(e)}")
            raise TransferError(str(e))