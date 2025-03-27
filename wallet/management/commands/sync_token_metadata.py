from django.core.management.base import BaseCommand
import aiohttp
import asyncio
import json
import logging
from datetime import datetime
from django.utils import timezone
from wallet.models import Token, TokenCategory
from django.core.cache import cache
from asgiref.sync import sync_to_async
from django.conf import settings
from wallet.services import ChainServiceFactory

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '从外部源同步代币元数据'

    def __init__(self):
        super().__init__()
        self.cache_key = 'token_metadata_sync_status'

    def add_arguments(self, parser):
        parser.add_argument(
            '--async-mode',
            action='store_true',
            help='在异步模式下运行',
        )
        parser.add_argument(
            '--source',
            type=str,
            default='jupiter',
            help='数据源: jupiter, solscan (默认: jupiter)'
        )
        parser.add_argument(
            '--address',
            type=str,
            help='代币地址'
        )
        parser.add_argument(
            '--chain',
            type=str,
            help='链类型'
        )

    def handle(self, *args, **options):
        if options.get('async_mode'):
            # 异步模式下，启动任务并立即返回
            asyncio.create_task(self._sync_metadata())
            self.stdout.write(self.style.SUCCESS('同步任务已启动'))
        else:
            # 同步模式下，等待任务完成
            asyncio.run(self.handle_async(*args, **options))
            self.stdout.write(self.style.SUCCESS('同步完成'))

    def update_sync_status(self, status='running', progress=0, message=''):
        try:
            cache.set(self.cache_key, {
                'status': status,
                'progress': progress,
                'message': message,
                'timestamp': timezone.now().isoformat()
            }, timeout=3600)  # 1小时超时
            logger.debug(f"更新同步状态: status={status}, progress={progress}, message={message}")
        except Exception as e:
            logger.error(f"更新同步状态失败: {str(e)}")

    def get_sync_status(self):
        try:
            status = cache.get(self.cache_key)
            if not status:
                return {
                    'status': 'idle',
                    'progress': 0,
                    'message': '未开始同步',
                    'timestamp': None
                }
            return status
        except Exception as e:
            logger.error(f"获取同步状态失败: {str(e)}")
            return {
                'status': 'error',
                'progress': 0,
                'message': f'获取状态失败: {str(e)}',
                'timestamp': timezone.now().isoformat()
            }

    async def handle_async(self, *args, **options):
        try:
            address = options.get('address')
            chain = options.get('chain')
            
            logger.info(f"开始同步代币 {address} 的元数据")
            
            # 获取代币服务
            token_service = ChainServiceFactory.get_token_info_service(chain)
            if not token_service:
                raise ValueError(f'不支持的链类型: {chain}')
            
            # 获取代币元数据
            token_data = await token_service.get_token_metadata(address)
            if not token_data:
                raise ValueError(f'未找到代币数据')
            
            # 更新或创建代币记录
            token, created = await sync_to_async(Token.objects.update_or_create)(
                chain=chain,
                address=address,
                defaults={
                    'name': token_data['name'],
                    'symbol': token_data['symbol'],
                    'decimals': token_data['decimals'],
                    'logo': token_data['logo'],
                    'description': token_data['description'],
                    'website': token_data['website'],
                    'twitter': token_data['twitter'],
                    'telegram': token_data['telegram'],
                    'discord': token_data['discord'],
                    'github': token_data['github'],
                    'medium': token_data['medium'],
                    'total_supply': token_data['total_supply'],
                    'total_supply_formatted': token_data['total_supply_formatted'],
                    'is_native': token_data['is_native'],
                    'is_verified': token_data['verified'],
                    'metaplex_data': token_data['metaplex_data'],
                    'is_visible': True
                }
            )
            
            logger.info(f"{'创建' if created else '更新'}代币成功: {token.symbol}")
            return token_data
            
        except Exception as e:
            logger.error(f"同步代币 {address} 失败: {str(e)}")
            logger.exception(e)
            raise

    async def _sync_from_jupiter(self):
        """从 Jupiter 同步代币元数据"""
        try:
            # 获取 Jupiter 代币列表
            async with aiohttp.ClientSession() as session:
                async with session.get('https://token.jup.ag/all') as response:
                    if response.status != 200:
                        raise Exception(f"获取 Jupiter 代币列表失败: {response.status}")
                    
                    tokens = await response.json()
                    
                    self.update_sync_status(
                        status='running', 
                        progress=10, 
                        message=f'从 Jupiter 获取到 {len(tokens)} 个代币'
                    )
            
            # 处理代币数据
            total = len(tokens)
            processed = 0
            
            for token in tokens:
                try:
                    # 获取代币分类
                    category = None
                    if 'tags' in token and token['tags']:
                        tag = token['tags'][0].lower()
                        if 'stable' in tag:
                            category_code = 'stablecoin'
                        elif 'meme' in tag:
                            category_code = 'meme'
                        elif 'defi' in tag:
                            category_code = 'defi'
                        elif 'gaming' in tag or 'game' in tag:
                            category_code = 'gamefi'
                        elif 'nft' in tag:
                            category_code = 'nft'
                        elif 'wrapped' in tag:
                            category_code = 'wrapped'
                        elif 'liquid' in tag and 'staking' in tag:
                            category_code = 'liquid_staking'
                        else:
                            category_code = 'other'
                        
                        # 获取分类对象
                        try:
                            category = await sync_to_async(TokenCategory.objects.get)(code=category_code)
                        except TokenCategory.DoesNotExist:
                            pass
                    
                    # 更新或创建代币
                    defaults = {
                        'name': token.get('name', ''),
                        'symbol': token.get('symbol', ''),
                        'decimals': token.get('decimals', 0),
                        'logo': token.get('logoURI', ''),
                        'is_native': token.get('address') == 'So11111111111111111111111111111111111111112',
                        'is_visible': True,
                        'is_verified': token.get('verified', False),
                        'category': category
                    }
                    
                    # 使用原始地址，不转换大小写
                    await sync_to_async(Token.objects.update_or_create)(
                        chain='SOL',
                        address=token.get('address'),
                        defaults=defaults
                    )
                    
                    processed += 1
                    if processed % 100 == 0 or processed == total:
                        progress = int(10 + (processed / total) * 90)
                        self.update_sync_status(
                            status='running', 
                            progress=progress, 
                            message=f'已处理 {processed}/{total} 个代币'
                        )
                
                except Exception as e:
                    logger.error(f"处理代币 {token.get('address')} 失败: {str(e)}")
            
            self.update_sync_status(
                status='completed', 
                progress=100, 
                message=f'同步完成，共处理 {processed}/{total} 个代币'
            )
            
        except Exception as e:
            logger.error(f"从 Jupiter 同步代币元数据失败: {str(e)}")
            self.update_sync_status(status='error', message=f'同步失败: {str(e)}')
            raise 

    async def _sync_single_token(self, address):
        """同步单个代币的元数据"""
        try:
            async with aiohttp.ClientSession() as session:
                # 从 Moralis 获取数据
                url = f'https://solana-gateway.moralis.io/token/mainnet/{address}/metadata'
                headers = {
                    'Accept': 'application/json',
                    'X-API-Key': settings.MORALIS_API_KEY
                }
                
                logger.info(f"开始从 Moralis 获取代币 {address} 的元数据")
                
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        raise Exception(f"Moralis API 请求失败: {response.status}")
                    
                    data = await response.json()
                    logger.info(f"Moralis API 返回数据: {json.dumps(data, indent=2)}")

                    # 根据实际返回的数据结构处理
                    token_data = {
                        'name': data.get('name', ''),
                        'symbol': data.get('symbol', ''),
                        'decimals': int(data.get('decimals', 0)),
                        'logo': data.get('logo', ''),
                        'is_native': address == 'So11111111111111111111111111111111111111112',
                        'is_visible': True,
                        'is_verified': True,
                        
                        # 详细信息
                        'description': data.get('description', ''),
                        'website': data.get('links', {}).get('website', ''),
                        'twitter': data.get('links', {}).get('twitter', ''),
                        'discord': data.get('links', {}).get('discord', ''),
                        'reddit': data.get('links', {}).get('reddit', ''),
                        'telegram': data.get('links', {}).get('telegram', ''),
                        
                        # 市场数据
                        'total_supply': data.get('totalSupply', ''),
                        'total_supply_formatted': data.get('totalSupplyFormatted', ''),
                        'fully_diluted_valuation': data.get('fullyDilutedValue', ''),
                        
                        # 其他信息
                        'contract_type': data.get('standard', 'Unknown'),
                        'metaplex_data': data.get('metaplex', {}),  # 保存 metaplex 相关数据
                    }

                    # 设置代币分类 - 可以根据名称或其他特征来判断
                    category_code = 'other'
                    name_lower = token_data['name'].lower()
                    if 'usd' in name_lower or 'usdt' in name_lower or 'usdc' in name_lower:
                        category_code = 'stablecoin'
                    elif 'bonk' in name_lower or 'doge' in name_lower or 'shib' in name_lower:
                        category_code = 'meme'
                    elif 'wrapped' in name_lower:
                        category_code = 'wrapped'
                    elif 'game' in name_lower:
                        category_code = 'gamefi'
                    elif 'nft' in name_lower:
                        category_code = 'nft'

                    try:
                        category = await sync_to_async(TokenCategory.objects.get)(code=category_code)
                        token_data['category'] = category
                    except TokenCategory.DoesNotExist:
                        token_data['category'] = None

                    logger.info(f"处理后的代币数据: {json.dumps(token_data, indent=2)}")

                    # 更新代币信息
                    await sync_to_async(Token.objects.update_or_create)(
                        chain='SOL',
                        address=address,
                        defaults=token_data
                    )

                    self.update_sync_status(
                        status='completed', 
                        progress=100, 
                        message=f'代币 {address} 同步完成'
                    )

        except Exception as e:
            logger.error(f"同步代币 {address} 失败: {str(e)}")
            raise