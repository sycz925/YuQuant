"""
数据同步API
"""
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.data.manager import get_data_manager
from app.data.task_manager import get_task_manager
from app.data.db import get_db
from app.server.models import SyncRequest, SyncResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _check_sync_time():
    """检查当前是否在允许同步的时间窗口内
    非交易日：全天可同步
    交易日：盘中 11:30-13:00，盘后 16:00-23:59
    返回: (allowed: bool, message: str)
    """
    from app.server.utils.sync_window import check_sync_time
    return check_sync_time()


@router.post("/basics", response_model=SyncResponse)
def sync_stock_basics():
    """同步股票基础信息"""
    try:
        dm = get_data_manager()
        count = dm.sync_stock_basics()
        return SyncResponse(
            success=True,
            message=f"股票基础信息同步成功，共 {count} 只",
            success_count=count,
            fail_count=0
        )
    except Exception as e:
        logger.error(f"同步股票基础信息失败: {e}")
        raise HTTPException(status_code=500, detail="同步股票基础信息失败")


@router.post("/daily", response_model=SyncResponse)
def sync_daily_data(request: SyncRequest = SyncRequest()):
    """同步日线数据"""
    try:
        dm = get_data_manager()

        # 设置默认日期
        if not request.end_date:
            request.end_date = datetime.now().strftime("%Y%m%d")
        if not request.start_date:
            request.start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

        # 执行同步
        result = dm.sync_daily_data(
            stock_codes=request.stock_codes or ["688279"],
            start_date=request.start_date,
            end_date=request.end_date,
            max_workers=request.max_workers or 8
        )

        success_count = result.get('success', 0)
        fail_count = result.get('fail', 0)
        skipped_count = result.get('skipped', 0)
        sources = result.get('sources', {})
        source_msg = ', '.join([f"{k}: {v}" for k, v in sources.items()])

        return SyncResponse(
            success=True,
            message=f"日线数据同步完成，成功 {success_count} 只，失败 {fail_count} 只，跳过 {skipped_count} 只。数据源: {source_msg or '无'}",
            success_count=success_count,
            fail_count=fail_count
        )

    except Exception as e:
        logger.error(f"同步日线数据失败: {e}")
        return SyncResponse(
            success=False,
            message=f"同步失败: {str(e)}"
        )


@router.delete("/task/{task_id}")
def cancel_task(task_id: str):
    """取消正在运行的任务"""
    tm = get_task_manager()
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get('status') in ('completed', 'failed', 'cancelled'):
        return {"success": True, "message": f"任务已处于 {task['status']} 状态，无需取消"}
    tm.cancel_task(task_id)
    return {"success": True, "message": "任务取消请求已发送，工作线程将在下次检查时停止"}


@router.post("/patch_is_final")
def patch_is_final():
    """批量修复 daily_data 集合中的 is_final 字段。

    - 今天之前的历史数据 → is_final=True（已收盘）
    - 今天以及未来的数据 → is_final=False（可能为半成品，需收盘后再覆盖）
    """
    try:
        from app.data.db import bulk_patch_is_final
        result = bulk_patch_is_final()
        return {
            "success": True,
            "message": f"修复完成，历史数据标记 {result['patched_final']} 条，今日/未来数据标记 {result['patched_not_final']} 条，总计 {result['total']} 条（今日={result['today']}）",
            "patched_final": result['patched_final'],
            "patched_not_final": result['patched_not_final'],
            "total": result['total'],
            "today": result['today']
        }
    except Exception as e:
        logger.error(f"修复 is_final 失败: {e}")
        return {
            "success": False,
            "message": f"修复 is_final 失败: {str(e)}"
        }


