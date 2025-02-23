# 生物密码接口文档

## 启用生物密码

### 请求信息

- **接口路径**: `/api/v1/wallets/biometric/enable/`
- **请求方法**: POST
- **Content-Type**: application/json

### 请求参数

```json
{
    "device_id": "设备唯一标识符",
    "payment_password": "支付密码"
}
```

### 参数说明

| 参数名 | 类型 | 是否必须 | 说明 |
|--------|------|----------|------|
| device_id | string | 是 | 设备的唯一标识符 |
| payment_password | string | 是 | 用户的支付密码 |

### 响应示例

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "is_enabled": true,
        "last_verified_at": "2024-02-20T10:00:00Z"
    }
}
```

### 响应参数说明

| 参数名 | 类型 | 说明 |
|--------|------|------|
| code | integer | 状态码，200表示成功 |
| message | string | 响应消息 |
| data.is_enabled | boolean | 生物密码是否已启用 |
| data.last_verified_at | string | 最后验证时间，ISO 8601格式 |

### 错误码说明

| 错误码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | 未授权或支付密码错误 |
| 500 | 服务器内部错误 |