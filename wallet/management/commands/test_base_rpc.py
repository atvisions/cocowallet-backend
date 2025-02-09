from django.core.management.base import BaseCommand
import aiohttp
import asyncio
import json
from wallet.api_config import APIConfig

class Command(BaseCommand):
    help = '测试 Base RPC 节点连接'

    def handle(self, *args, **options):
        async def test_base_rpc():
            rpc_url = APIConfig.RPC.BASE_RPC_URL
            if not rpc_url:
                return {'success': False, 'message': '未配置 Base RPC 节点URL'}

            try:
                async with aiohttp.ClientSession() as session:
                    # 获取最新区块信息
                    payload = {
                        "id": 1,
                        "jsonrpc": "2.0",
                        "method": "eth_getBlockByNumber",
                        "params": ["latest", False]
                    }
                    
                    async with session.post(rpc_url, json=payload) as response:
                        result = await response.json()
                        
                        if 'result' in result:
                            return {
                                'success': True,
                                'message': 'Base RPC 节点连接正常',
                                'details': {
                                    'block_number': int(result['result']['number'], 16),
                                    'timestamp': int(result['result']['timestamp'], 16),
                                    'hash': result['result']['hash']
                                }
                            }
                        else:
                            return {
                                'success': False,
                                'message': f'RPC 节点响应错误: {result.get("error", "未知错误")}',
                                'details': result
                            }
            except Exception as e:
                return {
                    'success': False,
                    'message': f'连接失败: {str(e)}',
                    'error': str(e)
                }

        result = asyncio.run(test_base_rpc())
        self.stdout.write(
            self.style.SUCCESS(f'测试结果: {json.dumps(result, ensure_ascii=False, indent=2)}')
            if result.get('success')
            else self.style.ERROR(f'测试失败: {json.dumps(result, ensure_ascii=False, indent=2)}')
        ) 