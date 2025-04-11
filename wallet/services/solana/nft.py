"""Solana NFT 服务"""
import logging
import aiohttp
import asyncio
from decimal import Decimal
from typing import Dict, List, Optional, Any, cast
from django.utils import timezone
from asgiref.sync import sync_to_async
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solana.transaction import Transaction
from solana.keypair import Keypair
from solana.publickey import PublicKey
from spl.token.instructions import get_associated_token_address, transfer_checked, TransferCheckedParams, create_associated_token_account
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
from solana.rpc.types import TxOpts
from solana.blockhash import Blockhash
from solana.system_program import create_account, CreateAccountParams
import base58
import json
from django.core.cache import cache

from ...models import Wallet, Transaction as DBTransaction, Token
from ...exceptions import InsufficientBalanceError, InvalidAddressError, TransferError
from ...services.solana_config import HeliusConfig, RPCConfig, MoralisConfig

logger = logging.getLogger(__name__)

class SolanaNFTService:
    """Solana NFT 服务实现类"""

    def __init__(self):
        """初始化 Solana NFT 服务"""
        # 初始化 RPC 配置
        self.rpc_url = RPCConfig.SOLANA_MAINNET_RPC_URL
        
        # 初始化 RPC 客户端
        self.client = AsyncClient(
            endpoint=self.rpc_url,
            timeout=30,
            commitment=Commitment("confirmed")
        )
        
        # 设置超时和重试配置
        self.timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_connect=5, sock_read=10)
        self.max_retries = 3

    async def _check_token_account(self, address: str) -> bool:
        """检查代币账户是否存在"""
        try:
            response = await self.client.get_account_info(address)
            if response and isinstance(response, dict):
                result = response.get('result', {})
                if result and result.get('value'):
                    return True
            return False
        except Exception as e:
            logger.error(f"检查代币账户失败: {str(e)}")
            return False

    async def transfer_nft(self, from_address: str, to_address: str, nft_address: str, private_key: str) -> Dict[str, Any]:
        """转移 NFT"""
        try:
            # 验证地址
            if not self._is_valid_address(to_address):
                raise InvalidAddressError("无效的接收地址")
            
            # 获取 NFT 元数据
            nft_info = await self._get_nft_info(nft_address)
            if not nft_info:
                raise TransferError("无法获取 NFT 信息")
            
            # 获取发送方密钥对
            keypair = Keypair.from_seed(base58.b58decode(private_key)[:32])
            
            # 获取源和目标的关联账户地址
            source_token_account = get_associated_token_address(
                owner=PublicKey(from_address),
                mint=PublicKey(nft_address)
            )
            destination_token_account = get_associated_token_address(
                owner=PublicKey(to_address),
                mint=PublicKey(nft_address)
            )
            
            # 查找实际持有 NFT 的代币账户
            actual_token_account = await self._find_token_account_for_mint(from_address, nft_address)
            logger.info(f"实际的NFT代币账户: {actual_token_account}")
            
            if actual_token_account:
                # 使用实际的代币账户
                source_token_account = PublicKey(actual_token_account)
                logger.info(f"使用找到的实际代币账户进行转账")
            else:
                # 检查默认关联账户
                has_source_account = await self._check_token_account(str(source_token_account))
                logger.info(f"源账户是否存在: {has_source_account}")
                
                if not has_source_account:
                    raise TransferError("源账户的关联代币账户不存在")
            
            # 检查源账户是否拥有 NFT
            source_account_info = await self.client.get_token_account_balance(str(source_token_account))
            logger.info(f"源账户余额信息: {source_account_info}")
            
            if not source_account_info or not source_account_info.get('result', {}).get('value', {}).get('amount'):
                raise TransferError("您没有这个 NFT 的所有权")
                
            # 获取并记录源账户的 NFT 余额详情
            balance_info = source_account_info.get('result', {}).get('value', {})
            amount = balance_info.get('amount', '0')
            decimals = balance_info.get('decimals', 0)
            ui_amount = balance_info.get('uiAmount', 0)
            
            logger.info(f"NFT 余额详情 - 数量: {amount}, 精度: {decimals}, UI数量: {ui_amount}")
            
            if int(amount) < 1:
                raise TransferError("NFT 余额不足")
                
            # 检查 SOL 余额是否足够支付交易费用
            balance_response = await self.client.get_balance(from_address)
            logger.info(f"SOL 余额响应: {balance_response}")
            
            if not balance_response or not balance_response.get('result', {}).get('value'):
                raise TransferError("无法获取账户余额")
            
            sol_balance = Decimal(str(balance_response.get('result', {}).get('value', 0))) / Decimal('1000000000')  # lamports to SOL
            logger.info(f"SOL 余额: {sol_balance} SOL")
            
            if sol_balance < Decimal('0.001'):  # 假设最低需要 0.001 SOL
                raise TransferError("SOL 余额不足以支付交易费用")
                
            # 检查目标账户是否存在
            has_destination_account = await self._check_token_account(str(destination_token_account))
            logger.info(f"目标账户是否存在: {has_destination_account}")
            
            # 创建转账指令列表
            instructions = []
            
            # 如果目标账户不存在，添加创建账户指令
            if not has_destination_account:
                create_account_ix = create_associated_token_account(
                    payer=PublicKey(from_address),
                    owner=PublicKey(to_address),
                    mint=PublicKey(nft_address)
                )
                instructions.append(create_account_ix)
            
            # 添加转账指令
            transfer_ix = transfer_checked(
                TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=source_token_account,
                    mint=PublicKey(nft_address),
                    dest=destination_token_account,
                    owner=PublicKey(from_address),
                    signers=[],  # NFT 转账不需要额外的签名者
                    amount=1,  # NFT 数量为 1
                    decimals=0  # NFT 精度为 0
                )
            )
            instructions.append(transfer_ix)
            
            # 最大重试次数
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # 创建交易
                    transaction = Transaction()
                    
                    # 添加所有指令
                    for ix in instructions:
                        transaction.add(ix)
                    
                    # 获取最新区块哈希
                    recent_blockhash = await self._get_recent_blockhash()
                    logger.info(f"获取到的区块哈希: {recent_blockhash}")
                    transaction.recent_blockhash = cast(Blockhash, recent_blockhash)
                    
                    # 设置手续费支付者
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
                            preflight_commitment=Commitment("confirmed")
                        )
                    )
                    
                    if not response or not response.get('result'):
                        raise TransferError("发送交易失败")
                    
                    tx_hash = response['result']
                    logger.info(f"交易已发送，哈希: {tx_hash}")
                    
                    # 等待交易确认
                    confirmed = await self._confirm_transaction(tx_hash)
                    if not confirmed:
                        raise TransferError("交易确认失败")
                    
                    # 获取交易详情
                    tx_info = await self._get_transaction(tx_hash)
                    
                    # 保存交易记录
                    await self._save_transaction(
                        wallet_address=from_address,
                        to_address=to_address,
                        nft_address=nft_address,
                        tx_hash=tx_hash,
                        tx_info=tx_info
                    )
                    
                    return {
                        'status': 'success',
                        'message': 'NFT 转移成功',
                        'data': {
                            'tx_hash': tx_hash,
                            'from': from_address,
                            'to': to_address,
                            'nft_address': nft_address
                        }
                    }
                    
                except Exception as e:
                    logger.error(f"第 {attempt + 1} 次尝试失败: {str(e)}")
                    if attempt == max_retries - 1:
                        raise TransferError(f"转移失败: {str(e)}")
                    await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"转移 NFT 失败: {str(e)}")
            raise TransferError(f"转移 NFT 失败: {str(e)}")

    async def _get_nft_info(self, nft_address: str) -> Dict[str, Any]:
        """获取 NFT 信息"""
        try:
            # 从缓存中获取
            cache_key = f"nft_info_{nft_address}"
            cached_info = cache.get(cache_key)
            if cached_info:
                return cached_info
            
            # 从 Helius API 获取
            url = f"{HeliusConfig.BASE_URL}/nft/{nft_address}"
            headers = HeliusConfig.get_headers()
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"获取 NFT 信息失败: {await response.text()}")
                        return {}
                    
                    nft_info = await response.json()
                    
                    # 缓存结果
                    cache.set(cache_key, nft_info, timeout=3600)  # 缓存 1 小时
                    
                    return nft_info
                    
        except Exception as e:
            logger.error(f"获取 NFT 信息失败: {str(e)}")
            return {}

    async def _get_recent_blockhash(self) -> str:
        """获取最新区块哈希"""
        try:
            response = await self.client.get_recent_blockhash()
            if not response or not response.get('result', {}).get('value', {}).get('blockhash'):
                raise TransferError("无法获取最新区块哈希")
            return response['result']['value']['blockhash']
        except Exception as e:
            logger.error(f"获取最新区块哈希失败: {str(e)}")
            raise TransferError(f"获取最新区块哈希失败: {str(e)}")

    async def _confirm_transaction(self, tx_hash: str) -> bool:
        """确认交易"""
        try:
            # 最大重试次数
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    response = await self.client.get_signature_statuses([tx_hash])
                    if not response or not response.get('result', {}).get('value'):
                        continue
                    
                    status = response['result']['value'][0]
                    if not status:
                        continue
                    
                    if status.get('confirmationStatus') == 'confirmed':
                        return True
                    
                    if status.get('confirmationStatus') == 'finalized':
                        return True
                    
                    if status.get('err'):
                        return False
                    
                except Exception as e:
                    logger.error(f"第 {attempt + 1} 次确认交易失败: {str(e)}")
                
                await asyncio.sleep(2)
            
            return False
            
        except Exception as e:
            logger.error(f"确认交易失败: {str(e)}")
            return False

    async def _get_transaction(self, tx_hash: str) -> Dict[str, Any]:
        """获取交易详情"""
        try:
            response = await self.client.get_transaction(tx_hash)
            if not response or not response.get('result'):
                return {}
            
            result = response['result']
            return {
                'block_number': result.get('slot', 0),
                'gas_used': 0,  # Solana 没有 gas
                'status': True  # 假设交易成功
            }
            
        except Exception as e:
            logger.error(f"获取交易详情失败: {str(e)}")
            return {}

    async def _save_transaction(self, wallet_address: str, to_address: str, nft_address: str,
                              tx_hash: str, tx_info: Dict[str, Any]) -> None:
        """保存交易记录"""
        try:
            # 获取钱包
            wallet = await sync_to_async(Wallet.objects.get)(
                address=wallet_address,
                chain='SOLANA'
            )
            
            # 创建交易记录
            await sync_to_async(DBTransaction.objects.create)(
                wallet=wallet,
                tx_hash=tx_hash,
                tx_type='NFT_TRANSFER',
                from_address=wallet_address,
                to_address=to_address,
                amount=1,  # NFT 数量为 1
                token=None,  # NFT 不使用代币模型
                token_info={
                    'token_address': nft_address,
                    'token_id': nft_address  # Solana NFT 使用地址作为 ID
                },
                fee=tx_info.get('gas_used', 0),
                status=tx_info.get('status', True),
                block_number=tx_info.get('block_number', 0),
                block_timestamp=timezone.now()
            )
            
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
            raise

    def _is_valid_address(self, address: str) -> bool:
        """验证地址格式"""
        try:
            PublicKey(address)
            return True
        except:
            return False

    async def _fetch_with_retry(self, method: str, **kwargs) -> Any:
        """带重试的 RPC 调用"""
        for attempt in range(self.max_retries):
            try:
                response = await getattr(self.client, method)(**kwargs)
                return response
            except Exception as e:
                logger.error(f"第 {attempt + 1} 次调用失败: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(1)

    async def _find_token_account_for_mint(self, owner_address: str, mint_address: str) -> Optional[str]:
        """查找持有指定代币的代币账户"""
        try:
            # 获取所有代币账户
            response = await self.client.get_token_accounts_by_owner(
                owner_address,
                {'mint': mint_address}
            )
            
            if not response or not response.get('result', {}).get('value'):
                return None
            
            accounts = response['result']['value']
            for account in accounts:
                account_info = account.get('account', {}).get('data', {})
                if account_info.get('parsed', {}).get('info', {}).get('tokenAmount', {}).get('amount', '0') == '1':
                    return account.get('pubkey')
            
            return None
            
        except Exception as e:
            logger.error(f"查找代币账户失败: {str(e)}")
            return None

    async def get_all_nft_collections(self, address: str) -> List[Dict]:
        """获取所有 NFT 合集列表（包括隐藏的）"""
        try:
            # 获取所有 NFT
            url = f"{HeliusConfig.BASE_URL}/nft/owner/{address}"
            headers = HeliusConfig.get_headers()
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"获取 NFT 列表失败: {await response.text()}")
                        return []
                    
                    result = await response.json()
                    
                    # 检查返回的数据格式
                    if not isinstance(result, list):
                        logger.error(f"API 返回的数据格式不正确: {result}")
                        return []
                    
                    # 按合约地址分组
                    collections = {}
                    for nft in result:
                        if not isinstance(nft, dict):
                            logger.warning(f"NFT 数据格式不正确: {nft}")
                            continue
                            
                        contract_address = nft.get('mint', '').lower()
                        if not contract_address:
                            continue
                            
                        if contract_address not in collections:
                            collections[contract_address] = {
                                'chain': self.chain,
                                'contract_address': contract_address,
                                'name': nft.get('name', ''),
                                'symbol': nft.get('symbol', ''),
                                'contract_type': 'SPL',
                                'logo': nft.get('image', ''),
                                'is_verified': False,
                                'is_spam': False,
                                'is_visible': True,  # 默认显示
                                'floor_price': '0',
                                'floor_price_usd': '0',
                                'floor_price_currency': 'sol',
                                'nft_count': 0
                            }
                            
                        collections[contract_address]['nft_count'] += 1
                    
                    return list(collections.values())
                    
        except Exception as e:
            logger.error(f"获取 NFT 合集列表失败: {str(e)}")
            return []