"""
编排器基类 - 定义通用任务编排逻辑
"""
import logging
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaseOrchestrator(ABC):
    """编排器基类"""
    
    def __init__(self, task_repo=None):
        from app.server.repositories import get_task_repo
        self.task_repo = task_repo or get_task_repo()
    
    @abstractmethod
    def get_steps(self) -> List[Dict[str, str]]:
        """获取步骤定义"""
        pass
    
    @abstractmethod
    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str]) -> None:
        """执行单个步骤"""
        pass
    
    def execute(self, target_date: Optional[str] = None) -> str:
        """
        执行编排流程
        :param target_date: 目标日期，None 表示最新
        :return: task_id
        """
        steps = self.get_steps()
        task_id = self.task_repo.create_task(steps)
        
        thread = threading.Thread(
            target=self._run,
            args=(task_id, target_date),
            daemon=True
        )
        thread.start()
        
        return task_id
    
    def _run(self, task_id: str, target_date: Optional[str]) -> None:
        """后台执行流程"""
        steps = self.get_steps()
        
        for i, step in enumerate(steps):
            step_key = step['key']
            step_name = step['name']
            
            self.task_repo.update_step_progress(task_id, i, status='running')
            self.task_repo.update_task_progress(task_id, current_step=i)
            
            try:
                self.execute_step(step_key, task_id, target_date)
                self.task_repo.update_step_progress(
                    task_id, i, 
                    status='completed', 
                    message=f'{step_name}完成'
                )
            except Exception as e:
                logger.error(f'步骤 {step_name} 失败: {e}')
                self.task_repo.update_step_progress(
                    task_id, i,
                    status='failed',
                    message=str(e)[:200]
                )
                self.task_repo.fail_task(task_id, f'步骤失败: {str(e)[:200]}')
                return
        
        self.task_repo.complete_task(task_id, '全部完成')
        logger.info(f'[{self.__class__.__name__}] 全部完成')
    
    def _make_callback(self, task_id: str, step_idx: int) -> Callable:
        """构造进度回调闭包"""
        def callback(current: int, total: int, message: str = '') -> None:
            self.task_repo.update_step_progress(
                task_id, step_idx,
                completed_count=current,
                total_count=total,
                message=message
            )
        return callback
