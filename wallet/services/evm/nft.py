"""EVM NFT 服务"""
import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal
import aiohttp
from web3 import Web3
from django.utils import timezone
from asgiref.sync import sync_to_async
import json

from ...models import Wallet, Transaction, NFTCollection
from ...api_config import RPCConfig, MoralisConfig
from ...exceptions import (
    WalletNotFoundError, 
    ChainNotSupportError, 
    InvalidAddressError,
    TransferError
)
from .utils import EVMUtils

logger = logging.getLogger(__name__)

# ERC721 代币 ABI
ERC721_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "tokenURI",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    },
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
        "constant": False,
        "inputs": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "tokenId", "type": "uint256"}
        ],
        "name": "transferFrom",
        "outputs": [],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "tokenId", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "getApproved",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    }
]

class EVMNFTService:
    """EVM NFT 服务实现类"""

    def __init__(self, chain: str):
        """初始化
        
        Args:
            chain: 链标识(ETH/BSC/POLYGON/AVAX/BASE)
        """
        self.chain = chain
        self.chain_config = EVMUtils.get_chain_config(chain)
        self.web3 = EVMUtils.get_web3(chain)
        
        # Moralis API 配置
        self.chain_id = MoralisConfig.get_chain_id(chain)
        self.headers = MoralisConfig.get_headers()
        self.timeout = aiohttp.ClientTimeout(total=MoralisConfig.TIMEOUT)

    async def get_nft_collections(self, address: str) -> List[Dict]:
        """获取 NFT 合集列表（仅显示可见的）
        
        Args:
            address: 钱包地址
            
        Returns:
            List[Dict]: NFT 合集列表
        """
        try:
            # 获取所有 NFT
            url = f"{MoralisConfig.BASE_URL}/{address}/nft"
            params = {
                'chain': self.chain_id,
                'format': 'decimal'
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        logger.error(f"获取 NFT 列表失败: {await response.text()}")
                        return []
                    
                    result = await response.json()
                    
                    # 检查返回的数据格式
                    if isinstance(result, dict) and 'result' in result:
                        nft_list = result['result']
                    elif isinstance(result, list):
                        nft_list = result
                    else:
                        logger.error(f"API 返回的数据格式不正确: {result}")
                        return []
                    
                    # 按合约地址分组
                    collections = {}
                    for nft in nft_list:
                        if not isinstance(nft, dict):
                            logger.warning(f"NFT 数据格式不正确: {nft}")
                            continue
                            
                        contract_address = nft.get('token_address', '').lower()
                        if not contract_address:
                            continue
                            
                        if contract_address not in collections:
                            collections[contract_address] = {
                                'chain': self.chain,
                                'contract_address': contract_address,
                                'name': nft.get('name', ''),
                                'symbol': nft.get('symbol', ''),
                                'contract_type': nft.get('contract_type', 'ERC721'),
                                'logo': nft.get('token_uri', ''),
                                'is_verified': False,
                                'is_spam': False,
                                'is_visible': True,  # 默认显示
                                'floor_price': '0',
                                'floor_price_usd': '0',
                                'floor_price_currency': 'eth',
                                'nft_count': 0
                            }
                            
                        collections[contract_address]['nft_count'] += 1
                    
                    # 获取已存在的合集信息
                    existing_collections = await sync_to_async(list)(
                        NFTCollection.objects.filter(
                            chain=self.chain,
                            contract_address__in=list(collections.keys())
                        ).values('contract_address', 'is_verified', 'is_spam', 'is_visible', 'floor_price', 'floor_price_usd')
                    )
                    
                    # 更新合集信息
                    for collection in existing_collections:
                        contract_address = collection['contract_address']
                        if contract_address in collections:
                            collections[contract_address].update({
                                'is_verified': collection['is_verified'],
                                'is_spam': collection['is_spam'],
                                'is_visible': collection['is_visible'],
                                'floor_price': str(collection['floor_price']),
                                'floor_price_usd': str(collection['floor_price_usd'])
                            })
                    
                    # 保存新的合集
                    for collection_data in collections.values():
                        await self._save_collection(collection_data)
                    
                    # 只返回可见的合集
                    visible_collections = [
                        collection for collection in collections.values()
                        if collection['is_visible']
                    ]
                    
                    return visible_collections
                    
        except Exception as e:
            logger.error(f"获取 NFT 合集列表失败: {str(e)}")
            return []

    async def get_nfts(self, address: str, collection_address: Optional[str] = None) -> List[Dict]:
        """获取 NFT 列表
        
        Args:
            address: 钱包地址
            collection_address: NFT 合集地址
            
        Returns:
            List[Dict]: NFT 列表，只包含基本信息
        """
        try:
            url = f"{MoralisConfig.BASE_URL}/{address}/nft"
            params = {
                'chain': self.chain_id,
                'format': 'decimal',
                'media_items': 'true',
                'normalizeMetadata': 'true'
            }
            
            if collection_address:
                params['token_addresses'] = collection_address  # 修改为单个地址字符串
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        logger.error(f"获取 NFT 列表失败: {await response.text()}")
                        return []
                    
                    result = await response.json()
                    nfts = []
                    
                    # 检查返回的数据格式
                    if isinstance(result, dict) and 'result' in result:
                        nft_list = result['result']
                    elif isinstance(result, list):
                        nft_list = result
                    else:
                        logger.error(f"API 返回的数据格式不正确: {result}")
                        return []
                    
                    for nft in nft_list:
                        try:
                            if not isinstance(nft, dict):
                                continue
                                
                            # 获取 NFT 元数据
                            metadata = nft.get('normalized_metadata', {})
                            if not metadata:
                                metadata = nft.get('metadata', {})
                                if isinstance(metadata, str):
                                    try:
                                        metadata = json.loads(metadata)
                                    except:
                                        metadata = {}
                            
                            # 构建简化的 NFT 数据
                            nft_data = {
                                'token_address': nft.get('token_address'),
                                'token_id': nft.get('token_id'),
                                'name': metadata.get('name', ''),
                                'image': metadata.get('image', ''),
                                'owner_of': nft.get('owner_of'),
                                'amount': nft.get('amount', '1')
                            }
                            
                            # 只添加缩略图信息
                            media = nft.get('media', {})
                            if isinstance(media, dict):
                                items = media.get('items', [])
                                if isinstance(items, list):
                                    for item in items:
                                        if isinstance(item, dict) and item.get('format') in ['png', 'jpeg', 'jpg', 'gif']:
                                            nft_data['thumbnail'] = item.get('thumbnail', '')
                                            break
                            
                            nfts.append(nft_data)
                            
                        except Exception as e:
                            logger.error(f"处理 NFT 数据失败: {str(e)}")
                            continue
                    
                    return nfts
                    
        except Exception as e:
            logger.error(f"获取 NFT 列表失败: {str(e)}")
            return []

    async def get_nft_details(self, token_address: str, token_id: str) -> Dict:
        """获取 NFT 详情
        
        Args:
            token_address: NFT 合约地址
            token_id: NFT Token ID
            
        Returns:
            Dict: NFT 详情
        """
        try:
            url = f"{MoralisConfig.BASE_URL}/nft/{token_address}/{token_id}"
            params = {
                'chain': self.chain_id,
                'format': 'decimal',
                'media_items': 'true',
                'normalizeMetadata': 'true'
            }
            
            logger.debug(f"请求 NFT 详情: {url}, 参数: {params}")
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    response_text = await response.text()
                    logger.debug(f"Moralis API 响应: {response_text}")
                    
                    if response.status != 200:
                        logger.error(f"获取 NFT 详情失败: {response_text}")
                        return {}
                    
                    try:
                        nft = json.loads(response_text)
                    except json.JSONDecodeError:
                        logger.error(f"解析 NFT 详情失败: {response_text}")
                        return {}
                    
                    try:
                        # 获取 NFT 元数据
                        metadata = nft.get('normalized_metadata', {})
                        if not metadata and nft.get('metadata'):
                            try:
                                if isinstance(nft['metadata'], str):
                                    metadata = json.loads(nft['metadata'])
                                else:
                                    metadata = nft['metadata']
                            except json.JSONDecodeError:
                                logger.error(f"解析 NFT 元数据失败: {nft['metadata']}")
                                metadata = {}
                        
                        # 获取当前所有者
                        owner = await self._get_nft_owner(token_address, token_id)
                        
                        # 构建 NFT 详情数据
                        nft_data = {
                            'token_address': token_address,
                            'token_id': token_id,
                            'contract_type': nft.get('contract_type', 'ERC721'),
                            'name': metadata.get('name', ''),
                            'description': metadata.get('description', ''),
                            'image': metadata.get('image', ''),
                            'animation_url': metadata.get('animation_url', ''),
                            'attributes': metadata.get('attributes', []),
                            'owner_of': owner,
                            'token_uri': nft.get('token_uri', ''),
                            'amount': nft.get('amount', '1'),
                            'block_number_minted': nft.get('block_number_minted'),
                            'last_token_uri_sync': nft.get('last_token_uri_sync'),
                            'last_metadata_sync': nft.get('last_metadata_sync')
                        }
                        
                        # 添加媒体信息
                        if nft.get('media', {}):
                            media = nft['media']
                            nft_data.update({
                                'media_collection': media.get('collection', {}),
                                'media_items': media.get('items', []),
                                'media_status': media.get('status')
                            })
                        
                        logger.debug(f"NFT 详情数据: {nft_data}")
                        return nft_data
                        
                    except Exception as e:
                        logger.error(f"处理 NFT 详情数据失败: {str(e)}")
                        return {}
                    
        except Exception as e:
            logger.error(f"获取 NFT 详情失败: {str(e)}")
            return {}

    async def _get_nft_owner(self, token_address: str, token_id: str) -> str:
        """获取 NFT 当前所有者
        
        Args:
            token_address: NFT 合约地址
            token_id: NFT Token ID
            
        Returns:
            str: 所有者地址
        """
        try:
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC721_ABI
            )
            owner = await contract.functions.ownerOf(int(token_id)).call()
            return owner
        except Exception as e:
            logger.error(f"获取 NFT 所有者失败: {str(e)}")
            return ''

    async def _get_last_transfer(self, token_address: str, token_id: str) -> Dict:
        """获取 NFT 最后一次转移记录
        
        Args:
            token_address: NFT 合约地址
            token_id: NFT Token ID
            
        Returns:
            Dict: 转移记录
        """
        try:
            url = f"{MoralisConfig.BASE_URL}/nft/{token_address}/{token_id}/transfers"
            params = {
                'chain': self.chain_id,
                'format': 'decimal',
                'limit': 1
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        return {}
                        
                    result = await response.json()
                    if result and len(result) > 0:
                        transfer = result[0]
                        return {
                            'from_address': transfer.get('from_address'),
                            'to_address': transfer.get('to_address'),
                            'transaction_hash': transfer.get('transaction_hash'),
                            'block_timestamp': transfer.get('block_timestamp'),
                            'block_number': transfer.get('block_number')
                        }
                    return {}
                    
        except Exception as e:
            logger.error(f"获取 NFT 转移记录失败: {str(e)}")
            return {}

    async def _save_collection(self, collection_data: Dict) -> None:
        """保存 NFT 合集
        
        Args:
            collection_data: NFT 合集数据
        """
        try:
            # 创建一个新的字典，避免修改原始数据
            data = collection_data.copy()
            
            # 确保所有字段都不为 None
            data['floor_price'] = '0' if data.get('floor_price') is None else data.get('floor_price', '0')
            data['floor_price_usd'] = '0' if data.get('floor_price_usd') is None else data.get('floor_price_usd', '0')
            data['floor_price_currency'] = 'eth' if data.get('floor_price_currency') is None else data.get('floor_price_currency', 'eth')
            data['logo'] = '' if data.get('logo') is None else data.get('logo', '')
            data['banner'] = '' if data.get('banner') is None else data.get('banner', '')
            data['description'] = '' if data.get('description') is None else data.get('description', '')
            data['name'] = 'Unknown Collection' if data.get('name') is None else data.get('name', 'Unknown Collection')
            data['symbol'] = '' if data.get('symbol') is None else data.get('symbol', '')
            data['contract_type'] = 'ERC721' if data.get('contract_type') is None else data.get('contract_type', 'ERC721')
            
            # 转换为 Decimal
            try:
                data['floor_price'] = Decimal(str(data['floor_price']))
            except:
                data['floor_price'] = Decimal('0')
                
            try:
                data['floor_price_usd'] = Decimal(str(data['floor_price_usd']))
            except:
                data['floor_price_usd'] = Decimal('0')
            
            # 保存或更新合集
            await sync_to_async(NFTCollection.objects.update_or_create)(
                chain=data['chain'],
                contract_address=data['contract_address'],
                defaults={
                    'name': data['name'],
                    'symbol': data['symbol'],
                    'contract_type': data['contract_type'],
                    'description': data['description'],
                    'logo': data['logo'],
                    'banner': data['banner'],
                    'is_verified': data.get('is_verified', False),
                    'is_spam': data.get('is_spam', False),
                    'is_visible': data.get('is_visible', True),
                    'floor_price': data['floor_price'],
                    'floor_price_usd': data['floor_price_usd'],
                    'floor_price_currency': data['floor_price_currency']
                }
            )
            
        except Exception as e:
            logger.error(f"保存 NFT 合集失败: {str(e)}, 数据: {collection_data}")

    async def get_all_nft_collections(self, address: str) -> List[Dict]:
        """获取所有 NFT 合集列表（包括隐藏的）
        
        Args:
            address: 钱包地址
            
        Returns:
            List[Dict]: NFT 合集列表
        """
        try:
            # 获取所有 NFT
            url = f"{MoralisConfig.BASE_URL}/{address}/nft"
            params = {
                'chain': self.chain_id,
                'format': 'decimal'
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        logger.error(f"获取 NFT 列表失败: {await response.text()}")
                        return []
                    
                    result = await response.json()
                    
                    # 检查返回的数据格式
                    if isinstance(result, dict) and 'result' in result:
                        nft_list = result['result']
                    elif isinstance(result, list):
                        nft_list = result
                    else:
                        logger.error(f"API 返回的数据格式不正确: {result}")
                        return []
                    
                    # 按合约地址分组
                    collections = {}
                    for nft in nft_list:
                        if not isinstance(nft, dict):
                            logger.warning(f"NFT 数据格式不正确: {nft}")
                            continue
                            
                        contract_address = nft.get('token_address', '').lower()
                        if not contract_address:
                            continue
                            
                        if contract_address not in collections:
                            collections[contract_address] = {
                                'chain': self.chain,
                                'contract_address': contract_address,
                                'name': nft.get('name', ''),
                                'symbol': nft.get('symbol', ''),
                                'contract_type': nft.get('contract_type', 'ERC721'),
                                'logo': nft.get('token_uri', ''),
                                'is_verified': False,
                                'is_spam': False,
                                'is_visible': True,  # 默认显示
                                'floor_price': '0',
                                'floor_price_usd': '0',
                                'floor_price_currency': 'eth',
                                'nft_count': 0
                            }
                            
                        collections[contract_address]['nft_count'] += 1
                    
                    if not collections:
                        logger.debug(f"没有找到任何 NFT 合集")
                        return []
                    
                    # 获取已存在的合集信息
                    existing_collections = await sync_to_async(list)(
                        NFTCollection.objects.filter(
                            chain=self.chain,
                            contract_address__in=list(collections.keys())
                        ).values('contract_address', 'is_verified', 'is_spam', 'is_visible', 'floor_price', 'floor_price_usd')
                    )
                    
                    # 更新合集信息
                    for collection in existing_collections:
                        contract_address = collection['contract_address']
                        if contract_address in collections:
                            collections[contract_address].update({
                                'is_verified': collection['is_verified'],
                                'is_spam': collection['is_spam'],
                                'is_visible': collection['is_visible'],
                                'floor_price': str(collection['floor_price']),
                                'floor_price_usd': str(collection['floor_price_usd'])
                            })
                    
                    # 保存新的合集
                    for collection_data in collections.values():
                        await self._save_collection(collection_data)
                    
                    return list(collections.values())
                    
        except Exception as e:
            logger.error(f"获取 NFT 合集列表失败: {str(e)}")
            return []

    async def transfer_nft(
        self,
        from_address: str,
        to_address: str,
        token_address: str,
        token_id: str,
        private_key: str
    ) -> Dict[str, Any]:
        """转移 NFT
        
        Args:
            from_address: 发送方地址
            to_address: 接收方地址
            token_address: NFT 合约地址
            token_id: NFT Token ID
            private_key: 发送方私钥
            
        Returns:
            Dict: 交易结果
        """
        try:
            # 验证地址
            if not EVMUtils.validate_address(to_address):
                raise InvalidAddressError("无效的接收方地址")
                
            # 获取 NFT 合约
            token_address = Web3.to_checksum_address(token_address)
            nft_contract = self.web3.eth.contract(
                address=token_address,
                abi=ERC721_ABI
            )
            
            # 验证 NFT 所有权
            owner = nft_contract.functions.ownerOf(int(token_id)).call()
            if owner.lower() != from_address.lower():
                raise TransferError("您不是该 NFT 的所有者")
            
            # 构建交易
            from_address = EVMUtils.to_checksum_address(from_address)
            to_address = EVMUtils.to_checksum_address(to_address)
            
            # 获取 nonce
            nonce = self.web3.eth.get_transaction_count(from_address)
            
            # 获取 gas 价格
            gas_price = EVMUtils.get_gas_price(self.chain)
            
            # 构建交易数据
            tx_data = nft_contract.functions.transferFrom(
                from_address,
                to_address,
                int(token_id)
            ).build_transaction({
                'chainId': self.chain_config['chain_id'],
                'gas': 0,  # 稍后估算
                'nonce': nonce,
                'maxFeePerGas': gas_price.get('max_fee', gas_price.get('gas_price')),
                'maxPriorityFeePerGas': gas_price.get('max_priority_fee', 0)
            }) # type: ignore
            
            # 估算 gas
            gas_limit = self.web3.eth.estimate_gas(tx_data)
            tx_data['gas'] = int(gas_limit * 1.1)  # type: ignore # 添加 10% 缓冲
            
            # 签名交易
            signed_tx = self.web3.eth.account.sign_transaction(tx_data, private_key)
            
            # 发送交易
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # 等待交易确认
            receipt = EVMUtils.wait_for_transaction_receipt(self.chain, tx_hash)
            if not receipt:
                raise TransferError("交易确认超时")
                
            if receipt['status'] != 1:
                raise TransferError("交易执行失败")
            
            # 保存交易记录
            await self._save_transaction(
                from_address,
                to_address,
                token_address,
                token_id,
                tx_hash.hex(),
                receipt
            )
            
            return {
                'status': 'success',
                'message': 'NFT 转移成功',
                'data': {
                    'tx_hash': tx_hash.hex(),
                    'block_number': receipt['blockNumber'],
                    'gas_used': receipt['gasUsed'],
                    'from': from_address,
                    'to': to_address,
                    'token_address': token_address,
                    'token_id': token_id
                }
            }
            
        except InvalidAddressError as e:
            logger.error(f"无效地址: {str(e)}")
            return {
                'status': 'error',
                'message': str(e)
            }
        except TransferError as e:
            logger.error(f"转移失败: {str(e)}")
            return {
                'status': 'error',
                'message': str(e)
            }
        except Exception as e:
            logger.error(f"NFT 转移异常: {str(e)}")
            return {
                'status': 'error',
                'message': f"转移失败: {str(e)}"
            }
            
    async def _save_transaction(
        self,
        from_address: str,
        to_address: str,
        token_address: str,
        token_id: str,
        tx_hash: str,
        tx_info: Dict[str, Any]
    ) -> None:
        """保存交易记录
        
        Args:
            from_address: 发送方地址
            to_address: 接收方地址
            token_address: NFT 合约地址
            token_id: NFT Token ID
            tx_hash: 交易哈希
            tx_info: 交易信息
        """
        try:
            # 获取发送方钱包
            sender_wallet = await sync_to_async(Wallet.objects.filter)(
                chain=self.chain,
                address=from_address.lower(),
                is_active=True
            ).first() # type: ignore

            if not sender_wallet:
                logger.error(f"找不到发送方钱包: {from_address}")
                return
            
            # 获取 NFT 合集
            collection = await sync_to_async(NFTCollection.objects.filter(
                chain=self.chain,
                contract_address=token_address.lower()
            ).first)()
            
            # 创建交易记录
            await sync_to_async(Transaction.objects.create)(
                wallet=sender_wallet,
                chain=self.chain,
                tx_hash=tx_hash,
                tx_type='NFT_TRANSFER',
                status='SUCCESS',
                from_address=from_address.lower(),
                to_address=to_address.lower(),
                amount=1,  # NFT 数量固定为 1
                nft_collection=collection,
                nft_token_id=token_id,
                gas_price=tx_info.get('effectiveGasPrice', 0),
                gas_used=tx_info.get('gasUsed', 0),
                block_number=tx_info.get('blockNumber', 0),
                block_timestamp=timezone.now()
            )
            
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
            # 不抛出异常，因为转账已经成功了 