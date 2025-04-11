import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from django.conf import settings
import hashlib

def encrypt_string(text: str) -> str:
    """
    加密字符串
    
    Args:
        text: 要加密的字符串
        
    Returns:
        加密后的字符串
    """
    try:
        # 使用 SHA256 生成固定长度的密钥
        key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        
        # 创建 AES 加密器
        cipher = AES.new(key, AES.MODE_CBC)
        
        # 加密数据
        padded_data = pad(text.encode(), AES.block_size)
        encrypted_data = cipher.encrypt(padded_data)
        
        # 组合 IV 和加密数据
        encrypted_text = base64.b64encode(cipher.iv + encrypted_data).decode()
        
        return encrypted_text
        
    except Exception as e:
        raise ValueError(f"加密失败: {str(e)}")

def decrypt_string(encrypted_text: str) -> str:
    """
    解密字符串
    
    Args:
        encrypted_text: 加密后的字符串
        
    Returns:
        解密后的字符串
    """
    try:
        # 使用 SHA256 生成固定长度的密钥
        key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        
        # 解码加密数据
        encrypted_data = base64.b64decode(encrypted_text)
        
        # 提取 IV 和加密数据
        iv = encrypted_data[:AES.block_size]
        encrypted_data = encrypted_data[AES.block_size:]
        
        # 创建 AES 解密器
        cipher = AES.new(key, AES.MODE_CBC, iv)
        
        # 解密数据
        decrypted_data = cipher.decrypt(encrypted_data)
        unpadded_data = unpad(decrypted_data, AES.block_size)
        
        return unpadded_data.decode()
        
    except Exception as e:
        raise ValueError(f"解密失败: {str(e)}") 