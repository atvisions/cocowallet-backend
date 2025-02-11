# Solana 代币兑换接口文档

## 基础信息

- 基础URL: `/api/v1/solana/wallets`
- 认证方式: 不需要认证
- 请求格式: JSON
- 响应格式: JSON

## 通用请求头

```
Content-Type: application/json
Accept: application/json
```

## 1. 获取兑换报价

获取两个代币之间的兑换报价信息。

### 请求信息

- 方法: `GET`
- 路径: `/{wallet_id}/swap/quote`

### 请求参数

#### Query Parameters

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| device_id | string | 是 | 设备ID |
| from_token | string | 是 | 源代币地址 |
| to_token | string | 是 | 目标代币地址 |
| amount | string | 是 | 兑换数量 |
| slippage | string | 否 | 滑点容忍度（可选，例如："0.5"表示0.5%） |

### 请求示例

```
GET /api/v1/solana/wallets/123/swap/quote?device_id=device123&from_token=So11111111111111111111111111111111111111112&to_token=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1.5&slippage=0.5
```

### 响应示例

```json
{
    "status": "success",
    "data": {
        "from_token": {
            "address": "So11111111111111111111111111111111111111112",
            "symbol": "SOL",
            "decimals": 9,
            "amount": "1.5"
        },
        "to_token": {
            "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "symbol": "USDC",
            "decimals": 6,
            "amount": "35.25"
        },
        "price_impact": "0.12",
        "minimum_received": "35.07",
        "maximum_sent": "1.5075",
        "estimated_gas": "0.000005",
        "route": [{
            "swapInfo": {
                "ammKey": "5zvhFRN45j9oePohUQ739Z4UaSrgPoJ8NLaS2izFuX1j",
                "label": "Lifinity V2",
                "inputMint": "So11111111111111111111111111111111111111112",
                "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "inAmount": "1500000000",
                "outAmount": "35250000",
                "feeAmount": "30000",
                "feeMint": "So11111111111111111111111111111111111111112"
            },
            "percent": 100
        }],
        "exchange": "Jupiter"
    }
}
```

## 2. 执行代币兑换

使用获取到的报价执行实际的代币兑换交易。

### 请求信息

- 方法: `POST`
- 路径: `/{wallet_id}/swap/execute`

### 请求参数

#### Request Body

```json
{
    "device_id": "string",       // 必填，设备ID
    "from_token": "string",     // 必填，源代币地址
    "to_token": "string",       // 必填，目标代币地址
    "amount": "string",         // 必填，兑换数量
    "payment_password": "string", // 必填，支付密码
    "slippage": "string"        // 可选，滑点容忍度
}
```

### 请求示例

```
POST /api/v1/solana/wallets/123/swap/execute

{
    "device_id": "device123",
    "from_token": "So11111111111111111111111111111111111111112",
    "to_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "amount": "1.5",
    "slippage": "0.5"
}
```

### 响应示例

```json
{
    "status": "success",
    "data": {
        "tx_hash": "5KKsT8nq9YFgzVUC2M8GwXGRZ6PYxXsqUzBrFgBRqKwvGUE3KqXHpJKRJXmGJNxqLtYN3NNxWpwGQqkwvkcBJKwH",
        "from_token": {
            "address": "So11111111111111111111111111111111111111112",
            "symbol": "SOL",
            "decimals": 9
        },
        "to_token": {
            "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "symbol": "USDC",
            "decimals": 6
        },
        "amount_in": "1.5",
        "amount_out": "35.25",
        "price_impact": "0.12",
        "exchange": "Jupiter"
    }
}
```

## 错误响应

当请求出现错误时，将返回以下格式的响应：

```json
{
    "status": "error",
    "message": "错误描述信息"
}
```

### 可能的错误状态码

- 400 Bad Request: 请求参数错误
- 401 Unauthorized: 认证失败
- 404 Not Found: 资源不存在
- 500 Internal Server Error: 服务器内部错误

## Postman 调试建议

1. 创建新的 Collection 用于 Solana Swap API
2. 设置环境变量：
   - `base_url`: API 基础地址
   - `wallet_id`: 钱包 ID
   - `device_id`: 设备 ID

3. 调试步骤：
   1. 先调用报价接口获取兑换信息
   2. 使用获取到的信息调用执行兑换接口
   3. 检查交易哈希是否成功

4. 注意事项：
   - 确保输入的代币地址正确
   - 检查钱包余额是否足够
   - 考虑适当的滑点设置
   - 记录每次请求的响应以便排查问题