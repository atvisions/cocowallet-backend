import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from wallet.models import TokenIndex
import time
from datetime import datetime
from django.utils import timezone
import pytz
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

class Command(BaseCommand):
    help = '从API获取代币索引数据'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504, 429, 402]
        )
        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def fetch_with_retry(self, url, max_retries=3, delay=65):
        """带重试机制的请求"""
        for attempt in range(max_retries):
            try:
                # 每次请求前强制等待
                self.stdout.write(self.style.WARNING(f'等待 {delay} 秒...'))
                time.sleep(delay)
                
                response = self.session.get(url, timeout=30)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 402:
                    error_data = response.json()
                    block_duration = error_data.get('block_duration', '1h')
                    wait_time = 3600 if block_duration == '1h' else 7200
                    self.stdout.write(self.style.ERROR(f'达到API限制，等待 {wait_time} 秒...'))
                    time.sleep(wait_time)
                    continue
                else:
                    self.stdout.write(self.style.WARNING(f'请求失败，状态码: {response.status_code}'))
                
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'请求异常: {str(e)}'))
                if attempt < max_retries - 1:
                    time.sleep(delay * (attempt + 1))
                    continue
                
        return None

    def handle(self, *args, **options):
        base_url = "https://serene-sly-voice.solana-mainnet.quiknode.pro/6a79cc4a87b9f9024abafc0783211ea381c4d181/addon/748/v1"
        
        # 获取代币列表
        self.stdout.write('获取代币列表...')
        coins_data = self.fetch_with_retry(f"{base_url}/coins/")
        if not coins_data:
            self.stdout.write(self.style.ERROR('获取币种列表失败'))
            return
        
        total_imported = 0
        total_updated = 0
        failed = 0
        
        # 按rank排序处理
        coins = sorted(
            [c for c in coins_data if isinstance(c.get('rank'), (int, float)) and c['rank'] > 0],
            key=lambda x: float(x['rank'])
        )
        
        for coin in coins:
            try:
                coin_id = coin['id']
                rank = coin.get('rank', 0)
                
                # 创建或更新代币索引
                token_index, created = TokenIndex.objects.update_or_create(
                    coin_id=coin_id,
                    defaults={
                        'name': coin['name'],
                        'symbol': coin['symbol'].upper(),
                        'rank': rank,
                        'is_new': coin.get('is_new', False),
                        'is_active': coin.get('is_active', True),
                        'type': coin.get('type', 'token'),
                    }
                )
                
                if created:
                    total_imported += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'导入代币索引: {token_index.name} ({token_index.symbol}) - Rank {rank}'
                        )
                    )
                else:
                    total_updated += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'更新代币索引: {token_index.name} ({token_index.symbol}) - Rank {rank}'
                        )
                    )
                
            except Exception as e:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(f'处理币种 {coin.get("id")} 时出错: {str(e)}')
                )
                continue
        
        self.stdout.write(
            self.style.SUCCESS(
                f'导入完成!\n'
                f'- 新增: {total_imported} 个代币\n'
                f'- 更新: {total_updated} 个代币\n'
                f'- 失败: {failed} 个代币'
            )
        ) 