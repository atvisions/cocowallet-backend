import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coco_wallet.settings')
django.setup()

import asyncio
from wallet.token_services.transfer_service import TransferService

async def test():
    result = await TransferService.test_rpc_connection()
    print('RPC连接测试结果:', result)

if __name__ == '__main__':
    asyncio.run(test()) 