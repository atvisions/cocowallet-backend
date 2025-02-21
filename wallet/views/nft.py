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
from rest_framework.views import APIView
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from ..models import Wallet, NFTCollection
from ..serializers import WalletSerializer
from ..api_config import HeliusConfig
from ..services.factory import ChainServiceFactory
from ..exceptions import InvalidAddressError, TransferError, WalletNotFoundError
from ..services.evm.nft import EVMNFTService
from ..services.evm.utils import EVMUtils
from ..decorators import verify_payment_password

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
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore  
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
                    
                    # 获取隐藏的合集列表
                    hidden_collections = await sync_to_async(list)(
                        NFTCollection.objects.filter(
                            chain='SOL',
                            is_visible=False
                        ).values_list('symbol', flat=True)
                    )
                    
                    # 保存合集信息到数据库
                    for collection_data in collections.values():
                        try:
                            # 检查合集是否已存在
                            collection = await sync_to_async(NFTCollection.objects.filter(
                                chain='SOL',
                                symbol=collection_data['symbol']
                            ).first)()
                            
                            if collection:
                                # 更新现有合集
                                collection.name = collection_data['name']
                                collection.contract_address = collection_data['address']
                                collection.logo = collection_data['image_url']
                                await sync_to_async(collection.save)()
                            else:
                                # 创建新合集
                                collection = NFTCollection(
                                    chain='SOL',
                                    name=collection_data['name'],
                                    symbol=collection_data['symbol'],
                                    contract_address=collection_data['address'],
                                    logo=collection_data['image_url'],
                                    is_visible=collection_data['symbol'] not in hidden_collections
                                )
                                await sync_to_async(collection.save)()
                                
                        except Exception as e:
                            logger.error(f"保存合集信息失败: {str(e)}")
                            continue
                    
                    # 转换为列表并过滤掉隐藏的合集
                    collection_list = [{
                        'name': data['name'],
                        'symbol': data['symbol'],
                        'address': data['address'],
                        'nft_count': data['nft_count'],
                        'image_url': data['image_url']
                    } for data in collections.values() 
                      if data['symbol'] not in hidden_collections]
                    
                    # 按NFT数量排序
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
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
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
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
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

    @swagger_auto_schema(
        operation_summary="转移 NFT",
        operation_description="将 NFT 从一个地址转移到另一个地址",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['to_address', 'token_address', 'token_id', 'payment_password'],
            properties={
                'to_address': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='接收方地址'
                ),
                'token_address': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='NFT 合约地址'
                ),
                'token_id': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='NFT Token ID'
                ),
                'payment_password': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='支付密码'
                )
            }
        ),
        manual_parameters=[
            openapi.Parameter(
                'device_id',
                openapi.IN_QUERY,
                description='设备ID',
                type=openapi.TYPE_STRING,
                required=True
            )
        ],
        responses={
            200: "转账成功",
            400: "参数错误",
            401: "未授权",
            500: "服务器错误"
        }
    )
    @action(detail=False, methods=['post'], url_path=r'transfer/(?P<wallet_id>[^/.]+)')
    @async_to_sync_api
    @verify_payment_password()
    async def transfer_nft(self, request, wallet_id=None):
        """转移 NFT"""
        try:
            device_id = request.data.get('device_id')
            to_address = request.data.get('to_address')
            token_address = request.data.get('token_address')
            token_id = request.data.get('token_id')
            payment_password = request.data.get('payment_password')
            
            if not all([device_id, to_address, token_address, token_id]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(wallet_id, device_id)
            
            # 设置支付密码用于解密私钥
            wallet.payment_password = payment_password
            
            try:
                # 获取私钥
                private_key = wallet.decrypt_private_key()
            except Exception as e:
                logger.error(f"解密私钥失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'解密私钥失败: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取 NFT 服务
            nft_service = ChainServiceFactory.get_nft_service(wallet.chain)
            if not nft_service:
                return Response({
                    'status': 'error',
                    'message': 'NFT服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 执行转账
            try:
                result = await nft_service.transfer_nft(
                    from_address=wallet.address,
                    to_address=to_address,
                    token_address=token_address,
                    token_id=token_id,
                    private_key=private_key
                )
                
                if result.get('success'):
                    return Response({
                        'status': 'success',
                        'data': {
                            'transaction_hash': result.get('transaction_hash'),
                            'block_hash': result.get('block_hash'),
                            'fee': result.get('fee')
                        }
                    })
                else:
                    return Response({
                        'status': 'error',
                        'message': result.get('error') or 'NFT转账失败'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
            except Exception as e:
                logger.error(f"执行NFT转账时出错: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'NFT转账失败: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.error(f"NFT转账失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path=r'collections/(?P<wallet_id>[^/.]+)/toggle-visibility')
    @async_to_sync_api
    async def toggle_collection_visibility(self, request, wallet_id=None):
        """切换NFT合集的显示状态"""
        try:
            # 获取请求参数
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            collection_symbol = request.data.get('collection_symbol')
            if not collection_symbol:
                return Response({
                    'status': 'error',
                    'message': '缺少collection_symbol参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 查找并更新合集
            try:
                collection = await sync_to_async(NFTCollection.objects.get)(
                    chain='SOL',
                    symbol=collection_symbol
                )
                
                # 切换显示状态
                collection.is_visible = not collection.is_visible
                await sync_to_async(collection.save)()

                return Response({
                    'status': 'success',
                    'message': '更新成功',
                    'data': {
                        'collection_symbol': collection.symbol,
                        'is_visible': collection.is_visible
                    }
                })

            except NFTCollection.DoesNotExist:
                # 如果合集不存在，创建一个新的合集记录
                collection = NFTCollection(
                    chain='SOL',
                    symbol=collection_symbol,
                    is_visible=False  # 默认设置为不可见
                )
                await sync_to_async(collection.save)()
                
                return Response({
                    'status': 'success',
                    'message': '创建并更新成功',
                    'data': {
                        'collection_symbol': collection.symbol,
                        'is_visible': collection.is_visible
                    }
                })

            except Exception as e:
                logger.error(f"更新合集显示状态失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': '更新合集显示状态失败'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            logger.error(f"切换合集显示状态失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '切换合集显示状态失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path=r'collections/(?P<wallet_id>[^/.]+)/hidden')
    @async_to_sync_api
    async def get_hidden_collections(self, request, wallet_id=None):
        """获取已隐藏的 NFT 合集列表"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少设备ID'
                }, status=400)
            
            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=400)
            
            # 获取隐藏的合集
            hidden_collections = await sync_to_async(list)(
                NFTCollection.objects.filter(
                    chain='SOL',
                    is_visible=False
                ).values(
                    'symbol',
                    'name',
                    'logo',
                    'is_verified',
                    'is_spam',
                    'floor_price',
                    'floor_price_usd'
                )
            )
            
            return Response({
                'status': 'success',
                'message': '获取成功',
                'data': hidden_collections
            })
            
        except Exception as e:
            logger.error(f"获取隐藏的 NFT 合集列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取失败: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['get'], url_path=r'collections/(?P<wallet_id>[^/.]+)/manage')
    @async_to_sync_api
    async def manage_nft_collections(self, request, wallet_id=None):
        """获取所有 NFT 合集（包括不可见的）"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少设备ID'
                }, status=400)
            
            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=400)
            
            # 获取钱包的所有 NFT 合集
            nft_service = ChainServiceFactory.get_nft_service('SOL')
            collections = await nft_service.get_all_nft_collections(wallet.address)
            
            # 获取合集的显示状态
            collection_symbols = [c['symbol'] for c in collections]
            db_collections = await sync_to_async(list)(
                NFTCollection.objects.filter(
                    chain='SOL',
                    symbol__in=collection_symbols
                ).values('symbol', 'is_visible')
            )
            
            # 创建显示状态映射
            visibility_map = {c['symbol']: c['is_visible'] for c in db_collections}
            
            # 更新合集的显示状态
            for collection in collections:
                collection['is_visible'] = visibility_map.get(collection['symbol'], True)
            
            return Response({
                'status': 'success',
                'message': '获取成功',
                'data': collections
            })
            
        except Exception as e:
            logger.error(f"获取 NFT 合集列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取 NFT 合集列表失败'
            }, status=500)

class NFTTransferView(APIView):
    """NFT 转账视图"""

    @swagger_auto_schema(
        operation_summary="转移 NFT",
        operation_description="将 NFT 从一个地址转移到另一个地址",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['to_address', 'token_address', 'token_id', 'payment_password'],
            properties={
                'to_address': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='接收方地址'
                ),
                'token_address': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='NFT 合约地址'
                ),
                'token_id': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='NFT Token ID'
                ),
                'payment_password': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='支付密码'
                )
            }
        ),
        manual_parameters=[
            openapi.Parameter(
                'device_id',
                openapi.IN_QUERY,
                description='设备ID',
                type=openapi.TYPE_STRING,
                required=True
            )
        ],
        responses={
            200: "转账成功",
            400: "参数错误",
            401: "未授权",
            500: "服务器错误"
        }
    )
    async def post(self, request, wallet_id):
        """处理 NFT 转账请求"""
        try:
            # 获取钱包
            wallet = await Wallet.objects.aget(id=wallet_id, is_active=True)
            
            # 获取请求参数
            to_address = request.data.get('to_address')
            nft_address = request.data.get('nft_address')
            payment_password = request.data.get('payment_password')
            
            # 参数验证
            if not to_address or not nft_address or not payment_password:
                return Response(
                    {"error": "缺少必要参数"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 获取 NFT 服务
            nft_service = ChainServiceFactory.get_nft_service(wallet.chain)
            if not nft_service:
                return Response(
                    {"error": f"不支持的链: {wallet.chain}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 设置支付密码
            wallet.payment_password = payment_password
            
            # 执行转账
            result = await nft_service.transfer_nft( # type: ignore
                from_address=wallet.address,
                to_address=to_address,
                nft_address=nft_address, # type: ignore
                private_key=wallet.decrypt_private_key()
            )
            
            return Response(result)
            
        except Wallet.DoesNotExist:
            return Response(
                {"error": "钱包不存在"},
                status=status.HTTP_404_NOT_FOUND
            )
        except InvalidAddressError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except TransferError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"NFT 转账失败: {str(e)}")
            return Response(
                {"error": "服务器错误"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class EVMNFTViewSet(viewsets.ModelViewSet):
    """EVM NFT视图集"""
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
                
            # 验证是否是EVM链
            if wallet.chain not in ['ETH', 'BSC', 'POLYGON', 'AVAX', 'BASE']:
                logger.error(f"不支持的链类型: {wallet.chain}")
                raise ValueError("该接口仅支持EVM链钱包")
                
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
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
            
            # 初始化 NFT 服务
            nft_service = EVMNFTService(wallet.chain)
            
            # 获取 NFT 合集列表
            collections = await nft_service.get_nft_collections(wallet.address)
            
            return Response({
                'status': 'success',
                'data': collections
            })
            
        except ValueError as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"获取NFT合集列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取NFT合集列表失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path=r'(?P<wallet_id>[^/.]+)/list')
    @async_to_sync_api
    async def get_collection_nfts(self, request, wallet_id=None):
        """获取NFT集合中的NFTs"""
        try:
            device_id = request.query_params.get('device_id')
            collection_address = request.query_params.get('collection_address')
            
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            if not collection_address:
                return Response({
                    'status': 'error',
                    'message': '缺少collection_address参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
            
            # 初始化 NFT 服务
            nft_service = EVMNFTService(wallet.chain)
            
            # 获取 NFT 列表
            nfts = await nft_service.get_nfts(wallet.address, collection_address)
            
            return Response({
                'status': 'success',
                'data': nfts
            })
            
        except ValueError as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"获取NFT列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取NFT列表失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path=r'(?P<wallet_id>[^/.]+)/details')
    @async_to_sync_api
    async def get_nft_details(self, request, wallet_id=None):
        """获取 NFT 详情"""
        try:
            device_id = request.query_params.get('device_id')
            token_address = request.query_params.get('token_address')
            token_id = request.query_params.get('token_id')
            
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=400)
            
            if not token_address:
                return Response({
                    'status': 'error',
                    'message': '缺少token_address参数'
                }, status=400)
            
            if not token_id:
                return Response({
                    'status': 'error',
                    'message': '缺少token_id参数'
                }, status=400)
            
            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
            
            # 初始化 NFT 服务
            nft_service = EVMNFTService(wallet.chain)
            
            # 获取 NFT 详情
            nft_details = await nft_service.get_nft_details(token_address, token_id)
            
            # 如果没有获取到数据，返回空对象
            if not nft_details:
                return Response({
                    'status': 'success',
                    'message': '获取NFT详情成功',
                    'data': {}
                })
            
            # 格式化返回数据
            formatted_data = {
                'token_address': token_address,
                'token_id': token_id,
                'contract_type': nft_details.get('contract_type', 'ERC721'),
                'name': nft_details.get('name', ''),
                'description': nft_details.get('description', ''),
                'image': nft_details.get('image', ''),
                'animation_url': nft_details.get('animation_url'),
                'attributes': [
                    {
                        'trait_type': attr.get('trait_type', ''),
                        'value': attr.get('value', ''),
                        'display_type': attr.get('display_type'),
                        'max_value': attr.get('max_value'),
                        'trait_count': attr.get('trait_count', 0),
                        'order': attr.get('order'),
                        'rarity_label': attr.get('rarity_label'),
                        'count': attr.get('count'),
                        'percentage': attr.get('percentage')
                    }
                    for attr in nft_details.get('attributes', [])
                ],
                'owner_of': nft_details.get('owner_of', ''),
                'token_uri': nft_details.get('token_uri', ''),
                'amount': nft_details.get('amount', '1'),
                'block_number_minted': nft_details.get('block_number_minted'),
                'last_token_uri_sync': nft_details.get('last_token_uri_sync'),
                'last_metadata_sync': nft_details.get('last_metadata_sync'),
                'media_collection': nft_details.get('media_collection', {}),
                'media_items': nft_details.get('media_items', []),
                'media_status': nft_details.get('media_status', 'host_unavailable')
            }
            
            return Response({
                'status': 'success',
                'message': '获取NFT详情成功',
                'data': formatted_data
            })
            
        except ValueError as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=400)
        except Exception as e:
            logger.error(f"获取NFT详情失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取NFT详情失败'
            }, status=500)

    @action(detail=False, methods=['post'], url_path=r'collections/(?P<wallet_id>[^/.]+)/toggle-visibility')
    @async_to_sync_api
    async def toggle_collection_visibility(self, request, wallet_id=None):
        """切换 NFT 合集显示状态"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少设备ID'
                }, status=400)
                
            contract_address = request.data.get('contract_address')
            if not contract_address:
                return Response({
                    'status': 'error',
                    'message': '缺少合约地址'
                }, status=400)
                
            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
            
            # 查找并更新合集
            try:
                collection = await sync_to_async(NFTCollection.objects.get)(
                    chain=wallet.chain,
                    contract_address=contract_address
                )
                
                # 切换显示状态
                collection.is_visible = not collection.is_visible
                await sync_to_async(collection.save)()
                
                return Response({
                    'status': 'success',
                    'message': '更新成功',
                    'data': {
                        'contract_address': collection.contract_address,
                        'is_visible': collection.is_visible
                    }
                })
            except NFTCollection.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': '找不到指定的合集'
                }, status=404)
            except Exception as e:
                logger.error(f"更新合集显示状态失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': '更新合集显示状态失败'
                }, status=500)
                
        except Exception as e:
            logger.error(f"切换合集显示状态失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '切换合集显示状态失败'
            }, status=500)
            
    @action(detail=False, methods=['get'], url_path=r'collections/(?P<wallet_id>[^/.]+)/hidden')
    @async_to_sync_api
    async def get_hidden_collections(self, request, wallet_id=None):
        """获取已隐藏的 NFT 合集列表"""
        try:
            # 获取请求参数
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少设备ID'
                }, status=400)
                
            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
            
            # 获取隐藏的合集
            hidden_collections = await sync_to_async(list)(
                NFTCollection.objects.filter(
                    chain=wallet.chain,
                    is_visible=False
                ).values(
                    'contract_address',
                    'name',
                    'logo',
                    'is_verified',
                    'is_spam'
                )
            )
            
            return Response({
                'status': 'success',
                'message': '获取成功',
                'data': hidden_collections
            })
            
        except Exception as e:
            logger.error(f"获取隐藏的 NFT 合集列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取失败: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['get'], url_path=r'collections/(?P<wallet_id>[^/.]+)/manage')
    @async_to_sync_api
    async def manage_nft_collections(self, request, wallet_id=None):
        """获取所有 NFT 合集（包括不可见的）"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少设备ID'
                }, status=400)
                
            # 验证钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore
            logger.debug(f"成功获取钱包: {wallet.address}")
            
            # 初始化 NFT 服务
            nft_service = EVMNFTService(wallet.chain)
            
            # 获取所有合集（包括不可见的）
            collections = await nft_service.get_all_nft_collections(wallet.address)
            
            return Response({
                'status': 'success',
                'message': '获取成功',
                'data': collections
            })
            
        except Exception as e:
            logger.error(f"获取 NFT 合集列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取 NFT 合集列表失败'
            }, status=500)

    @swagger_auto_schema(
        operation_summary="转移 NFT",
        operation_description="将 NFT 从一个地址转移到另一个地址",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['to_address', 'token_address', 'token_id', 'payment_password'],
            properties={
                'to_address': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='接收方地址'
                ),
                'token_address': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='NFT 合约地址'
                ),
                'token_id': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='NFT Token ID'
                ),
                'payment_password': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='支付密码'
                )
            }
        ),
        manual_parameters=[
            openapi.Parameter(
                'device_id',
                openapi.IN_QUERY,
                description='设备ID',
                type=openapi.TYPE_STRING,
                required=True
            )
        ],
        responses={
            200: "转账成功",
            400: "参数错误",
            401: "未授权",
            500: "服务器错误"
        }
    )
    @action(detail=False, methods=['post'], url_path=r'transfer/(?P<wallet_id>[^/.]+)')
    @async_to_sync_api
    async def transfer_nft(self, request, wallet_id=None):
        """处理 NFT 转账请求"""
        try:
            # 验证设备ID
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            # 获取请求参数
            to_address = request.data.get('to_address')
            token_address = request.data.get('token_address')
            token_id = request.data.get('token_id')
            payment_password = request.data.get('payment_password')
            
            # 参数验证
            if not all([to_address, token_address, token_id, payment_password]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取钱包
            wallet = await self.get_wallet_async(int(wallet_id), device_id) # type: ignore      
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持EVM链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 验证支付密码
            if not await sync_to_async(wallet.check_payment_password)(payment_password):
                return Response({
                    'status': 'error',
                    'message': '支付密码错误'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            # 设置支付密码
            wallet.payment_password = payment_password
            
            # 解密私钥
            try:
                private_key = wallet.decrypt_private_key()
            except Exception as e:
                logger.error(f"解密私钥失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': '解密私钥失败'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # 初始化 NFT 服务
            nft_service = EVMNFTService(wallet.chain)
            
            # 执行转账
            result = await nft_service.transfer_nft(
                from_address=wallet.address,
                to_address=to_address,
                token_address=token_address,
                token_id=token_id,
                private_key=private_key
            )
            
            if result['status'] == 'error':
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
            
            return Response(result)
            
        except WalletNotFoundError:
            return Response({
                'status': 'error',
                'message': '钱包不存在'
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            logger.error(f"NFT 转账失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'NFT 转账失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR) 