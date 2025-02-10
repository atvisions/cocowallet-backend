import logging
from decimal import Decimal
from typing import Dict, Any, Optional, cast, Union
import asyncio
import aiohttp
from django.utils import timezone
import base58

from solana.rpc.async_api import AsyncClient
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
from ..base.transfer import BaseTransferService
from ...exceptions import InsufficientBalanceError, InvalidAddressError, TransferError
from ...api_config import RPCConfig, MoralisConfig

logger = logging.getLogger(__name__)

class SolanaTransferService(BaseTransferService):
    def __init__(self):
        """初始化 Solana 转账服务"""
        super().__init__()
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }
        self.timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_connect=5, sock_read=10)
        self.rpc_url = RPCConfig.SOLANA_MAINNET_RPC_URL
        self.backup_nodes = RPCConfig.SOLANA_BACKUP_NODES
        # 初始化主要和备用 RPC 节点
        self.rpc_urls = [self.rpc_url]
        if isinstance(self.backup_nodes, list):
            self.rpc_urls.extend(self.backup_nodes)
        self.current_rpc_index = 0
        self.client = AsyncClient(self.rpc_urls[self.current_rpc_index], timeout=30)
        
    async def _switch_rpc_node(self):
        """切换到下一个可用的 RPC 节点"""
        try:
            # 获取当前节点的索引
            current_index = self.rpc_urls.index(self.rpc_url)
            # 尝试切换到下一个节点
            for i in range(len(self.rpc_urls)):
                next_index = (current_index + i + 1) % len(self.rpc_urls)
                next_url = self.rpc_urls[next_index]
                
                # 测试新节点是否可用
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                        response = await self._fetch_with_retry(
                            session,
                            next_url,
                            method="post",
                            json={
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "getLatestBlockhash",
                                "params": [{"commitment": "confirmed"}]
                            }
                        )
                        
                        if response and isinstance(response, dict):
                            result = response.get('result')
                            if result and isinstance(result, dict):
                                value = result.get('value', {})
                                if isinstance(value, dict) and value.get('blockhash'):
                                    self.rpc_url = next_url
                                    self.client = AsyncClient(next_url, timeout=30)
                                    logger.info(f"成功切换到 RPC 节点: {next_url}")
                                    return True
                except Exception as e:
                    logger.warning(f"测试节点 {next_url} 失败: {str(e)}")
                    continue
            
            # 如果所有节点都不可用，尝试使用公共节点
            public_nodes = [
                'https://api.mainnet-beta.solana.com',
                'https://solana.public-rpc.com',
                'https://rpc.ankr.com/solana'
            ]
            
            for url in public_nodes:
                if url not in self.rpc_urls:
                    try:
                        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                            response = await self._fetch_with_retry(
                                session,
                                url,
                                method="post",
                                json={
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "getLatestBlockhash",
                                    "params": [{"commitment": "confirmed"}]
                                }
                            )
                            
                            if response and isinstance(response, dict):
                                result = response.get('result')
                                if result and isinstance(result, dict):
                                    value = result.get('value', {})
                                    if isinstance(value, dict) and value.get('blockhash'):
                                        self.rpc_url = url
                                        self.client = AsyncClient(url, timeout=30)
                                        # 将可用的公共节点添加到节点列表中
                                        if url not in self.rpc_urls:
                                            self.rpc_urls.append(url)
                                        logger.info(f"成功切换到公共节点: {url}")
                                        return True
                    except Exception as e:
                        logger.warning(f"测试公共节点 {url} 失败: {str(e)}")
                        continue
            
            logger.error("所有RPC节点都不可用")
            return False
            
        except Exception as e:
            logger.error(f"切换RPC节点失败: {str(e)}")
            return False

    async def _get_recent_blockhash(self) -> str:
        """获取最新的区块哈希，带重试机制和节点切换"""
        max_retries = 5  # 增加重试次数
        retry_delay = 2  # 增加重试延迟
        
        for attempt in range(max_retries):
            try:
                # 构建标准的 JSON-RPC 2.0 请求
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getLatestBlockhash",
                    "params": [
                        {
                            "commitment": "confirmed"
                        }
                    ]
                }
                
                # 使用 aiohttp 直接发送请求
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    headers = {"Content-Type": "application/json"}
                    async with session.post(
                        self.rpc_url,
                        json=payload,
                        headers=headers
                    ) as resp:
                        response = await resp.json()
                        logger.debug(f"获取区块哈希响应: {response}")
                        
                        if response and 'result' in response:
                            result = response['result']
                            if isinstance(result, dict):
                                value = result.get('value', {})
                                if isinstance(value, dict):
                                    blockhash = value.get('blockhash')
                                    if blockhash:
                                        logger.info(f"成功获取区块哈希: {blockhash}")
                                        return blockhash
                        
                        # 如果响应中包含错误
                        if 'error' in response:
                            error = response['error']
                            if isinstance(error, dict):
                                error_msg = error.get('message', '')
                                if 'App is inactive' in error_msg or 'Invalid request' in error_msg:
                                    # 切换到下一个节点
                                    if await self._switch_rpc_node():
                                        logger.info("成功切换RPC节点，重试获取区块哈希")
                                        continue
                
                # 如果没有获取到有效的区块哈希
                error_msg = f"第 {attempt + 1} 次尝试获取区块哈希失败，响应: {response}"
                logger.warning(error_msg)
                
                # 尝试切换节点
                if await self._switch_rpc_node():
                    await asyncio.sleep(retry_delay)
                    continue
                    
            except Exception as e:
                error_msg = f"获取区块哈希出错: {str(e)}"
                logger.error(error_msg)
                
                # 尝试切换节点
                if await self._switch_rpc_node():
                    await asyncio.sleep(retry_delay)
                    continue
                
            # 增加重试间隔
            await asyncio.sleep(retry_delay * (attempt + 1))
                
        raise TransferError("多次尝试后仍无法获取区块哈希，请稍后重试")

    def get_health_check_url(self) -> str:
        """获取健康检查URL"""
        return self.rpc_url
        
    async def check_health(self) -> Dict[str, Any]:
        """检查服务健康状态"""
        try:
            # 使用父类的健康检查方法
            health_status = await super().check_health()
            
            # 额外检查 Solana RPC 节点状态
            response = await self.client.get_recent_blockhash()
            if response and 'result' in response:
                health_status['solana_rpc'] = {
                    'status': 'ok',
                    'message': '节点连接正常'
                }
            else:
                health_status['solana_rpc'] = {
                    'status': 'error',
                    'message': '无法获取区块哈希'
                }
            
            return health_status
        except Exception as e:
            return {
                'status': 'error',
                'message': f'服务异常: {str(e)}',
                'solana_rpc': {
                    'status': 'error',
                    'message': str(e)
                }
            }

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
            # 构建标准的 JSON-RPC 2.0 请求
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    account_address,
                    {
                        "encoding": "base64",
                        "commitment": "confirmed"
                    }
                ]
            }
            
            # 使用 aiohttp 直接发送请求
            async with aiohttp.ClientSession() as session:
                headers = {"Content-Type": "application/json"}
                async with session.post(
                    self.rpc_url,
                    json=payload,
                    headers=headers,
                    timeout=10
                ) as resp:
                    response = await resp.json()
                    logger.debug(f"检查账户响应: {response}")
                    
                    if response and 'result' in response:
                        result = response['result']
                        if isinstance(result, dict):
                            value = result.get('value')
                            return value is not None and len(value) > 0
            return False
        except Exception as e:
            logger.error(f"检查代币账户失败: {str(e)}")
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

    async def transfer_native(self, from_address: str, to_address: str, amount: Decimal, private_key: str) -> Dict[str, Any]:
        """转账原生SOL代币"""
        try:
            # 验证地址
            try:
                to_pubkey = PublicKey(to_address)
            except Exception:
                raise InvalidAddressError("无效的接收地址")
            
            # 获取密钥对
            keypair = Keypair.from_seed(base58.b58decode(private_key)[:32])
            
            # 创建转账交易
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=PublicKey(from_address),
                    to_pubkey=to_pubkey,
                    lamports=int(amount * Decimal('1000000000'))  # 转换为lamports
                )
            )
            
            # 最大重试次数
            max_retries = 3
            for attempt in range(max_retries):
                try:
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
                    
                    # 预检查交易
                    try:
                        await self.client.simulate_transaction(transaction)
                    except Exception as sim_error:
                        logger.error(f"交易预检查失败: {str(sim_error)}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        raise TransferError(f"交易预检查失败: {str(sim_error)}")
                    
                    # 发送交易
                    response = await self.client.send_raw_transaction(
                        transaction.serialize(),
                        opts=TxOpts(
                            skip_preflight=False,  # 启用预检查
                            max_retries=5,
                            preflight_commitment="confirmed"
                        )
                    )
                    
                    # 处理响应
                    if isinstance(response, dict):
                        if 'error' in response:
                            error_msg = str(response.get('error', {}))
                            if 'BlockhashNotFound' in error_msg:
                                logger.warning("区块哈希已过期，重试交易")
                                await asyncio.sleep(2)
                                continue
                            raise TransferError(f"发送交易失败: {error_msg}")
                            
                        tx_hash = response.get('result')
                        if not tx_hash:
                            raise TransferError("无法获取交易哈希")
                    else:
                        tx_hash = response
                    
                    # 等待交易确认
                    confirmation_status = await self._confirm_transaction(tx_hash)
                    if not confirmation_status:
                        if attempt < max_retries - 1:
                            logger.warning("交易未确认，重试交易")
                            await asyncio.sleep(2)
                            continue
                        raise TransferError("交易未被确认")
                    
                    # 获取交易详情
                    tx_info = await self._get_transaction(str(tx_hash))
                    
                    # 保存交易记录
                    await self._save_transaction(
                        wallet_address=from_address,
                        to_address=to_address,
                        amount=amount,
                        token_address=None,
                        tx_hash=str(tx_hash),
                        tx_info=tx_info
                    )
                    
                    return {
                        'success': True,
                        'transaction_hash': str(tx_hash),
                        'block_hash': tx_info.get('blockhash', ''),
                        'fee': str(tx_info.get('fee', 0))
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
            raise TransferError(f"转账失败: {str(e)}")

    async def transfer_token(self, from_address: str, to_address: str, token_address: str, amount: Decimal, private_key: str) -> Dict[str, Any]:
        """SPL代币转账"""
        try:
            # 验证地址
            if not self._is_valid_address(to_address):
                raise InvalidAddressError("无效的接收地址")
            
            # 获取代币精度
            decimals = await self._get_token_decimals(token_address)
            
            # 将金额转换为最小单位
            amount_in_smallest = int(amount * Decimal(str(10 ** decimals)))
            
            # 获取发送方代币账户地址
            from_token_account = await self._get_associated_token_address(from_address, token_address)
            
            # 获取接收方代币账户地址
            to_token_account = await self._get_associated_token_address(to_address, token_address)
            
            # 检查接收方代币账户是否存在
            to_account_exists = await self._check_token_account_exists(to_token_account)
            
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
            serialized_tx = base58.b58encode(transaction.serialize()).decode('utf-8')
            
            # 使用 sendTransaction 方法发送交易
            response = await self.client.send_raw_transaction(
                transaction.serialize(),
                opts=TxOpts(
                    skip_preflight=True,
                    max_retries=5
                )
            )
            
            if isinstance(response, dict) and 'error' in response:
                error_msg = str(response.get('error', {}))
                raise TransferError(f"发送交易失败: {error_msg}")
            
            # 获取交易哈希
            tx_hash = response.get('result') if isinstance(response, dict) else response
            if not tx_hash:
                raise TransferError("无法获取交易哈希")
            
            # 等待交易确认
            confirmation_status = await self._confirm_transaction(tx_hash)
            if not confirmation_status:
                raise TransferError("交易未被确认")
            
            # 获取交易详情
            tx_info = await self._get_transaction(str(tx_hash))
            
            # 保存交易记录
            await self._save_transaction(
                wallet_address=from_address,
                to_address=to_address,
                amount=amount,
                token_address=token_address,
                tx_hash=str(tx_hash),
                tx_info=tx_info
            )
            
            return {
                'success': True,
                'transaction_hash': str(tx_hash),
                'block_hash': tx_info.get('blockhash', ''),
                'fee': str(tx_info.get('fee', 0))
            }
            
        except Exception as e:
            logger.error(f"SPL代币转账失败: {str(e)}")
            raise TransferError(f"转账失败: {str(e)}")

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

    async def _confirm_transaction(self, tx_hash: Union[str, Dict[str, Any]], max_retries: int = 30) -> bool:
        """确认交易是否成功"""
        try:
            # 处理 tx_hash 参数
            if isinstance(tx_hash, dict):
                if 'result' in tx_hash:
                    tx_hash = str(tx_hash['result'])
                elif 'transaction_hash' in tx_hash:
                    tx_hash = str(tx_hash['transaction_hash'])
                else:
                    for key, value in tx_hash.items():
                        if isinstance(value, str) and len(value) >= 86:
                            tx_hash = value
                            break
                    else:
                        logger.error(f"无法从响应中获取交易哈希: {tx_hash}")
                        return False
            
            # 确保 tx_hash 是字符串类型
            tx_hash = str(tx_hash).strip()
            if not tx_hash:
                logger.error("交易哈希为空")
                return False
                
            logger.info(f"开始确认交易: {tx_hash}")
            
            # 增加初始等待时间
            await asyncio.sleep(5)
            
            for i in range(max_retries):
                try:
                    # 使用不同的确认方法
                    confirmation_methods = [
                        self._confirm_with_signature_status,
                        self._confirm_with_transaction_status
                    ]
                    
                    for method in confirmation_methods:
                        try:
                            status = await method(tx_hash)
                            if status:
                                logger.info(f"交易已确认: {tx_hash}")
                                return True
                        except Exception as method_error:
                            logger.warning(f"确认方法 {method.__name__} 失败: {str(method_error)}")
                            continue
                    
                    # 如果所有方法都失败，检查是否需要切换节点
                    if i > 0 and i % 5 == 0:
                        if await self._switch_rpc_node():
                            logger.info("已切换到新的 RPC 节点")
                            await asyncio.sleep(2)
                            continue
                    
                    # 动态调整等待时间
                    wait_time = min(2 * (i + 1), 10)
                    logger.warning(f"第 {i + 1} 次确认: 交易尚未上链，等待 {wait_time} 秒")
                    await asyncio.sleep(wait_time)
                    
                except Exception as e:
                    logger.warning(f"第 {i + 1} 次确认交易状态失败: {str(e)}")
                    if 'App is inactive' in str(e):
                        if await self._switch_rpc_node():
                            logger.info("已切换到新的 RPC 节点")
                            await asyncio.sleep(2)
                            continue
                    await asyncio.sleep(2)
            
            logger.error(f"交易确认超时: {tx_hash}")
            return False
            
        except Exception as e:
            logger.error(f"确认交易状态时出错: {str(e)}")
            return False
            
    async def _confirm_with_signature_status(self, tx_hash: str) -> bool:
        """使用签名状态确认交易"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            response = await self._fetch_with_retry(
                session,
                self.rpc_url,
                method="post",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignatureStatuses",
                    "params": [
                        [tx_hash],
                        {"searchTransactionHistory": True}
                    ]
                }
            )
            
            if response and isinstance(response, dict):
                result = response.get('result', {})
                if result and isinstance(result, dict):
                    value = result.get('value', [])
                    if value and isinstance(value, list) and len(value) > 0:
                        status = value[0]
                        if status is None:
                            return False
                            
                        if status.get('err'):
                            error_msg = str(status['err'])
                            logger.error(f"交易失败: {error_msg}")
                            return False
                            
                        confirmation_status = status.get('confirmationStatus')
                        return confirmation_status == 'finalized'
            
            return False
            
    async def _confirm_with_transaction_status(self, tx_hash: str) -> bool:
        """使用交易状态确认交易"""
        try:
            response = await self.client.get_transaction(
                tx_hash,
                commitment="finalized"
            )
            
            if response and isinstance(response, dict):
                result = response.get('result')
                if result:
                    meta = result.get('meta')
                    if meta is not None:
                        if meta.get('err'):
                            logger.error(f"交易执行失败: {meta['err']}")
                            return False
                        return True
            return False
            
        except Exception as e:
            logger.warning(f"获取交易状态失败: {str(e)}")
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
                              token_address: str, tx_hash: str, tx_info: Dict[str, Any]) -> None:
        """保存交易记录"""
        try:
            wallet = await Wallet.objects.aget(address=wallet_address, chain='SOL', is_active=True)
            token = None
            if token_address:
                token = await Token.objects.aget(chain='SOL', address=token_address)
            
            await DBTransaction.objects.acreate(
                wallet=wallet,
                chain='SOL',
                tx_hash=tx_hash,
                tx_type='TRANSFER',
                status='SUCCESS' if tx_info.get('status') == 'success' else 'FAILED',
                from_address=wallet_address,
                to_address=to_address,
                amount=amount,
                token=token,
                gas_price=Decimal(str(tx_info.get('fee', 0) / 1e9)),  # 转换为 SOL
                gas_used=Decimal('1'),
                block_number=0,  # Solana 不使用区块号
                block_timestamp=timezone.now()
            )
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}") 