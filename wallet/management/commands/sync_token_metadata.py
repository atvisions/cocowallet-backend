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
        """异步处理命令"""
        source = options.get('source', 'jupiter')
        
        self.update_sync_status(status='running', progress=0, message=f'开始从 {source} 同步代币元数据')
        
        try:
            if source == 'jupiter':
                await self._sync_from_jupiter()
            else:
                self.update_sync_status(status='error', message=f'不支持的数据源: {source}')
                return
                
            self.update_sync_status(status='completed', progress=100, message='同步完成')
        except Exception as e:
            logger.error(f"同步失败: {str(e)}")
            self.update_sync_status(status='error', message=f'同步失败: {str(e)}')

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