import aiohttp
import asyncio
import json

HELIUS_API_KEY = "87466c84-da3e-42be-b346-a4e837da857f"
WALLET_ADDRESS = "HCtD2JcUWLreM8WS3YUgS4pUfd7vXuoQRHh4RtAm27oP"

async def get_nft_collections():
    # Helius RPC API endpoint
    url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    
    print(f"正在获取钱包 {WALLET_ADDRESS} 的 NFT 数据...")
    
    payload = {
        "jsonrpc": "2.0",
        "id": "my-id",
        "method": "getAssetsByOwner",
        "params": {
            "ownerAddress": WALLET_ADDRESS,
            "page": 1,
            "limit": 100
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                print(f"获取NFT数据失败: HTTP {response.status}")
                print(f"错误信息: {error_text}")
                return
            
            data = await response.json()
            if 'error' in data:
                print(f"API返回错误: {data['error']}")
                return
                
            items = data.get('result', {}).get('items', [])
            
            # 按合集分组NFTs
            collections = {}
            
            for item in items:
                try:
                    # 获取合集信息
                    grouping = item.get('grouping', [])
                    collection_name = None
                    
                    # 尝试从grouping中获取合集名称
                    for group in grouping:
                        if group.get('group_key') == 'collection':
                            collection_name = group.get('group_value')
                            break
                    
                    # 如果没有合集名称，使用symbol
                    if not collection_name:
                        collection_name = item.get('content', {}).get('metadata', {}).get('symbol', 'Unknown')
                    
                    if collection_name not in collections:
                        collections[collection_name] = {
                            'name': collection_name,
                            'nft_count': 0,
                            'nfts': []
                        }
                    
                    # 获取NFT信息
                    content = item.get('content', {})
                    metadata = content.get('metadata', {})
                    
                    # 获取图片URL
                    image_url = None
                    files = content.get('files', [])
                    if files and isinstance(files, list) and len(files) > 0:
                        image_url = files[0].get('uri', '')
                    
                    if not image_url:
                        image_url = metadata.get('image', '')
                    
                    collections[collection_name]['nft_count'] += 1
                    collections[collection_name]['nfts'].append({
                        'name': metadata.get('name', ''),
                        'image': image_url,
                        'mint': item.get('id', '')
                    })
                    
                except Exception as e:
                    print(f"处理NFT数据时出错: {str(e)}")
                    continue
            
            # 打印结果
            print(f"\n找到 {len(collections)} 个 NFT 合集:")
            for name, data in collections.items():
                print(f"\n合集: {name}")
                print(f"NFT数量: {data['nft_count']}")
                print("\nNFTs:")
                for nft in data['nfts'][:3]:  # 只显示前3个NFT
                    print(f"- {nft['name']} (Mint: {nft['mint']})")
                    if nft['image']:
                        print(f"  图片: {nft['image']}")
                if len(data['nfts']) > 3:
                    print(f"... 还有 {len(data['nfts']) - 3} 个NFT未显示")

async def main():
    await get_nft_collections()

if __name__ == "__main__":
    asyncio.run(main()) 