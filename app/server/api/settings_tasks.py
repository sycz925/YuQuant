"""
Settings Tasks API - 设置页面任务接口
提供统一的 steps 任务模式接口
"""
import logging
from fastapi import APIRouter, Query
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings-tasks", tags=["设置任务"])


def _check_running_tasks(task_type: str):
    """检查是否有正在运行的同类任务"""
    from app.server.repositories import get_task_repo
    return get_task_repo().find_running_by_stock_name(task_type)


@router.post("/sync-indices")
def sync_indices(max_workers: Optional[int] = Query(4)):
    """同步指数数据（steps 任务模式）"""
    try:
        from app.server.api.sync import _check_sync_time
        allowed, msg = _check_sync_time()
        if not allowed:
            return {"success": False, "message": msg}

        # 检查是否有正在运行的任务
        running = _check_running_tasks("指数")
        if running:
            return {"success": True, "task_id": running['task_id'], "already_running": True}

        from app.server.orchestrators.settings_orchestrator import SettingsOrchestrator
        orchestrator = SettingsOrchestrator()
        task_id = orchestrator.execute('sync_indices', max_workers=max_workers)

        return {"success": True, "task_id": task_id, "message": "指数同步已启动"}
    except Exception as e:
        logger.error(f"启动指数同步失败: {e}")
        return {"success": False, "message": str(e)[:200]}


@router.post("/sync-daily")
def sync_daily(max_workers: Optional[int] = Query(16), min_days: Optional[int] = Query(200)):
    """同步个股日线数据（steps 任务模式）"""
    try:
        from app.server.api.sync import _check_sync_time
        allowed, msg = _check_sync_time()
        if not allowed:
            return {"success": False, "message": msg}

        # 检查是否有正在运行的任务
        running = _check_running_tasks("个股")
        if running:
            return {"success": True, "task_id": running['task_id'], "already_running": True}

        from app.server.orchestrators.settings_orchestrator import SettingsOrchestrator
        orchestrator = SettingsOrchestrator()
        task_id = orchestrator.execute('sync_daily', max_workers=max_workers, min_days=min_days)

        return {"success": True, "task_id": task_id, "message": "个股同步已启动"}
    except Exception as e:
        logger.error(f"启动个股同步失败: {e}")
        return {"success": False, "message": str(e)[:200]}


@router.post("/calculate-rps")
def calculate_rps(target: str = Query('stock'), max_workers: Optional[int] = Query(16), min_days: Optional[int] = Query(200)):
    """计算RPS（steps 任务模式）"""
    try:
        from app.server.orchestrators.settings_orchestrator import SettingsOrchestrator
        orchestrator = SettingsOrchestrator()

        task_type = 'calculate_rps' if target == 'stock' else 'calculate_sector_rps'
        task_id = orchestrator.execute(task_type, max_workers=max_workers, min_days=min_days)

        return {"success": True, "task_id": task_id, "message": f"{target} RPS计算已启动"}
    except Exception as e:
        logger.error(f"启动RPS计算失败: {e}")
        return {"success": False, "message": str(e)[:200]}


@router.post("/sync-sectors")
def sync_sectors(max_workers: Optional[int] = Query(16)):
    """同步板块数据（steps 任务模式）"""
    try:
        from app.server.api.sync import _check_sync_time
        allowed, msg = _check_sync_time()
        if not allowed:
            return {"success": False, "message": msg}

        # 检查是否有正在运行的任务
        running = _check_running_tasks("板块")
        if running:
            return {"success": True, "task_id": running['task_id'], "already_running": True}

        from app.server.orchestrators.settings_orchestrator import SettingsOrchestrator
        orchestrator = SettingsOrchestrator()
        task_id = orchestrator.execute('sync_sectors', max_workers=max_workers)

        return {"success": True, "task_id": task_id, "message": "板块同步已启动"}
    except Exception as e:
        logger.error(f"启动板块同步失败: {e}")
        return {"success": False, "message": str(e)[:200]}


@router.post("/sync-index-pe")
def sync_index_pe(token: Optional[str] = Query(None)):
    """同步指数PE数据（steps 任务模式）"""
    try:
        # 检查是否有正在运行的任务
        running = _check_running_tasks("PE")
        if running:
            return {"success": True, "task_id": running['task_id'], "already_running": True}

        from app.server.orchestrators.settings_orchestrator import SettingsOrchestrator
        orchestrator = SettingsOrchestrator()
        task_id = orchestrator.execute('sync_index_pe', token=token)

        return {"success": True, "task_id": task_id, "message": "PE同步已启动"}
    except Exception as e:
        logger.error(f"启动PE同步失败: {e}")
        return {"success": False, "message": str(e)[:200]}


@router.post("/precompute-base")
def precompute_base():
    """预计算基础数据（steps 任务模式）"""
    try:
        # 检查是否有正在运行的任务
        running = _check_running_tasks("预计算")
        if running:
            return {"success": True, "task_id": running['task_id'], "already_running": True}

        from app.server.orchestrators.settings_orchestrator import SettingsOrchestrator
        orchestrator = SettingsOrchestrator()
        task_id = orchestrator.execute('precompute_base')

        return {"success": True, "task_id": task_id, "message": "预计算已启动"}
    except Exception as e:
        logger.error(f"启动预计算失败: {e}")
        return {"success": False, "message": str(e)[:200]}


# 任务状态查询统一使用 /calendar/task/{task_id}
