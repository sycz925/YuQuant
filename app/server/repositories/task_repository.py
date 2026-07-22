"""
Task Repository - 任务数据访问层
"""
from typing import Dict, List, Optional
from datetime import datetime
from app.server.repositories.base import BaseRepository


class TaskRepository(BaseRepository):
    """任务管理仓库"""
    
    def __init__(self):
        super().__init__('sync_tasks')
    
    def get_running_task(self) -> Optional[Dict]:
        """获取正在运行的任务"""
        return self.collection.find_one(
            {'status': 'running'},
            sort=[('created_at', -1)]
        )
    
    def get_by_task_id(self, task_id: str) -> Optional[Dict]:
        """根据任务 ID 获取任务"""
        return self.collection.find_one(
            {'task_id': task_id}
        )
    
    def create_task(self, task_id: str, steps: List[Dict]) -> str:
        """创建带步骤的任务"""
        doc = {
            'task_id': task_id,
            'status': 'running',
            'steps': steps,
            'created_at': datetime.now(),
            'current_step': 0,
            'total_count': 0,
            'completed_count': 0,
            'failed_count': 0,
            'skipped_count': 0,
            'current_stock_name': ''
        }
        self.collection.insert_one(doc)
        return task_id
    
    def update_task_progress(self, task_id: str, **kwargs) -> None:
        """更新任务进度"""
        self.collection.update_one(
            {'task_id': task_id},
            {'$set': kwargs}
        )
    
    def update_step_progress(self, task_id: str, step_idx: int, **kwargs) -> None:
        """更新步骤进度"""
        update_dict = {}
        for key, value in kwargs.items():
            update_dict[f'steps.{step_idx}.{key}'] = value
        self.collection.update_one(
            {'task_id': task_id},
            {'$set': update_dict}
        )
    
    def complete_task(self, task_id: str, message: str = '') -> None:
        """完成任务"""
        self.collection.update_one(
            {'task_id': task_id},
            {'$set': {
                'status': 'completed',
                'message': message,
                'completed_at': datetime.now()
            }}
        )
    
    def fail_task(self, task_id: str, message: str = '') -> None:
        """失败任务"""
        self.collection.update_one(
            {'task_id': task_id},
            {'$set': {
                'status': 'failed',
                'message': message,
                'failed_at': datetime.now()
            }}
        )
    
    def cancel_task(self, task_id: str) -> None:
        """取消任务"""
        self.collection.update_one(
            {'task_id': task_id},
            {'$set': {
                'status': 'cancelled',
                'cancelled_at': datetime.now()
            }}
        )
    
    def clear_all(self) -> int:
        """清除所有任务"""
        result = self.collection.delete_many({})
        return result.deleted_count
    
    def get_tasks_by_status(self, status: str, limit: int = 10) -> List[Dict]:
        """按状态获取任务列表"""
        return list(self.collection.find(
            {'status': status},
            {'_id': 0}
        ).sort('created_at', -1).limit(limit))
