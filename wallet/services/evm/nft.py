"""EVM NFT 服务"""
import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal
import aiohttp
from web3 import Web3
from django.utils import timezone
from asgiref.sync import sync_to_async
import json

from ...models import Wallet, Transaction
from ..evm_config import RPCConfig, MoralisConfig
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
            collection_address: 合集地址（可选）
            
        Returns:
            List[Dict]: NFT 列表
        """
        try:
            # 获取所有 NFT
            url = f"{MoralisConfig.BASE_URL}/{address}/nft"
            params = {
                'chain': self.chain_id,
                'format': 'decimal'
            }
            
            if collection_address:
                params['token_addresses'] = [collection_address]
            
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
                    
                    # 处理 NFT 数据
                    nfts = []
                    for nft in nft_list:
                        if not isinstance(nft, dict):
                            logger.warning(f"NFT 数据格式不正确: {nft}")
                            continue
                            
                        nft_data = {
                            'chain': self.chain,
                            'contract_address': nft.get('token_address', '').lower(),
                            'token_id': nft.get('token_id', ''),
                            'name': nft.get('name', ''),
                            'symbol': nft.get('symbol', ''),
                            'contract_type': nft.get('contract_type', 'ERC721'),
                            'token_uri': nft.get('token_uri', ''),
                            'metadata': nft.get('metadata', {}),
                            'amount': nft.get('amount', '1'),
                            'owner_of': nft.get('owner_of', ''),
                            'block_number_minted': nft.get('block_number_minted', ''),
                            'block_number': nft.get('block_number', ''),
                            'last_token_uri_sync': nft.get('last_token_uri_sync', ''),
                            'last_metadata_sync': nft.get('last_metadata_sync', ''),
                            'is_verified': False,
                            'is_spam': False,
                            'is_visible': True  # 默认显示
                        }
                        
                        nfts.append(nft_data)
                    
                    return nfts
                    
        except Exception as e:
            logger.error(f"获取 NFT 列表失败: {str(e)}")
            return []

    async def get_nft_details(self, token_address: str, token_id: str) -> Dict:
        """获取 NFT 详情
        
        Args:
            token_address: 代币地址
            token_id: 代币 ID
            
        Returns:
            Dict: NFT 详情
        """
        try:
            # 获取 NFT 详情
            url = f"{MoralisConfig.BASE_URL}/nft/{token_address}/{token_id}"
            params = {
                'chain': self.chain_id,
                'format': 'decimal'
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        logger.error(f"获取 NFT 详情失败: {await response.text()}")
                        return {}
                    
                    result = await response.json()
                    
                    # 检查返回的数据格式
                    if not isinstance(result, dict):
                        logger.error(f"API 返回的数据格式不正确: {result}")
                        return {}
                    
                    # 处理 NFT 数据
                    nft_data = {
                        'chain': self.chain,
                        'contract_address': result.get('token_address', '').lower(),
                        'token_id': result.get('token_id', ''),
                        'name': result.get('name', ''),
                        'symbol': result.get('symbol', ''),
                        'contract_type': result.get('contract_type', 'ERC721'),
                        'token_uri': result.get('token_uri', ''),
                        'metadata': result.get('metadata', {}),
                        'amount': result.get('amount', '1'),
                        'owner_of': result.get('owner_of', ''),
                        'block_number_minted': result.get('block_number_minted', ''),
                        'block_number': result.get('block_number', ''),
                        'last_token_uri_sync': result.get('last_token_uri_sync', ''),
                        'last_metadata_sync': result.get('last_metadata_sync', ''),
                        'is_verified': False,
                        'is_spam': False,
                        'is_visible': True  # 默认显示
                    }
                    
                    return nft_data
                    
        except Exception as e:
            logger.error(f"获取 NFT 详情失败: {str(e)}")
            return {}

    async def _get_nft_owner(self, token_address: str, token_id: str) -> str:
        """获取 NFT 所有者
        
        Args:
            token_address: 代币地址
            token_id: 代币 ID
            
        Returns:
            str: 所有者地址
        """
        try:
            # 获取 NFT 所有者
            url = f"{MoralisConfig.BASE_URL}/nft/{token_address}/{token_id}/owners"
            params = {
                'chain': self.chain_id,
                'format': 'decimal'
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        logger.error(f"获取 NFT 所有者失败: {await response.text()}")
                        return ''
                    
                    result = await response.json()
                    
                    # 检查返回的数据格式
                    if not isinstance(result, dict) or 'result' not in result:
                        logger.error(f"API 返回的数据格式不正确: {result}")
                        return ''
                    
                    owners = result['result']
                    if not owners:
                        return ''
                    
                    return owners[0].get('owner_of', '')
                    
        except Exception as e:
            logger.error(f"获取 NFT 所有者失败: {str(e)}")
            return ''

    async def _get_last_transfer(self, token_address: str, token_id: str) -> Dict:
        """获取最后一次转账记录
        
        Args:
            token_address: 代币地址
            token_id: 代币 ID
            
        Returns:
            Dict: 转账记录
        """
        try:
            # 获取转账记录
            url = f"{MoralisConfig.BASE_URL}/nft/{token_address}/{token_id}/transfers"
            params = {
                'chain': self.chain_id,
                'format': 'decimal',
                'limit': 1
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        logger.error(f"获取转账记录失败: {await response.text()}")
                        return {}
                    
                    result = await response.json()
                    
                    # 检查返回的数据格式
                    if not isinstance(result, dict) or 'result' not in result:
                        logger.error(f"API 返回的数据格式不正确: {result}")
                        return {}
                    
                    transfers = result['result']
                    if not transfers:
                        return {}
                    
                    return transfers[0]
                    
        except Exception as e:
            logger.error(f"获取转账记录失败: {str(e)}")
            return {}

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
            from_address: 发送地址
            to_address: 接收地址
            token_address: 代币地址
            token_id: 代币 ID
            private_key: 私钥
            
        Returns:
            Dict[str, Any]: 交易信息
        """
        try:
            # 检查地址格式
            if not Web3.is_address(from_address):
                raise InvalidAddressError(f"无效的发送地址: {from_address}")
            if not Web3.is_address(to_address):
                raise InvalidAddressError(f"无效的接收地址: {to_address}")
            if not Web3.is_address(token_address):
                raise InvalidAddressError(f"无效的代币地址: {token_address}")
            
            # 获取合约实例
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC721_ABI
            )
            
            # 构建交易
            tx = contract.functions.transferFrom(
                Web3.to_checksum_address(from_address),
                Web3.to_checksum_address(to_address),
                int(token_id)
            ).build_transaction({
                'chainId': self.chain_config['chain_id'],
                'gas': 200000,
                'gasPrice': self.web3.eth.gas_price,
                'nonce': self.web3.eth.get_transaction_count(from_address),
            })
            
            # 签名交易
            signed_tx = self.web3.eth.account.sign_transaction(tx, private_key)
            
            # 发送交易
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # 等待交易确认
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            # 记录交易
            await self._save_transaction(
                from_address=from_address,
                to_address=to_address,
                token_address=token_address,
                token_id=token_id,
                tx_hash=tx_hash.hex(),
                tx_info={
                    'block_number': receipt.blockNumber,
                    'gas_used': receipt.gasUsed,
                    'status': receipt.status == 1
                }
            )
            
            return {
                'tx_hash': tx_hash.hex(),
                'status': receipt.status == 1,
                'block_number': receipt.blockNumber,
                'gas_used': receipt.gasUsed
            }
            
        except Exception as e:
            logger.error(f"转移 NFT 失败: {str(e)}")
            raise TransferError(f"转移 NFT 失败: {str(e)}")

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
            from_address: 发送地址
            to_address: 接收地址
            token_address: 代币地址
            token_id: 代币 ID
            tx_hash: 交易哈希
            tx_info: 交易信息
        """
        try:
            # 获取钱包
            wallet = await sync_to_async(Wallet.objects.get)(
                address=from_address,
                chain=self.chain
            )
            
            # 创建交易记录
            await sync_to_async(Transaction.objects.create)(
                wallet=wallet,
                tx_hash=tx_hash,
                tx_type='TRANSFER',
                from_address=from_address,
                to_address=to_address,
                amount=1,  # NFT 数量为 1
                token=None,  # NFT 不使用代币模型
                token_info={
                    'token_address': token_address,
                    'token_id': token_id
                },
                fee=tx_info.get('gas_used', 0),
                status=tx_info.get('status', True),
                block_number=tx_info.get('block_number', 0),
                block_timestamp=timezone.now()
            )
            
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
            raise