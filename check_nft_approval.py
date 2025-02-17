from web3 import Web3
import asyncio
import json

# ERC721 代币 ABI
ERC721_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "getApproved",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "operator", "type": "address"}
        ],
        "name": "isApprovedForAll",
        "outputs": [{"name": "", "type": "boolean"}],
        "type": "function"
    }
]

async def check_nft_approval(
    nft_contract_address: str,
    token_id: str,
    wallet_address: str,
    rpc_url: str
):
    """检查 NFT 的授权状态
    
    Args:
        nft_contract_address: NFT 合约地址
        token_id: NFT Token ID
        wallet_address: 钱包地址
        rpc_url: RPC 节点地址
    """
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    
    # 转换地址格式
    nft_contract_address = web3.to_checksum_address(nft_contract_address)
    wallet_address = web3.to_checksum_address(wallet_address)
    
    # 创建合约实例
    contract = web3.eth.contract(address=nft_contract_address, abi=ERC721_ABI)
    
    try:
        # 检查单个 NFT 的授权
        approved_address = contract.functions.getApproved(int(token_id)).call()
        
        # 检查是否授权给所有 NFT
        operators = []
        events = contract.events.ApprovalForAll().get_logs(fromBlock=0)
        for event in events:
            if event.args.owner.lower() == wallet_address.lower():
                operator = event.args.operator
                is_approved = event.args.approved
                if is_approved:
                    operators.append(operator)
        
        print(f"\n检查结果:")
        print(f"NFT 合约地址: {nft_contract_address}")
        print(f"Token ID: {token_id}")
        print(f"钱包地址: {wallet_address}")
        print(f"\n单个 NFT 授权状态:")
        if approved_address != "0x0000000000000000000000000000000000000000":
            print(f"已授权给地址: {approved_address}")
        else:
            print("未授权给任何地址")
            
        print(f"\n全部 NFT 授权状态:")
        if operators:
            print("已授权给以下操作者:")
            for operator in operators:
                print(f"- {operator}")
        else:
            print("未授权给任何操作者")
            
    except Exception as e:
        print(f"检查授权状态时出错: {str(e)}")

if __name__ == "__main__":
    # 替换为实际的参数
    NFT_CONTRACT = "0x3fc29836e84e471a053d2d9e80494a867d670ead"  # NFT 合约地址
    TOKEN_ID = "1"  # NFT Token ID
    WALLET_ADDRESS = "0x74E7c6A60F88B01a15Da447B09a8e403053CCA0B"  # 钱包地址
    RPC_URL = "https://eth-mainnet.g.alchemy.com/v2/Dwhp-JulbzNpZrEHruaBSD7RRx4Eeukb"  # RPC 节点地址
    
    asyncio.run(check_nft_approval(
        NFT_CONTRACT,
        TOKEN_ID,
        WALLET_ADDRESS,
        RPC_URL
    )) 