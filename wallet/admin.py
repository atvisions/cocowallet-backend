from django.contrib import admin
from django.utils.html import format_html
import requests
from django.contrib import messages
from .models import (
    Wallet, Token, NFTCollection, Transaction,
    MnemonicBackup, PaymentPassword, TokenIndex
)
import re

@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    def logo_display(self, obj):
        """显示代币logo"""
        if obj.logo:
            return format_html('<img src="{}" style="width: 32px; height: 32px; border-radius: 50%;" />', obj.logo)
        return format_html('<div style="width: 32px; height: 32px; border-radius: 50%; background-color: #f0f0f0; display: flex; align-items: center; justify-content: center;">{}</div>', obj.symbol[0] if obj.symbol else '?')
    logo_display.short_description = 'Logo'

    list_display = [
        'logo_display', 'name', 'symbol', 'chain', 'address', 'type',
        'rank', 'is_active', 'is_new', 'open_source',
        'development_status'
    ]
    list_filter = [
        'chain', 'type', 'is_active', 'is_new',
        'open_source', 'hardware_wallet'
    ]
    search_fields = ['name', 'symbol', 'address', 'coin_id']
    readonly_fields = [
        'coin_id', 'rank', 'first_data_at', 'last_data_at',
        'created_at', 'updated_at'
    ]
    fieldsets = [
        ('基本信息', {
            'fields': [
                'chain', 'name', 'symbol', 'address', 'decimals',
                'logo', 'coin_id', 'rank', 'type'
            ]
        }),
        ('状态', {
            'fields': [
                'is_new', 'is_active', 'open_source',
                'hardware_wallet'
            ]
        }),
        ('项目信息', {
            'fields': [
                'description', 'tags', 'team', 'started_at',
                'development_status', 'proof_type',
                'org_structure', 'hash_algorithm'
            ]
        }),
        ('链接', {
            'fields': [
                'website', 'explorer', 'reddit', 'source_code',
                'technical_doc', 'twitter', 'telegram',
                'links_extended'
            ]
        }),
        ('白皮书', {
            'fields': ['whitepaper_link', 'whitepaper_thumbnail']
        }),
        ('时间信息', {
            'fields': [
                'first_data_at', 'last_data_at',
                'created_at', 'updated_at'
            ]
        })
    ]
    ordering = ['rank', '-is_active']

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['name', 'chain', 'address', 'is_active', 'is_watch_only', 'is_imported', 'created_at']
    list_filter = ['chain', 'is_active', 'is_watch_only', 'is_imported']
    search_fields = ['name', 'address', 'device_id']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(NFTCollection)
class NFTCollectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'chain', 'contract_address', 'is_verified', 'is_recommended', 'floor_price']
    list_filter = ['chain', 'is_verified', 'is_recommended']
    search_fields = ['name', 'contract_address']
    list_editable = ['is_verified', 'is_recommended']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['tx_hash', 'chain', 'tx_type', 'status', 'from_address', 'to_address', 'block_timestamp']
    list_filter = ['chain', 'tx_type', 'status']
    search_fields = ['tx_hash', 'from_address', 'to_address']
    readonly_fields = ['created_at']

@admin.register(MnemonicBackup)
class MnemonicBackupAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'created_at']
    search_fields = ['device_id']
    readonly_fields = ['created_at']

@admin.register(PaymentPassword)
class PaymentPasswordAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'created_at', 'updated_at']
    search_fields = ['device_id']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(TokenIndex)
