from django.core.management.base import BaseCommand
import asyncio
from wallet.token_services.transfer_service import TransferService

class Command(BaseCommand):
    help = 'Test Solana RPC connection'

    def handle(self, *args, **options):
        async def test():
            result = await TransferService.test_rpc_connection()
            self.stdout.write(self.style.SUCCESS(f'RPC连接测试结果: {result}'))

        asyncio.run(test()) 