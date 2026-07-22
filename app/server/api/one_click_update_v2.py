"""
一键更新API v2 - 使用 Orchestrator 编排层
"""
import logging
from fastapi import APIRouter, Query

from app.server.repositories.task_repository import TaskRepository
from app.server.utils.sync_window import check_sync_time

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/one-click-update", tags=["一键更新"])


@router.post("/start")
def start_update():
    """启动一键更新任务"""
    # 检查同步时间窗口
    allowed, msg = check_sync_time()
    if not allowed:
        return {
            'success': False,
            'message': msg,
            'already_running': False,
        }

    task_repo = TaskRepository()
    
    # 检查是否有正在运行的任务
    running_task = task_repo.get_running_task()
    
    if running_task:
        return {
            'success': True,
            'message': '更新任务正在进行中',
            'already_running': True,
            'task_id': running_task['task_id'],
        }
    
    # 使用 orchestrator 启动任务
    from app.server.orchestrators import get_one_click_orchestrator
    orchestrator = get_one_click_orchestrator()
    task_id = orchestrator.execute()
    
    return {'success': True, 'message': '一键更新已启动', 'task_id': task_id}


@router.get("/status")
def get_status():
    """获取更新任务状态"""
    task_repo = TaskRepository()
    running_task = task_repo.get_running_task()
    
    if running_task:
        return {
            'running': True,
            'current_step': running_task.get('current_step', 0),
            'total_steps': len(running_task.get('steps', [])),
            'step_name': running_task.get('current_stock_name', ''),
            'steps': running_task.get('steps', []),
            'error': None
        }
    
    return {
        'running': False,
        'current_step': 0,
        'total_steps': 7,
        'step_name': '',
        'steps': [],
        'error': None
    }


@router.get("/sync-time-check")
def check_sync_time_endpoint():
    """检查当前是否在允许同步的时间窗口内"""
    allowed, msg = check_sync_time()
    return {'allowed': allowed, 'message': msg}


@router.post("/recalculate-date")
def recalculate_date(target_date: str = Query(..., description="目标日期 YYYYMMDD")):
    """启动按日期重算任务"""
    task_repo = TaskRepository()
    
    # 检查是否有正在运行的任务
    running_task = task_repo.get_running_task()
    
    if running_task:
        return {
            'success': True,
            'message': '重算任务正在进行中',
            'already_running': True,
            'task_id': running_task['task_id'],
        }
    
    # 使用 orchestrator 启动任务
    from app.server.orchestrators import get_daily_recalc_orchestrator
    orchestrator = get_daily_recalc_orchestrator()
    task_id = orchestrator.execute(target_date)
    
    return {'success': True, 'message': f'{target_date} 数据重算已启动', 'already_running': False, 'task_id': task_id}
