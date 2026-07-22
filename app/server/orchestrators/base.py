"""
编排器基类 - 定义通用任务编排逻辑
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 全局线程池
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="orchestrator")


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
        import uuid
        steps = self.get_steps()
        task_id = str(uuid.uuid4())
        self.task_repo.create_task(task_id, steps)
        
        # 使用线程池提交任务
        _executor.submit(self._run_wrapper, task_id, [target_date] if target_date else None)
        
        logger.info(f'[{self.__class__.__name__}] 任务 {task_id} 已提交到线程池')
        return task_id
    
    def _run_wrapper(self, task_id: str, dates: Optional[List[str]] = None) -> None:
        """线程包装器 - 确保异常被捕获"""
        try:
            self._run(task_id, dates)
        except Exception as e:
            logger.error(f'[{self.__class__.__name__}] 任务 {task_id} 异常: {e}', exc_info=True)
            try:
                self.task_repo.fail_task(task_id, f'任务异常: {str(e)[:200]}')
            except Exception:
                pass
    
    def _run(self, task_id: str, dates: Optional[List[str]] = None) -> None:
        """后台执行流程"""
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()
        steps = self.get_steps()
        
        # 如果没有指定日期列表，使用默认行为
        if not dates:
            dates = [None]
        
        logger.info(f'[{self.__class__.__name__}] 开始执行任务 {task_id}，共 {len(dates)} 个日期')
        
        for date_idx, date in enumerate(dates):
            logger.info(f'[{self.__class__.__name__}] 日期 {date_idx+1}/{len(dates)}: {date}')
            
            for step_idx, step in enumerate(steps):
                # 计算全局步骤索引
                global_step_idx = date_idx * len(steps) + step_idx
                
                # 检查任务是否已取消
                if tm.is_cancelled(task_id):
                    logger.info(f'任务 {task_id} 已取消，停止执行')
                    return
                
                step_key = step['key']
                step_name = step['name']
                
                logger.info(f'[{self.__class__.__name__}] 步骤 {step_idx+1}/{len(steps)}: {step_name}')
                
                self.task_repo.update_step_progress(task_id, global_step_idx, status='running')
                self.task_repo.update_task_progress(task_id, current_step=global_step_idx)
                
                # 启动进度同步线程
                sync_stop = threading.Event()
                sync_thread = threading.Thread(
                    target=self._sync_progress,
                    args=(task_id, global_step_idx, sync_stop),
                    daemon=True
                )
                sync_thread.start()
                
                try:
                    self.execute_step(step_key, task_id, date)
                except Exception as e:
                    logger.error(f'[{self.__class__.__name__}] 步骤 {date} {step_name} 失败: {e}', exc_info=True)
                    sync_stop.set()
                    sync_thread.join(timeout=5)
                    self.task_repo.update_step_progress(
                        task_id, global_step_idx,
                        status='failed',
                        message=str(e)[:200]
                    )
                    self.task_repo.fail_task(task_id, f'步骤失败: {str(e)[:200]}')
                    return
                finally:
                    sync_stop.set()
                    sync_thread.join(timeout=5)
                
                self.task_repo.update_step_progress(
                    task_id, global_step_idx, 
                    status='completed', 
                    message=f'{date} {step_name}完成'
                )
                logger.info(f'[{self.__class__.__name__}] 步骤 {step_idx+1}/{len(steps)}: {step_name} 完成')
            
            logger.info(f'[{self.__class__.__name__}] 日期 {date} 全部完成')
        
        self.task_repo.complete_task(task_id, '全部完成')
        logger.info(f'[{self.__class__.__name__}] 任务 {task_id} 全部完成，共处理 {len(dates)} 个日期')
    
    def _sync_progress(self, task_id: str, step_idx: int, stop_event: threading.Event) -> None:
        """同步顶层进度到步骤级进度（只同步 completed_count，不覆盖 total_count）"""
        from app.data.db import get_db
        
        db = get_db()
        while not stop_event.is_set():
            try:
                # 读取顶层进度
                task = db['sync_tasks'].find_one(
                    {'task_id': task_id},
                    {'_id': 0, 'completed_count': 1, 'current_stock_name': 1}
                )
                if task:
                    # 同步到步骤进度（只更新 completed_count，不覆盖 total_count）
                    db['sync_tasks'].update_one(
                        {'task_id': task_id},
                        {'$set': {
                            f'steps.{step_idx}.completed_count': task.get('completed_count', 0),
                            f'steps.{step_idx}.message': task.get('current_stock_name', '')
                        }}
                    )
            except Exception:
                pass
            stop_event.wait(timeout=3)
    
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