class TokenIndexAdmin(admin.ModelAdmin):
    list_display = ['coin_id', 'name', 'symbol', 'rank', 'is_new', 'is_active', 'type', 'is_token_synced', 'updated_at', 'sync_button']
    list_filter = ['is_new', 'is_active', 'type', 'is_token_synced']
    search_fields = ['coin_id', 'name', 'symbol']
    ordering = ['rank']
    readonly_fields = ['updated_at']
    actions = ['sync_selected_tokens', 'import_token_indexes']

    def sync_button(self, obj):
        """为每行添加同步按钮"""
        return format_html(
            '<a class="el-button el-button--primary el-button--small" href="javascript:void(0);" onclick="syncToken(\'{}\')">更新</a>',
            obj.coin_id
        )
    sync_button.short_description = '操作'

    def _clean_string(self, text):
        if not text:
            return ''
        # 移除表情符号和特殊字符
        text = re.sub(r'[^\x00-\x7F]+', '', text)
        # 移除多余的空格
        text = ' '.join(text.split())
        return text.strip()

    def import_token_indexes(self, request, queryset):
        base_api_url = "https://serene-sly-voice.solana-mainnet.quiknode.pro/6a79cc4a87b9f9024abafc0783211ea381c4d181/addon/748/v1/coins/"
        
        # 统计计数器
        new_count = 0
        update_count = 0
        error_count = 0
        
        try:
            page = 1
            while True:
                api_url = f"{base_api_url}?page={page}"
                response = requests.get(api_url)
                
                if not response.ok:
                    self.message_user(request, f"API请求失败: {response.status_code}", level=messages.ERROR)
                    break
                    
                data = response.json()
                if not data:
                    break
                    
                for token in data:
                    try:
                        coin_id = token.get('id')
                        if not coin_id:
                            error_count += 1
                            continue
                            
                        # 清理数据
                        token_data = {
                            'name': self._clean_string(token.get('name', '')),
                            'symbol': self._clean_string(token.get('symbol', '')),
                            'rank': token.get('rank', 0),
                            'is_new': token.get('is_new', False),
                            'is_active': token.get('is_active', True),
                            'type': token.get('type', 'token'),
                            'is_token_synced': False
                        }
                        
                        # 尝试更新现有记录，如果不存在则创建新记录
                        obj, created = TokenIndex.objects.update_or_create(
                            coin_id=coin_id,
                            defaults=token_data
                        )
                        
                        if created:
                            new_count += 1
                        else:
                            update_count += 1
                            
                    except Exception as e:
                        error_count += 1
                        print(f"处理代币 {coin_id} 时出错: {str(e)}")
                        continue
                
                page += 1
                
            self.message_user(
                request,
                f"导入完成。新增: {new_count}, 更新: {update_count}, 错误: {error_count}",
                level=messages.SUCCESS if error_count == 0 else messages.WARNING
            )
            
        except Exception as e:
            self.message_user(request, f"导入过程发生错误: {str(e)}", level=messages.ERROR)

    def sync_selected_tokens(self, request, queryset):
        """批量同步选中的代币"""
        success_count = 0
        failed_count = 0
        
        for token_index in queryset:
            try:
                self.sync_token_data(token_index)
                success_count += 1
            except Exception as e:
                failed_count += 1
                self.message_user(request, f"同步代币 {token_index.name} 失败: {str(e)}", level=messages.ERROR)
        
        self.message_user(request, f"成功同步 {success_count} 个代币，失败 {failed_count} 个")
    sync_selected_tokens.short_description = "同步选中代币"

    def sync_token_data(self, token_index):
        """同步单个代币数据，确保数据完整性"""
        # 原生币配置
        native_coins = {
            'BTC': {
                'chain': 'BITCOIN',
                'decimals': 8,
                'contract': '0x0000000000000000000000000000000000000000'
            },
            'ETH': {
                'chain': 'ETHEREUM',
                'decimals': 18,
                'contract': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
            },
            'DOGE': {
                'chain': 'DOGECOIN',
                'decimals': 8,
                'contract': '0xba2ae424d960c26247dd6c32edc70b295c744c43'  # DOGE的BSC合约地址
            },
            'SOL': {
                'chain': 'SOLANA',
                'decimals': 9,
                'contract': 'So11111111111111111111111111111111111111112'
            },
        }

        # 主接口
        main_api_url = f"https://serene-sly-voice.solana-mainnet.quiknode.pro/6a79cc4a87b9f9024abafc0783211ea381c4d181/addon/748/v1/coins/{token_index.coin_id}"
        # 备选接口列表
        backup_apis = [
            f"https://api.coingecko.com/api/v3/coins/{token_index.coin_id}",
            f"https://pro-api.coinmarketcap.com/v2/cryptocurrency/info?symbol={token_index.symbol}"
        ]

        try:
            # 尝试主接口
            response = requests.get(main_api_url)
            data = None
            
            if response.status_code == 200:
                data = response.json()
                # 检查数据是否为空或不完整
                if not data or not data.get('contracts', []):
                    # 如果主接口数据为空，尝试备选接口
                    for backup_api in backup_apis:
                        try:
                            backup_response = requests.get(backup_api)
                            if backup_response.status_code == 200:
                                backup_data = backup_response.json()
                                if backup_data:
                                    # 将备选接口数据转换为标准格式
                                    data = self._convert_backup_data(backup_data, token_index)
                                    if data and data.get('contracts'):
                                        break
                        except Exception as e:
                            print(f"备选接口请求失败: {str(e)}")
                            continue

            if not data:
                raise Exception("所有接口都未返回有效数据")

            # 基础数据验证
            if not all(field in data for field in ['name', 'symbol', 'type']):
                raise Exception("基础数据不完整")
            
            # 构建基础数据
            base_token_data = {
                'name': data['name'],
                'symbol': data['symbol'],
                'type': data['type'],
                'description': data.get('description', ''),
                'logo': data.get('logo', ''),
                'rank': data.get('rank', 0),
                'is_new': data.get('is_new', False),
                'is_active': data.get('is_active', True),
                'open_source': data.get('open_source', False),
                'hardware_wallet': data.get('hardware_wallet', False),
                'development_status': data.get('development_status'),
                'proof_type': data.get('proof_type'),
                'org_structure': data.get('org_structure'),
                'hash_algorithm': data.get('hash_algorithm'),
                'tags': data.get('tags', []),
                'team': data.get('team', []),
                'links_extended': data.get('links_extended', []),
                'website': data.get('links', {}).get('website', [None])[0],
                'explorer': data.get('links', {}).get('explorer', []),
                'reddit': data.get('links', {}).get('reddit', []),
                'source_code': data.get('links', {}).get('source_code', []),
                'technical_doc': data.get('links', {}).get('technical_doc', [None])[0],
                'twitter': next((link['url'] for link in data.get('links_extended', []) if link.get('type') == 'twitter'), None),
                'telegram': next((link['url'] for link in data.get('links_extended', []) if link.get('type') == 'telegram'), None),
                'whitepaper_link': data.get('whitepaper', {}).get('link'),
                'whitepaper_thumbnail': data.get('whitepaper', {}).get('thumbnail'),
                'first_data_at': data.get('first_data_at'),
                'last_data_at': data.get('last_data_at'),
                'coin_id': token_index.coin_id,
            }

            success = False
            
            # 首先删除该代币的所有旧记录
            Token.objects.filter(coin_id=token_index.coin_id).delete()

            # 检查是否是原生币
            symbol = data['symbol'].upper()
            if symbol in native_coins:
                # 使用预定义的原生币配置
                coin_config = native_coins[symbol]
                token_data = {
                    **base_token_data,
                    'chain': coin_config['chain'],
                    'address': coin_config['contract'],
                    'decimals': coin_config['decimals']
                }
                Token.objects.create(**token_data)
                success = True
            else:
                # 处理合约数据
                contracts = data.get('contracts', [])
                if contracts:
                    for contract in contracts:
                        if not contract.get('contract') or not contract.get('platform'):
                            continue
                        
                        platform = contract['platform'].split('-')[0].upper()
                        chain_mapping = {
                            'ETH': 'ETHEREUM',
                            'BSC': 'BSC',
                            'POLYGON': 'POLYGON',
                            'SOLANA': 'SOLANA',
                            'AVALANCHE': 'AVALANCHE',
                            'FANTOM': 'FANTOM',
                            'TRON': 'TRON',
                            'NEAR': 'NEAR',
                        }
                        
                        chain = chain_mapping.get(platform, platform)
                        token_data = {
                            **base_token_data,
                            'chain': chain,
                            'address': contract['contract'],
                            'decimals': contract.get('decimals', 18)
                        }
                        Token.objects.create(**token_data)
                        success = True
            
            if not success:
                raise Exception("没有找到有效的合约信息")

            # 更新同步状态
            token_index.is_token_synced = True
            token_index.save()
            
        except Exception as e:
            token_index.is_token_synced = False
            token_index.save()
            raise e

    def _convert_backup_data(self, backup_data, token_index):
        """将备选接口的数据转换为标准格式"""
        # 处理CoinGecko数据格式
        if 'platforms' in backup_data:
            contracts = []
            for platform, address in backup_data['platforms'].items():
                if address:
                    contracts.append({
                        'platform': platform,
                        'contract': address,
                        'decimals': 18
                    })
            
            return {
                'name': backup_data.get('name', token_index.name),
                'symbol': backup_data.get('symbol', token_index.symbol).upper(),
                'type': 'token',
                'contracts': contracts,
                'description': backup_data.get('description', {}).get('en', ''),
                'logo': backup_data.get('image', {}).get('large', ''),
                'rank': backup_data.get('market_cap_rank', 0),
                'is_active': True
            }
            
        # 处理CoinMarketCap数据格式
        elif 'data' in backup_data:
            token_data = next(iter(backup_data['data'].values()))
            contracts = []
            for platform in token_data.get('platform', []):
                if platform.get('token_address'):
                    contracts.append({
                        'platform': platform['name'],
                        'contract': platform['token_address'],
                        'decimals': platform.get('decimals', 18)
                    })
            
            return {
                'name': token_data.get('name', token_index.name),
                'symbol': token_data.get('symbol', token_index.symbol).upper(),
                'type': 'token',
                'contracts': contracts,
                'description': token_data.get('description', ''),
                'logo': token_data.get('logo', ''),
                'rank': token_data.get('cmc_rank', 0),
                'is_active': True
            }
            
        return None

    class Media:
        js = ('admin/js/token_sync.js',)

    def get_fieldsets(self, request, obj=None):
        return [
            ('基本信息', {
                'fields': [
                    'coin_id', 'name', 'symbol', 'rank'
                ]
            }),
            ('状态', {
                'fields': [
                    'is_new', 'is_active', 'type', 'is_token_synced'
                ]
            }),
            ('时间信息', {
                'fields': [
                    'updated_at'
                ]
            })
        ]
