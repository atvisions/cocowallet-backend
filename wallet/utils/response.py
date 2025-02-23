from rest_framework.response import Response
from rest_framework import status
from typing import Any, Dict, Optional, Union

def success_response(data: Any = None, message: str = "操作成功") -> Response:
    """返回成功响应
    
    Args:
        data: 响应数据
        message: 成功消息
        
    Returns:
        Response: DRF响应对象
    """
    response_data = {
        'status': 'success',
        'message': message
    }
    
    if data is not None:
        response_data['data'] = data
        
    return Response(response_data)

def error_response(
    message: str,
    error_code: Optional[Union[int, str]] = None,
    status_code: int = status.HTTP_400_BAD_REQUEST
) -> Response:
    """返回错误响应
    
    Args:
        message: 错误消息
        error_code: 错误代码
        status_code: HTTP状态码
        
    Returns:
        Response: DRF响应对象
    """
    response_data: Dict[str, Any] = {
        'status': 'error',
        'message': message
    }
    
    if error_code is not None:
        response_data['error_code'] = error_code
        
    return Response(response_data, status=status_code) 