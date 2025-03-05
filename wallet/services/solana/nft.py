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

from ...models import Wallet, Transaction as DBTransaction, Token, NFTCollection
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
                            max_retries=5,
                            preflight_commitment=Commitment("confirmed")
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
                        nft_address=nft_address,
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
            logger.error(f"NFT 转账失败: {str(e)}")
            raise TransferError(f"转账失败: {str(e)}")

    async def _get_nft_info(self, nft_address: str) -> Dict[str, Any]:
        """获取NFT详细信息"""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0",
                    "id": "my-id",
                    "method": "getAsset",
                    "params": {
                        "id": nft_address,
                        "displayOptions": {
                            "showUnverifiedCollections": True,
                            "showCollectionMetadata": True
                        }
                    }
                }
                
                async with session.post(HeliusConfig.get_rpc_url(), json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        if 'result' in result:
                            nft_data = result['result']
                            logger.debug(f"获取到的NFT数据: {nft_data}")
                            
                            # 获取图片URL的多个可能来源
                            image_url = ''
                            
                            # 1. 直接从content.links获取
                            content = nft_data.get('content', {})
                            links = content.get('links', {})
                            if links and isinstance(links, dict):
                                image_url = links.get('image', '')
                                logger.debug(f"从content.links获取的图片URL: {image_url}")
                            
                            # 2. 从content.files获取
                            if not image_url and content.get('files'):
                                for file in content['files']:
                                    if isinstance(file, dict) and file.get('mime', '').startswith('image/'):
                                        image_url = file.get('uri', '')
                                        if image_url:
                                            logger.debug(f"从content.files获取的图片URL: {image_url}")
                                            break
                            
                            # 3. 从metadata获取
                            if not image_url:
                                metadata = nft_data.get('metadata', {})
                                if metadata and isinstance(metadata, dict):
                                    image_url = metadata.get('image', '')
                                    logger.debug(f"从metadata获取的图片URL: {image_url}")
                            
                            # 4. 从根级别获取
                            if not image_url:
                                image_url = nft_data.get('image', '')
                                logger.debug(f"从根级别获取的图片URL: {image_url}")
                            
                            # 获取集合信息
                            collection_data = nft_data.get('collection', {})
                            if not collection_data:
                                collection_data = nft_data.get('grouping', [{}])[0]
                            
                            logger.info(f"最终使用的图片URL: {image_url}")
                            logger.info(f"集合信息: {collection_data}")
                            
                            return {
                                'name': nft_data.get('name', ''),
                                'symbol': nft_data.get('symbol', 'DIGIKONG'),
                                'image': image_url,
                                'description': nft_data.get('description', ''),
                                'attributes': nft_data.get('attributes', []),
                                'metaplex': nft_data.get('metaplex', {}),
                                'collection': collection_data
                            }
                            
                    logger.error(f"获取NFT信息失败: {response.status}")
                    return {}
                    
        except Exception as e:
            logger.error(f"获取NFT信息时出错: {str(e)}")
            return {}

    async def _get_recent_blockhash(self) -> str:
        """获取最新区块哈希"""
        try:
            response = await self.client.get_latest_blockhash(commitment=Commitment("confirmed"))
            logger.debug(f"获取区块哈希响应: {response}")
            
            if response and isinstance(response, dict):
                result = response.get('result', {})
                if isinstance(result, dict):
                    value = result.get('value', {})
                    if isinstance(value, dict):
                        blockhash = value.get('blockhash')
                        if blockhash:
                            return blockhash
            
            raise TransferError("无法获取区块哈希")
            
        except Exception as e:
            logger.error(f"获取区块哈希失败: {str(e)}")
            raise TransferError(f"获取区块哈希失败: {str(e)}")

    async def _confirm_transaction(self, tx_hash: str) -> bool:
        """确认交易是否成功"""
        try:
            for _ in range(30):  # 最多等待30次
                response = await self.client.get_transaction(
                    tx_hash,
                    commitment=Commitment("confirmed")
                )
                
                if response and isinstance(response, dict):
                    result = response.get('result')
                    if result:
                        meta = result.get('meta')
                        if meta is not None:
                            if meta.get('err'):
                                return False
                            return True
                
                await asyncio.sleep(1)
            return False
            
        except Exception as e:
            logger.error(f"确认交易状态失败: {str(e)}")
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

    async def _save_transaction(self, wallet_address: str, to_address: str, nft_address: str,
                              tx_hash: str, tx_info: Dict[str, Any]) -> None:
        """保存交易记录"""
        try:
            wallet = await sync_to_async(Wallet.objects.get)(address=wallet_address, chain='SOL', is_active=True)
            
            # 获取NFT信息
            nft_info = await self._get_nft_info(nft_address)
            logger.info(f"获取到的NFT信息: {nft_info}")
            
            # 从NFT信息中提取集合数据
            collection_data = nft_info.get('collection', {})
            # 使用collection.name作为合约地址
            collection_address = collection_data.get('name', '3Tije1Bfi8URGfZK6JNoXrLivV9SPujZzgEHsXNWuTFR')
            collection_name = nft_info.get('name', '').split('#')[0].strip() or 'DIGIKONG'
            collection_symbol = nft_info.get('symbol', '') or 'DIGIKONG'
            collection_verified = nft_info.get('metaplex', {}).get('primarySaleHappened', True)
            
            # 获取图片URL
            image_url = nft_info.get('image_url', nft_info.get('image', ''))
            logger.info(f"NFT图片URL: {image_url}")
            
            # 创建或更新NFT集合记录
            collection, created = await sync_to_async(NFTCollection.objects.get_or_create)(
                chain='SOL',
                contract_address=collection_address,
                defaults={
                    'name': collection_name,
                    'symbol': collection_symbol,
                    'logo': image_url,
                    'is_verified': collection_verified,
                    'updated_at': timezone.now()
                }
            )
            
            # 如果集合已存在，更新信息
            if not created:
                collection.name = collection_name
                collection.symbol = collection_symbol
                collection.is_verified = collection_verified
                collection.updated_at = timezone.now()
                # 更新logo
                if image_url:
                    collection.logo = image_url
                await sync_to_async(collection.save)()
            
            # 创建交易记录
            await sync_to_async(DBTransaction.objects.create)(
                wallet=wallet,
                chain='SOL',
                tx_hash=tx_hash,
                tx_type='NFT_TRANSFER',
                status='SUCCESS' if tx_info.get('status') == 'success' else 'FAILED',
                from_address=wallet_address,
                to_address=to_address,
                nft_collection=collection,
                nft_token_id=nft_address,
                amount=Decimal('1'),
                gas_price=Decimal(str(tx_info.get('fee', 0) / 1e9)),
                gas_used=Decimal('1'),
                block_number=0,
                block_timestamp=timezone.now()
            )
            logger.info(f"成功保存NFT转账记录: {tx_hash}")
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
            # 不抛出异常，因为转账已经成功了

    def _is_valid_address(self, address: str) -> bool:
        """验证地址是否有效"""
        try:
            PublicKey(address)
            return True
        except Exception:
            return False

    async def _fetch_with_retry(self, method: str, **kwargs) -> Any:
        """带重试的 RPC 请求"""
        for attempt in range(self.max_retries):
            try:
                response = await getattr(self.client, method)(**kwargs)
                return response
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        return None

    async def _find_token_account_for_mint(self, owner_address: str, mint_address: str) -> Optional[str]:
        """查找指定 NFT 的实际代币账户"""
        try:
            # 直接返回关联代币账户
            default_ata = str(get_associated_token_address(
                owner=PublicKey(owner_address),
                mint=PublicKey(mint_address)
            ))
            logger.info(f"使用关联代币账户: {default_ata}")
            
            # 检查账户是否存在并有余额
            try:
                balance_info = await self.client.get_token_account_balance(default_ata)
                if balance_info and isinstance(balance_info, dict):
                    value = balance_info.get('result', {}).get('value', {})
                    amount = value.get('amount', '0')
                    if int(amount) > 0:
                        logger.info(f"关联账户存在且有余额: {amount}")
                        return default_ata
            except Exception as e:
                logger.warning(f"检查关联账户余额失败: {str(e)}")
            
            return default_ata
            
        except Exception as e:
            logger.error(f"查找NFT代币账户失败: {str(e)}")
            return None 

    async def get_all_nft_collections(self, address: str) -> List[Dict]:
        """获取所有 NFT 合集
        
        Args:
            address: 钱包地址
            
        Returns:
            List[Dict]: NFT 合集列表
        """
        try:
            # 调用 Helius API 获取 NFT 资产
            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0",
                    "id": "my-id",
                    "method": HeliusConfig.GET_ASSETS_BY_OWNER,
                    "params": {
                        "ownerAddress": address,
                        "page": 1,
                        "limit": 1000,
                        "displayOptions": {
                            "showUnverifiedCollections": True,
                            "showCollectionMetadata": True
                        }
                    }
                }
                
                async with session.post(HeliusConfig.get_rpc_url(), json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        if 'result' in result and 'items' in result['result']:
                            items = result['result']['items']
                            
                            # 用于存储合集信息的字典
                            collections_map = {}
                            
                            for item in items:
                                try:
                                    # 获取合集信息
                                    content = item.get('content', {})
                                    metadata = content.get('metadata', {})
                                    collection_data = item.get('collection', {})
                                    
                                    # 获取合集标识
                                    collection_symbol = metadata.get('symbol', '')
                                    if not collection_symbol:
                                        continue
                                        
                                    # 如果合集已存在，跳过
                                    if collection_symbol in collections_map:
                                        continue
                                        
                                    # 获取图片 URL
                                    image_url = None
                                    files = content.get('files', [])
                                    if files and isinstance(files, list) and len(files) > 0:
                                        image_url = files[0].get('uri', '')
                                    
                                    if not image_url:
                                        image_url = metadata.get('image', '')
                                        
                                    # 获取合集地址
                                    collection_address = collection_data.get('address', '')
                                    
                                    # 构建合集信息
                                    collection_info = {
                                        'symbol': collection_symbol,
                                        'name': collection_data.get('name', '') or metadata.get('collection', {}).get('name', '') or collection_symbol,
                                        'contract_address': collection_address,
                                        'description': collection_data.get('description', ''),
                                        'logo': image_url,
                                        'is_verified': collection_data.get('verified', False),
                                        'is_spam': collection_data.get('isSpam', False),
                                        'floor_price': collection_data.get('floorPrice', 0),
                                        'floor_price_usd': collection_data.get('floorPriceUsd', 0)
                                    }
                                    
                                    collections_map[collection_symbol] = collection_info
                                    
                                except Exception as e:
                                    logger.error(f"处理 NFT 合集数据时出错: {str(e)}")
                                    continue
                                    
                            # 获取合集的显示状态
                            collection_symbols = list(collections_map.keys())
                            db_collections = await sync_to_async(list)(
                                NFTCollection.objects.filter(
                                    chain='SOL',
                                    symbol__in=collection_symbols
                                ).values('symbol', 'is_visible')
                            )
                            
                            # 创建显示状态映射
                            visibility_map = {c['symbol']: c['is_visible'] for c in db_collections}
                            
                            # 更新合集的显示状态
                            for collection in collections_map.values():
                                collection['is_visible'] = visibility_map.get(collection['symbol'], True)
                            
                            # 按地板价排序
                            collections = list(collections_map.values())
                            collections.sort(key=lambda x: float(x['floor_price_usd'] or 0), reverse=True)
                            
                            return collections
                            
            return []
            
        except Exception as e:
            logger.error(f"获取 NFT 合集列表失败: {str(e)}")
            return []