"""
System Config Repository - 系统配置数据访问层
"""
from app.server.repositories.base import BaseRepository


class SystemConfigRepository(BaseRepository):
    """系统配置（system_config 集合）"""

    def __init__(self):
        super().__init__('system_config')

    def get_config(self, key: str, default=None):
        """获取配置值，不存在则返回 default"""
        doc = self.collection.find_one({'key': key}, {'_id': 0})
        return doc.get('value', default) if doc else default

    def set_config(self, key: str, value):
        """设置配置值（upsert）"""
        from datetime import datetime
        self.collection.update_one(
            {'key': key},
            {'$set': {'key': key, 'value': value, 'update_time': datetime.now()}},
            upsert=True
        )
