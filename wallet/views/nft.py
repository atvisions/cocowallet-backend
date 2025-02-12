from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
import logging
from asgiref.sync import async_to_sync, sync_to_async
from functools import wraps
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.permissions import AllowAny
from rest_framework.parsers import JSONParser
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
import aiohttp
from typing import Optional

from ..models import Wallet
from ..serializers import WalletSerializer
from ..api_config import HeliusConfig

logger = logging.getLogger(__name__)

def async_to_sync_api(func):
    """装饰器：将异步API转换为同步API"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        return async_to_sync(func)(*args, **kwargs)
    return wrapper

class SolanaNFTViewSet(viewsets.ModelViewSet):
    """Solana NFT视图集"""
    serializer_class = WalletSerializer
    permission_classes = [AllowAny]
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    parser_classes = [JSONParser]

    async def get_wallet_async(self, wallet_id: int, device_id: Optional[str] = None) -> Wallet:
        """异步获取钱包对象"""
        try:
            # 使用sync_to_async包装数据库查询
            get_wallet = sync_to_async(Wallet.objects.filter(id=wallet_id).first)
            wallet = await get_wallet()
            
            if not wallet:
                logger.error(f"找不到钱包，ID: {wallet_id}")
                raise ObjectDoesNotExist(f"找不到ID为{wallet_id}的钱包")
            
            # 验证device_id
            if device_id and wallet.device_id != device_id:
                logger.error(f"设备ID不匹配，钱包device_id: {wallet.device_id}, 请求device_id: {device_id}")
                raise ObjectDoesNotExist("无权访问该钱包")
                
            logger.debug(f"成功获取钱包: {wallet.address}")
            return wallet
            
        except Exception as e:
            logger.error(f"获取钱包时出错: {str(e)}")
            raise

    @action(detail=False, methods=['get'], url_path=r'collections/(?P<wallet_id>[^/.]+)')
    @async_to_sync_api
    async def get_nft_collections(self, request, wallet_id=None):
        """获取钱包的 NFT 合集列表"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id)
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            logger.debug(f"开始获取NFT合集数据，钱包地址: {wallet.address}")
            
            # 使用 Helius API 获取 NFT 数据
            payload = {
                "jsonrpc": "2.0",
                "id": "my-id",
                "method": HeliusConfig.GET_ASSETS_BY_OWNER,
                "params": {
                    "ownerAddress": wallet.address,
                    "page": 1,
                    "limit": 1000
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(HeliusConfig.get_rpc_url(), json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"获取NFT列表失败: HTTP {response.status}, 响应: {error_text}")
                        return Response({
                            'status': 'error',
                            'message': f'获取NFT列表失败: {error_text}'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    data = await response.json()
                    if 'error' in data:
                        logger.error(f"API返回错误: {data['error']}")
                        return Response({
                            'status': 'error',
                            'message': f"获取NFT数据失败: {data['error']}"
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    items = data.get('result', {}).get('items', [])
                    
                    # 按合集分组NFTs
                    collections = {}
                    
                    for item in items:
                        try:
                            # 获取合集信息
                            grouping = item.get('grouping', [])
                            collection_name = None
                            collection_address = None
                            collection_symbol = None
                            
                            # 尝试从grouping中获取合集信息
                            for group in grouping:
                                if group.get('group_key') == 'collection':
                                    collection_name = group.get('group_value')
                                    collection_address = group.get('group_value')
                                    break
                            
                            # 获取symbol
                            content = item.get('content', {})
                            metadata = content.get('metadata', {})
                            collection_symbol = metadata.get('symbol', '')
                            
                            # 如果没有合集名称，使用symbol
                            if not collection_name:
                                collection_name = collection_symbol or 'Unknown'
                                collection_address = collection_symbol or 'Unknown'
                            
                            if collection_address not in collections:
                                collections[collection_address] = {
                                    'name': collection_name,
                                    'symbol': collection_symbol or collection_name,
                                    'address': collection_address,
                                    'nft_count': 0,
                                    'image_url': None,
                                    'first_mint': None
                                }
                            
                            # 获取NFT信息
                            mint = item.get('id', '')
                            
                            # 获取图片URL
                            image_url = None
                            files = content.get('files', [])
                            if files and isinstance(files, list) and len(files) > 0:
                                image_url = files[0].get('uri', '')
                            
                            if not image_url:
                                image_url = metadata.get('image', '')
                            
                            collections[collection_address]['nft_count'] += 1
                            
                            # 记录第一个NFT的mint和图片
                            if not collections[collection_address]['first_mint']:
                                collections[collection_address]['first_mint'] = mint
                                collections[collection_address]['image_url'] = image_url
                            
                        except Exception as e:
                            logger.error(f"处理NFT数据时出错: {str(e)}")
                            continue
                    
                    # 转换为列表并排序
                    collection_list = [{
                        'name': data['name'],
                        'symbol': data['symbol'],
                        'address': data['address'],
                        'nft_count': data['nft_count'],
                        'image_url': data['image_url']
                    } for data in collections.values()]
                    
                    collection_list.sort(key=lambda x: x['nft_count'], reverse=True)
                    
                    return Response({
                        'status': 'success',
                        'data': collection_list
                    })
                    
        except Exception as e:
            logger.error(f"获取NFT合集列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取NFT合集列表失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path=r'collections/(?P<wallet_id>[^/.]+)/(?P<collection_symbol>[^/.]+)/nfts')
    @async_to_sync_api
    async def get_collection_nfts(self, request, wallet_id=None, collection_symbol=None):
        """获取NFT集合中的NFTs"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            if not collection_symbol:
                return Response({
                    'status': 'error',
                    'message': '缺少collection_symbol参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id)
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            logger.debug(f"开始获取NFT集合数据，钱包地址: {wallet.address}, collection_symbol: {collection_symbol}")
            
            # 使用 Helius API 获取 NFT 数据
            payload = {
                "jsonrpc": "2.0",
                "id": "my-id",
                "method": HeliusConfig.GET_ASSETS_BY_OWNER,
                "params": {
                    "ownerAddress": wallet.address,
                    "page": 1,
                    "limit": 1000
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(HeliusConfig.get_rpc_url(), json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"获取NFT列表失败: HTTP {response.status}, 响应: {error_text}")
                        return Response({
                            'status': 'error',
                            'message': f'获取NFT列表失败: {error_text}'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    data = await response.json()
                    if 'error' in data:
                        logger.error(f"API返回错误: {data['error']}")
                        return Response({
                            'status': 'error',
                            'message': f"获取NFT数据失败: {data['error']}"
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    items = data.get('result', {}).get('items', [])
                    
                    # 过滤指定collection的NFTs
                    filtered_nfts = []
                    collection_info = {}
                    
                    for item in items:
                        try:
                            # 获取合集信息
                            grouping = item.get('grouping', [])
                            item_collection_symbol = None
                            
                            # 从metadata中获取symbol
                            content = item.get('content', {})
                            metadata = content.get('metadata', {})
                            item_collection_symbol = metadata.get('symbol', '')
                            
                            # 如果symbol不匹配，跳过
                            if not item_collection_symbol or not collection_symbol or \
                               item_collection_symbol.upper() != collection_symbol.upper():
                                continue
                            
                            # 获取NFT信息
                            mint = item.get('id', '')
                            name = metadata.get('name', '')
                            description = metadata.get('description', '')
                            
                            # 获取图片URL
                            image_url = None
                            files = content.get('files', [])
                            if files and isinstance(files, list) and len(files) > 0:
                                image_url = files[0].get('uri', '')
                            
                            if not image_url:
                                image_url = metadata.get('image', '')
                            
                            # 处理属性
                            attributes = []
                            raw_attributes = metadata.get('attributes', [])
                            if isinstance(raw_attributes, list):
                                attributes = raw_attributes
                            elif isinstance(raw_attributes, dict):
                                attributes = [{'trait_type': k, 'value': v} for k, v in raw_attributes.items()]
                            
                            nft_info = {
                                'mint': mint,
                                'name': name,
                                'symbol': item_collection_symbol,
                                'description': description,
                                'image_url': image_url,
                                'attributes': attributes,
                                'owner': wallet.address
                            }
                            
                            filtered_nfts.append(nft_info)
                            
                            # 更新合集信息
                            if not collection_info:
                                collection_info = {
                                    'name': metadata.get('collection', {}).get('name', '') or item_collection_symbol,
                                    'symbol': item_collection_symbol,
                                    'description': metadata.get('collection', {}).get('description', ''),
                                    'image_url': metadata.get('collection', {}).get('image', '')
                                }
                            
                        except Exception as e:
                            logger.error(f"处理NFT数据时出错: {str(e)}")
                            continue

                    if not filtered_nfts:
                        logger.warning(f"未找到匹配的NFTs，collection_symbol: {collection_symbol}")
                        return Response({
                            'status': 'success',
                            'data': {
                                'collection': collection_info,
                                'nfts': []
                            }
                        })

                    return Response({
                        'status': 'success',
                        'data': {
                            'collection': collection_info,
                            'nfts': filtered_nfts
                        }
                    })

        except Exception as e:
            logger.error(f"获取NFT集合数据时出错: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path=r'(?P<wallet_id>[^/.]+)/(?P<mint_address>[^/.]+)/detail')
    @async_to_sync_api
    async def get_nft_detail(self, request, wallet_id=None, mint_address=None):
        """获取NFT详情"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id)
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            logger.debug(f"开始获取NFT详情，钱包地址: {wallet.address}, mint_address: {mint_address}")
            
            # 使用 Helius RPC API 获取 NFT 数据
            payload = {
                "jsonrpc": "2.0",
                "id": "my-id",
                "method": HeliusConfig.GET_ASSET,
                "params": {
                    "id": mint_address
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(HeliusConfig.get_rpc_url(), json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"获取NFT详情失败: HTTP {response.status}, 响应: {error_text}")
                        return Response({
                            'status': 'error',
                            'message': f'获取NFT详情失败: {error_text}'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    data = await response.json()
                    if 'error' in data:
                        logger.error(f"API返回错误: {data['error']}")
                        return Response({
                            'status': 'error',
                            'message': f"获取NFT数据失败: {data['error']}"
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    nft_data = data.get('result', {})
                    if not nft_data:
                        return Response({
                            'status': 'error',
                            'message': '未找到NFT数据'
                        }, status=status.HTTP_404_NOT_FOUND)
                    
                    try:
                        # 获取NFT基本信息
                        content = nft_data.get('content', {})
                        metadata = content.get('metadata', {})
                        
                        # 获取图片URL
                        image_url = None
                        files = content.get('files', [])
                        if files and isinstance(files, list) and len(files) > 0:
                            image_url = files[0].get('uri', '')
                        
                        if not image_url:
                            image_url = metadata.get('image', '')
                        
                        # 处理属性
                        attributes = []
                        raw_attributes = metadata.get('attributes', [])
                        if isinstance(raw_attributes, list):
                            attributes = raw_attributes
                        elif isinstance(raw_attributes, dict):
                            attributes = [{'trait_type': k, 'value': v} for k, v in raw_attributes.items()]
                        
                        # 获取合集信息
                        grouping = nft_data.get('grouping', [])
                        collection_info = {
                            'name': '',
                            'family': ''
                        }
                        
                        for group in grouping:
                            if group.get('group_key') == 'collection':
                                collection_info['name'] = group.get('group_value', '')
                                collection_info['family'] = group.get('collection_id', '')
                                break
                        
                        # 如果没有合集名称，使用symbol
                        if not collection_info['name']:
                            collection_info['name'] = metadata.get('symbol', '')
                        
                        # 构建返回数据
                        nft_detail = {
                            'mint': mint_address,
                            'name': metadata.get('name', ''),
                            'symbol': metadata.get('symbol', ''),
                            'image': image_url,
                            'animation_url': metadata.get('animation_url', ''),
                            'external_url': metadata.get('external_url', ''),
                            'description': metadata.get('description', ''),
                            'attributes': attributes,
                            'properties': metadata.get('properties', {}),
                            'collection': collection_info,
                            'metaplex': {
                                'metadataUri': content.get('json_uri', ''),
                                'updateAuthority': nft_data.get('authorities', [{}])[0].get('address', ''),
                                'sellerFeeBasisPoints': nft_data.get('royalty', {}).get('basis_points', 0),
                                'primarySaleHappened': nft_data.get('royalty', {}).get('primary_sale_happened', False),
                                'isMutable': True  # Helius API 目前不提供这个信息
                            }
                        }
                        
                        return Response({
                            'status': 'success',
                            'data': nft_detail
                        })
                        
                    except Exception as e:
                        logger.error(f"处理NFT数据时出错: {str(e)}")
                        return Response({
                            'status': 'error',
                            'message': f'处理NFT数据时出错: {str(e)}'
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                        
        except Exception as e:
            logger.error(f"获取NFT详情时出错: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR) 