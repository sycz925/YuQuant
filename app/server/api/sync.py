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


def _run_sync_task(task_id: str, end_date: str, max_workers: int = 16, is_external: bool = False):
    """后台任务：逐天回溯同步日线数据"""
    try:
        dm = get_data_manager()
        tm = get_task_manager()
        
        stock_df = dm.get_stock_list()
        if stock_df.empty:
            tm.fail_task(task_id, "没有找到股票数据，请先同步股票基础信息")
            return
        
        # 直接从数据库查询启用的股票代码
        db = get_db()
        stock_codes = [
            doc['stock_code'] for doc in db['stock_basics'].find(
                {'is_disable': {'$ne': True}},
                {'_id': 0, 'stock_code': 1}
            )
        ]
        logger.info(f"获取到 {len(stock_codes)} 只启用股票")

        total = len(stock_codes)
        logger.info(f"开始逐天回溯同步股票日线数据，共 {total} 只，线程数: {max_workers}")
        
        result = dm.sync_daily_data(
            stock_codes=stock_codes,
            end_date=end_date,
            task_id=task_id,
            max_workers=max_workers,
            is_external=is_external
        )
        
        source_msg = ', '.join([f"{k}: {v}" for k, v in result.get('sources', {}).items()])
        message = f"同步完成，共 {total} 只，成功 {result.get('success', 0)}，跳过 {result.get('skipped', 0)}，失败 {result.get('fail', 0)}。数据源: {source_msg or '无'}"
        logger.info(message)

        # 同步完成后计算涨幅字段（只算最新日期）
        logger.info("开始计算涨幅字段...")
        try:
            chg_result = dm.calculate_chg_fields(target='stock')
            logger.info(f"涨幅字段计算完成: {chg_result}")
        except Exception as e:
            logger.error(f"计算涨幅字段失败: {e}")

        if not is_external:
            tm.complete_task(task_id, message, result.get('sources', {}))

        # 刷新交易日缓存
        try:
            from app.server.cache import refresh_trade_dates
            refresh_trade_dates()
        except Exception:
            pass

        # 注意：不再在这里预计算market_daily
        # market_daily应该在一键更新的最后一步才生成
        # 这里只刷新交易日缓存
        try:
            from app.server.cache import refresh_trade_dates
            refresh_trade_dates()
        except Exception as e:
            logger.error(f"刷新交易日缓存失败: {e}")

    except Exception as e:
        logger.exception(f"同步所有股票日线数据失败: {e}")
        tm = get_task_manager()
        tm.fail_task(task_id, f"同步失败: {str(e)}")


@router.post("/daily/all")
def sync_all_daily_data(request: SyncRequest = SyncRequest()):
    """同步所有股票的日线数据 — 逐天回溯模式（后台任务）"""
    try:
        allowed, msg = _check_sync_time()
        if not allowed:
            return {"success": False, "message": msg, "task_id": None}

        dm = get_data_manager()
        tm = get_task_manager()

        end_date = request.end_date or datetime.now().strftime("%Y%m%d")

        # 直接从数据库查询启用的股票代码
        db = get_db()
        stock_codes = [
            doc['stock_code'] for doc in db['stock_basics'].find(
                {'is_disable': {'$ne': True}},
                {'_id': 0, 'stock_code': 1}
            )
        ]
        if not stock_codes:
            raise HTTPException(status_code=404, detail="没有找到股票数据，请先同步股票基础信息")
        
        logger.info(f"获取到 {len(stock_codes)} 只启用股票")

        # 最小上市天数过滤
        min_days = request.min_days
        if min_days and min_days > 0:
            from datetime import datetime as dt
            end_date_obj = dt.strptime(end_date, "%Y%m%d")
            from app.data.db import get_db
            db = get_db()
            basics_cursor = db['stock_basics'].find(
                {}, {'_id': 0, 'stock_code': 1, 'list_date': 1}
            )
            list_date_map = {d['stock_code']: d.get('list_date') for d in basics_cursor}
            filtered_codes = []
            for code in stock_codes:
                list_date = list_date_map.get(code)
                if list_date:
                    try:
                        list_date_obj = dt.strptime(str(list_date), "%Y%m%d")
                        if (end_date_obj - list_date_obj).days >= min_days:
                            filtered_codes.append(code)
                    except Exception:
                        filtered_codes.append(code)
                else:
                    filtered_codes.append(code)
            logger.info(f"过滤股票：原始 {len(stock_codes)} 只，过滤后 {len(filtered_codes)} 只（最小上市天数: {min_days}）")
            stock_codes = filtered_codes

        # 检查是否有正在运行的同步任务
        from app.data.db import get_db
        db = get_db()
        running_task = db['sync_tasks'].find_one(
            {'status': 'running', 'current_stock_name': {'$regex': '同步|sync'}},
            sort=[('created_at', -1)]
        )
        
        if running_task:
            # 复用正在运行的任务
            task_id = running_task['task_id']
            return {
                "success": True,
                "task_id": task_id,
                "message": "任务正在运行中，共用task_id",
                "total_count": running_task.get('total_count', 0),
                "already_running": True
            }
        
        task_id = tm.create_task()

        thread = threading.Thread(
            target=_run_sync_task,
            args=(task_id, end_date, request.max_workers)
        )
        thread.daemon = True
        thread.start()

        return {
            "success": True,
            "task_id": task_id,
            "message": f"逐天回溯同步已启动，共 {len(stock_codes)} 只股票",
            "total_count": len(stock_codes)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动同步任务失败: {e}")
        return {"success": False, "message": f"启动同步失败: {str(e)}"}


@router.get("/task/{task_id}")
def get_task_status(task_id: str):
    """获取任务状态"""
    tm = get_task_manager()
    task = tm.get_task_dict(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return task


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


@router.post("/derived_fields")
def sync_derived_fields(target: str = "all", trade_date: Optional[str] = None, backfill: bool = False):
    """
    计算冗余字段（MA、VOL_MA、CHG、涨跌幅、百分位）

    Args:
        target: 'all' - 全部, 'stock' - 仅个股, 'sector' - 仅板块
        trade_date: 指定日期 YYYYMMDD，None则计算最新日期
        backfill: True则回刷所有历史数据
    """
    try:
        dm = get_data_manager()
        result = dm.calculate_all_derived_fields(target=target, trade_date=trade_date, backfill=backfill)

        stock_result = result.get('stock', {})
        sector_result = result.get('sector', {})

        stock_dates = stock_result.get('derived', {}).get('dates', 0) + stock_result.get('percentile', {}).get('dates', 0)
        sector_dates = sector_result.get('derived', {}).get('dates', 0) + sector_result.get('percentile', {}).get('dates', 0)
        stock_updates = stock_result.get('derived', {}).get('updates', 0) + stock_result.get('percentile', {}).get('updates', 0)
        sector_updates = sector_result.get('derived', {}).get('updates', 0) + sector_result.get('percentile', {}).get('updates', 0)

        return {
            "success": True,
            "message": f"冗余字段计算完成，个股: {stock_dates} 天 {stock_updates} 条更新，板块: {sector_dates} 天 {sector_updates} 条更新",
            "stock": stock_result,
            "sector": sector_result
        }
    except Exception as e:
        logger.exception(f"计算冗余字段失败: {e}")
        return {
            "success": False,
            "message": f"计算冗余字段失败: {str(e)}"
        }
