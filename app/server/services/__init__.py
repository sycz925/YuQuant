"""
Services - 业务逻辑层
处理路由层和数据层之间的业务逻辑
"""
from app.server.services.data_service import DataService, get_data_service

__all__ = [
    'DataService',
    'get_data_service',
]
