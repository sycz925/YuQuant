"""
后台任务管理器 - 使用 MongoDB 持久化，支持多 worker/多进程共享状态
"""
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, asdict
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class FailedStock:
    """失败的股票信息"""
    stock_code: str
    stock_name: str
    error: str


def _sync_task_to_doc(task_id: str, status: str, 
                       sources: Optional[Dict[str, int]] = None,
                       message: Optional[str] = None,
                       error: Optional[str] = None,
                       created_at: Optional[str] = None,
                       updated_at: Optional[str] = None,
                       steps: Optional[List[Dict]] = None,
                       current_step: int = 0) -> Dict:
    """把任务参数转换为 MongoDB 文档格式"""
    now = datetime.utcnow().isoformat()
    return {
        'task_id': task_id,
        'status': status,
        'sources': sources or {},
        'message': message,
        'error': error,
        'created_at': created_at or now,
        'updated_at': updated_at or now,
    }


class TaskManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def _get_db(self):
        from .db import get_db
        return get_db()

    def _get_col(self):
        db = self._get_db()
        col = db['sync_tasks']
        # 确保有索引
        try:
            col.create_index('task_id', unique=True)
            col.create_index([('updated_at', -1)])
        except Exception:
            pass
        return col

    def create_task(self) -> str:
        """创建一个新任务"""
        task_id = str(uuid.uuid4())
        col = self._get_col()
        now = datetime.utcnow().isoformat()
        doc = {
            'task_id': task_id,
            'status': TaskStatus.PENDING.value,
            'sources': {},
            'message': None,
            'error': None,
            'created_at': now,
            'updated_at': now,
            'steps': [],
            'current_step': 0,
        }
        col.insert_one(doc)
        return task_id

    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务信息"""
        col = self._get_col()
        doc = col.find_one({'task_id': task_id}, {'_id': 0})
        return doc

    def get_task_dict(self, task_id: str) -> Optional[Dict]:
        """获取任务信息（字典格式，兼容旧接口）"""
        task = self.get_task(task_id)
        if task:
            task['failed_stocks'] = [
                fs if isinstance(fs, dict) else {
                    'stock_code': getattr(fs, 'stock_code', ''),
                    'stock_name': getattr(fs, 'stock_name', ''),
                    'error': getattr(fs, 'error', '')
                }
                for fs in (task.get('failed_stocks') or [])
            ]
            return task
        return None

    def update_task_progress(self, task_id: str,
                             current_stock: Optional[str] = None,
                             current_stock_name: Optional[str] = None,
                             increment_completed: int = 0,
                             increment_failed: int = 0,
                             increment_skipped: int = 0,
                             total_count: Optional[int] = None,
                             completed_count: Optional[int] = None,
                             sources: Optional[Dict[str, int]] = None,
                             failed_stock: Optional[Dict] = None):
        """更新任务进度（原子更新）
        使用 MongoDB 的原子操作 ($set, $inc, $push) 确保多线程下的数据一致性。
        """
        col = self._get_col()

        # 检查是否为终态（如果是则不更新，避免终态被覆盖）
        # 注意：这里可能存在极小的竞态，但 update_one 的 query 增加了状态过滤可以彻底解决

        update_doc: Dict[str, Any] = {
            '$set': {
                'status': TaskStatus.RUNNING.value,
                'updated_at': datetime.utcnow().isoformat(),
            }
        }

        if current_stock is not None:
            update_doc['$set']['current_stock'] = current_stock
        if current_stock_name is not None:
            update_doc['$set']['current_stock_name'] = current_stock_name
        if total_count is not None:
            update_doc['$set']['total_count'] = max(0, int(total_count))
        if completed_count is not None:
            update_doc['$set']['completed_count'] = max(0, int(completed_count))

        # $inc 部分
        inc_fields = {}
        if increment_completed and completed_count is None:
            inc_fields['completed_count'] = int(increment_completed)
        if increment_failed:
            inc_fields['failed_count'] = int(increment_failed)
        if increment_skipped:
            inc_fields['skipped_count'] = int(increment_skipped)

        if sources:
            for k, v in sources.items():
                # 注意：MongoDB 支持 $inc: {"sources.pytdx": 1}
                inc_fields[f'sources.{k}'] = int(v)

        if inc_fields:
            update_doc['$inc'] = inc_fields

        # $push 部分
        if failed_stock:
            update_doc['$push'] = {
                'failed_stocks': {
                    'stock_code': failed_stock.get('stock_code', ''),
                    'stock_name': failed_stock.get('stock_name', ''),
                    'error': failed_stock.get('error', '未知错误'),
                    'time': datetime.utcnow().isoformat()
                }
            }

        # 核心：只更新非终态的任务
        col.update_one(
            {
                'task_id': task_id,
                'status': {'$nin': [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value]}
            },
            update_doc
        )

    def complete_task(self, task_id: str, message: str, sources: Optional[Dict[str, int]] = None):
        """完成任务：设置 COMPLETED 状态"""
        col = self._get_col()

        # 获取总数以对齐已完成数
        current = col.find_one({'task_id': task_id}, {'total_count': 1})
        total_count = current.get('total_count', 0) if current else 0

        set_fields = {
            'status': TaskStatus.COMPLETED.value,
            'message': message,
            'current_stock': None,
            'current_stock_name': None,
            'completed_count': int(total_count),
            'updated_at': datetime.utcnow().isoformat()
        }

        update_doc: Dict[str, Any] = {'$set': set_fields}

        if sources:
            inc_fields = {f'sources.{k}': int(v) for k, v in sources.items()}
            update_doc['$inc'] = inc_fields

        col.update_one({'task_id': task_id}, update_doc)

    def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        col = self._get_col()

        set_fields = {
            'status': TaskStatus.FAILED.value,
            'error': error,
            'current_stock': None,
            'current_stock_name': None,
            'updated_at': datetime.utcnow().isoformat()
        }

        col.update_one({'task_id': task_id}, {'$set': set_fields})

    def cancel_task(self, task_id: str):
        """取消任务：设置 CANCELLED 状态，工作线程会在下次检查时停止"""
        col = self._get_col()
        col.update_one(
            {
                'task_id': task_id,
                'status': {'$nin': [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value]}
            },
            {'$set': {
                'status': TaskStatus.CANCELLED.value,
                'message': '用户取消',
                'current_stock': None,
                'current_stock_name': None,
                'updated_at': datetime.utcnow().isoformat()
            }}
        )

    def is_cancelled(self, task_id: str) -> bool:
        """检查任务是否已被取消"""
        col = self._get_col()
        doc = col.find_one({'task_id': task_id}, {'status': 1, '_id': 0})
        return doc is not None and doc.get('status') == TaskStatus.CANCELLED.value

    def create_task_with_steps(self, steps: List[Dict]) -> str:
        """创建带步骤的任务"""
        task_id = str(uuid.uuid4())
        col = self._get_col()
        now = datetime.utcnow().isoformat()
        doc = {
            'task_id': task_id,
            'status': TaskStatus.RUNNING.value,
            'sources': {},
            'message': None,
            'error': None,
            'created_at': now,
            'updated_at': now,
            'steps': steps,
            'current_step': 0,
        }
        col.insert_one(doc)
        return task_id

    def start_step(self, task_id: str, step_index: int):
        """开始一个步骤"""
        col = self._get_col()
        doc = col.find_one({'task_id': task_id}, {'_id': 0, 'steps': 1})
        step_name = doc['steps'][step_index]['name'] if doc and 'steps' in doc and step_index < len(doc['steps']) else f'步骤{step_index + 1}'
        col.update_one(
            {'task_id': task_id},
            {'$set': {
                'current_step': step_index,
                'current_stock_name': f"正在执行: {step_name}",
                'updated_at': datetime.utcnow().isoformat(),
                f'steps.{step_index}.status': 'running',
                f'steps.{step_index}.completed_count': 0,
                f'steps.{step_index}.failed_count': 0,
                f'steps.{step_index}.skipped_count': 0,
            }}
        )

    def complete_step(self, task_id: str, step_index: int, message: str = ''):
        """完成一个步骤"""
        col = self._get_col()
        doc = col.find_one({'task_id': task_id}, {'_id': 0, 'steps': 1})
        if doc and 'steps' in doc and step_index < len(doc['steps']):
            step = doc['steps'][step_index]
            step_name = step['name']
            total_count = step.get('total_count', 1)
        else:
            step_name = f'步骤{step_index + 1}'
            total_count = 1
        col.update_one(
            {'task_id': task_id},
            {'$set': {
                'current_stock_name': f"完成: {step_name}",
                'updated_at': datetime.utcnow().isoformat(),
                f'steps.{step_index}.status': 'completed',
                f'steps.{step_index}.completed_count': total_count,
                f'steps.{step_index}.message': message
            }}
        )

    def fail_step(self, task_id: str, step_index: int, error: str):
        """失败一个步骤"""
        col = self._get_col()
        doc = col.find_one({'task_id': task_id}, {'_id': 0, 'steps': 1})
        step_name = doc['steps'][step_index]['name'] if doc and 'steps' in doc and step_index < len(doc['steps']) else f'步骤{step_index + 1}'
        col.update_one(
            {'task_id': task_id},
            {'$set': {
                'current_stock_name': f"失败: {step_name}",
                'updated_at': datetime.utcnow().isoformat(),
                'error': error,
                f'steps.{step_index}.status': 'failed',
                f'steps.{step_index}.error': error
            }}
        )



# 全局单例
_task_manager = None


def get_task_manager() -> TaskManager:
    """获取任务管理器单例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager

