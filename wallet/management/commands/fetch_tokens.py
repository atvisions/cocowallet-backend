import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from wallet.models import Token
import time
from datetime import datetime
from django.utils import timezone
import pytz
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

class Command(BaseCommand):
    help = '从QuickNode API获取代币数据'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 设置请求会话
        self.session = requests.Session()
        retries = Retry(
            total=5,  # 总重试次数
            backoff_factor=0.5,  # 重试间隔
            status_forcelist=[500, 502, 503, 504, 429]  # 需要重试的HTTP状态码
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

    def parse_datetime(self, date_str):
        if not date_str:
            return None
        try:
            naive_dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
            return timezone.make_aware(naive_dt, timezone=pytz.UTC)
        except ValueError:
            return None

    def get_chain_and_addresses(self, coin_data, coin_id):
        """获取代币的所有链和地址信息"""
        results = []
        
        # 处理原生代币
        symbol = coin_data.get('symbol', '').upper()
        native_tokens = {
            'BTC': ('BTC', 'bitcoin'),  # 比特币没有合约地址
            'ETH': ('ETH', '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'),  # ETH的标准地址
            'BNB': ('BNB', '0xB8c77482e45F1F44dE1745F52C74426C631bDD52'),  # BNB在ETH上的地址
            'MATIC': ('MATIC', '0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0'),  # MATIC在ETH上的地址
            'AVAX': ('AVAX', '0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7'),  # AVAX的合约地址
            'SOL': ('SOL', 'So11111111111111111111111111111111111111112'),  # SOL的程序ID
        }
        
        if symbol in native_tokens:
            chain, address = native_tokens[symbol]
            results.append((chain, address, 'NATIVE'))
            return results
            
        # 处理多链合约
        contracts = coin_data.get('contracts', [])
        if contracts:
            platform_mapping = {
                'eth-ethereum': 'ETH',
                'bnb-binance-coin': 'BNB',
                'matic-polygon': 'MATIC',
                'sol-solana': 'SOL',
                'arb-arbitrum': 'ARB',
                'avax-avalanche': 'AVAX',
            }
            
            for contract in contracts:
                platform = contract.get('platform')
                chain = platform_mapping.get(platform)
                if chain and contract.get('contract'):
                    results.append((
                        chain,
                        contract['contract'],
                        contract.get('type', 'Other')
                    ))
            
            if results:
                return results
        
        # 处理单一平台
        platform = coin_data.get('platform')
        contract = coin_data.get('contract')
        if platform and contract:
            platform_mapping = {
                'eth-ethereum': 'ETH',
                'bnb-binance-coin': 'BNB',
                'matic-polygon': 'MATIC',
                'sol-solana': 'SOL',
                'arb-arbitrum': 'ARB',
                'avax-avalanche': 'AVAX',
            }
            chain = platform_mapping.get(platform)
            if chain:
                results.append((chain, contract, 'Other'))
                return results
        
        # 处理特殊代币
        special_tokens = {
            'usdt-tether': [('ETH', '0xdac17f958d2ee523a2206206994597c13d831ec7', 'ERC20')],
            'usdc-usd-coin': [('ETH', '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', 'ERC20')],
            'wbtc-wrapped-bitcoin': [('ETH', '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599', 'ERC20')],
            'link-chainlink': [('ETH', '0x514910771af9ca656af840dff83e8264ecf986ca', 'ERC20')],
            'shib-shiba-inu': [('ETH', '0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce', 'ERC20')],
            'weth-weth': [('ETH', '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2', 'ERC20')],
            'dai-dai': [('ETH', '0x6b175474e89094c44da98b954eedeac495271d0f', 'ERC20')],
            'uni-uniswap': [('ETH', '0x1f9840a85d5af5bf1d1762f925bdaddc4201f984', 'ERC20')],
            'aave-new': [('ETH', '0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9', 'ERC20')],
            'steth-lido-staked-ether': [('ETH', '0xae7ab96520de3a18e5e111b5eaab095312d7fe84', 'ERC20')],
        }
        
        if coin_id in special_tokens:
            return special_tokens[coin_id]
            
        return results

    def handle(self, *args, **options):
        base_url = "https://api.coinpaprika.com/v1"
        
        # 获取前50个代币来测试
        self.stdout.write('获取代币列表...')
        coins_data = self.fetch_with_retry(f"{base_url}/coins")
        if not coins_data:
            self.stdout.write(self.style.ERROR('获取币种列表失败'))
            return
        
        # 只处理排名前50的代币
        coins = sorted(
            [c for c in coins_data if c.get('rank') and c.get('rank') != 0],
            key=lambda x: float(x.get('rank', 999999))
        )[:50]  # 减少处理数量
        
        total_imported = 0
        skipped = 0
        failed = 0
        
        for coin in coins:
            try:
                coin_id = coin['id']
                rank = coin.get('rank', 'N/A')
                self.stdout.write(f'处理币种 {coin_id} (rank: {rank})...')
                
                # 获取币种详细信息
                coin_data = self.fetch_with_retry(f"{base_url}/coins/{coin_id}")
                if not coin_data:
                    failed += 1
                    self.stdout.write(self.style.ERROR(f'获取币种 {coin_id} 详情失败'))
                    continue
                
                # 获取链和地址信息
                chain_addresses = self.get_chain_and_addresses(coin_data, coin_id)
                if not chain_addresses:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(f'跳过币种 {coin_id}: 无法确定链或地址')
                    )
                    continue

                # 处理链接
                links = coin_data.get('links', {})
                
                # 基本信息
                base_info = {
                    'name': coin['name'],
                    'symbol': coin['symbol'].upper(),
                    'decimals': coin_data.get('decimals', 18),
                    'logo': coin_data.get('logo'),
                    'rank': coin.get('rank'),
                    'is_new': coin.get('is_new', False),
                    'is_active': coin.get('is_active', True),
                    'type': coin.get('type', 'token'),
                    
                    # 扩展信息
                    'description': coin_data.get('description', ''),
                    'tags': coin_data.get('tags', []),
                    'team': coin_data.get('team', []),
                    'open_source': coin_data.get('open_source', True),
                    'started_at': self.parse_datetime(coin_data.get('started_at')),
                    'development_status': coin_data.get('development_status'),
                    'hardware_wallet': coin_data.get('hardware_wallet', False),
                    'proof_type': coin_data.get('proof_type'),
                    'org_structure': coin_data.get('org_structure'),
                    'hash_algorithm': coin_data.get('hash_algorithm'),
                    
                    # 链接
                    'website': links.get('website', [''])[0],
                    'explorer': links.get('explorer', []),
                    'reddit': links.get('reddit', []),
                    'source_code': links.get('source_code', []),
                    'twitter': next((link['url'] for link in coin_data.get('links_extended', []) 
                                  if link['type'] == 'twitter'), None),
                    'telegram': next((link['url'] for link in coin_data.get('links_extended', []) 
                                   if link['type'] == 'telegram'), None),
                    
                    # 扩展链接
                    'links_extended': coin_data.get('links_extended', []),
                    
                    # 白皮书
                    'whitepaper_link': coin_data.get('whitepaper', {}).get('link'),
                    'whitepaper_thumbnail': coin_data.get('whitepaper', {}).get('thumbnail'),
                    
                    # 时间信息
                    'first_data_at': self.parse_datetime(coin_data.get('first_data_at')),
                    'last_data_at': self.parse_datetime(coin_data.get('last_data_at')),
                }
                
                # 为每个链创建或更新代币记录
                for chain, address, contract_type in chain_addresses:
                    token, created = Token.objects.update_or_create(
                        coin_id=coin_id,
                        chain=chain,
                        address=address,
                        defaults={
                            **base_info,
                            'contract_type': contract_type
                        }
                    )
                    
                    if created:
                        total_imported += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'成功导入代币: {token.name} ({token.symbol}) on {chain} - {contract_type}'
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f'更新代币: {token.name} ({token.symbol}) on {chain} - {contract_type}'
                            )
                        )
                
                # 动态调整延时
                if coin.get('rank', 0) > 100:
                    time.sleep(1)  # 对于排名靠后的代币，增加延时
                else:
                    time.sleep(0.5)  # 优先处理排名靠前的代币
                
            except Exception as e:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(f'处理币种 {coin.get("id")} 时出错: {str(e)}')
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'导入完成!\n'
                f'- 成功导入: {total_imported} 个新代币\n'
                f'- 跳过: {skipped} 个代币\n'
                f'- 失败: {failed} 个代币'
            )
        ) 