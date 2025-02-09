from django.core.management.base import BaseCommand
import aiohttp
import asyncio
import json
from wallet.api_config import APIConfig

class Command(BaseCommand):
    help = '测试 Solana RPC 节点连接'

    def handle(self, *args, **options):
        async def test_solana_rpc():
            rpc_url = APIConfig.RPC.SOLANA_MAINNET_RPC_URL
            if not rpc_url:
                return {'success': False, 'message': '未配置 Solana RPC 节点URL'}

            try:
                async with aiohttp.ClientSession() as session:
                    # 获取版本信息
                    version_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getVersion"
                    }
                    async with session.post(rpc_url, json=version_payload) as response:
                        version_result = await response.json()
                        if 'result' not in version_result:
                            return {
                                'success': False,
                                'message': 'RPC 节点响应错误',
                                'details': version_result
                            }
                        
                    # 获取最新区块高度
                    slot_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getSlot"
                    }
                    async with session.post(rpc_url, json=slot_payload) as response:
                        slot_result = await response.json()
                        if 'result' not in slot_result:
                            return {
                                'success': False,
                                'message': 'RPC 节点响应错误',
                                'details': slot_result
                            }
                        
                    # 获取最新区块哈希
                    blockhash_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getLatestBlockhash"
                    }
                    async with session.post(rpc_url, json=blockhash_payload) as response:
                        blockhash_result = await response.json()
                        if 'result' not in blockhash_result:
                            return {
                                'success': False,
                                'message': 'RPC 节点响应错误',
                                'details': blockhash_result
                            }
                        
                    return {
                        'success': True,
                        'message': 'Solana RPC 节点连接正常',
                        'details': {
                            'version': version_result['result'].get('solana-core'),
                            'slot': slot_result['result'],
                            'blockhash': blockhash_result['result']['value']['blockhash']
                        }
                    }
                    
            except Exception as e:
                return {
                    'success': False,
                    'message': f'连接失败: {str(e)}',
                    'error': str(e)
                }

        result = asyncio.run(test_solana_rpc())
        self.stdout.write(
            self.style.SUCCESS(f'测试结果: {json.dumps(result, ensure_ascii=False, indent=2)}')
            if result.get('success')
            else self.style.ERROR(f'测试失败: {json.dumps(result, ensure_ascii=False, indent=2)}')
        ) 