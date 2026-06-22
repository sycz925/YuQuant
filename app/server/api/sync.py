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
from app.server.models import SyncRequest, SyncResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


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


def _run_sync_task(task_id: str, start_date: str, end_date: str, max_workers: int = 16):
    """后台任务：使用多线程同步日线数据"""
    try:
        dm = get_data_manager()
        tm = get_task_manager()
        
        # 获取所有股票代码和名称
        stock_df = dm.get_stock_list()
        if stock_df.empty:
            tm.fail_task(task_id, "没有找到股票数据，请先同步股票基础信息")
            return
        
        stock_codes = stock_df['stock_code'].tolist()

        # 排除禁用同步的股票
        from app.server.api.exclusions import get_excluded_set
        excluded = get_excluded_set('stock', 'sync')
        if excluded:
            before = len(stock_codes)
            stock_codes = [c for c in stock_codes if c not in excluded]
            logger.info(f"排除 {before - len(stock_codes)} 只禁用股票，实际同步 {len(stock_codes)} 只")

        total = len(stock_codes)
        
        logger.info(f"开始多线程同步股票日线数据，共 {total} 只，线程数: {max_workers}，日期范围: {start_date} - {end_date}")
        
        # 使用 manager 的多线程同步方法
        result = dm.sync_daily_data(
            stock_codes=stock_codes,
            start_date=start_date,
            end_date=end_date,
            task_id=task_id,
            max_workers=max_workers
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

        tm.complete_task(task_id, message, result.get('sources', {}))

        # 刷新交易日缓存
        try:
            from app.server.cache import refresh_trade_dates
            refresh_trade_dates()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"同步所有股票日线数据失败: {e}")
        import traceback
        traceback.print_exc()
        tm = get_task_manager()
        tm.fail_task(task_id, f"同步失败: {str(e)}")


@router.post("/daily/all")
def sync_all_daily_data(request: SyncRequest = SyncRequest()):
    """同步所有股票的日线数据（后台任务）"""
    try:
        dm = get_data_manager()
        tm = get_task_manager()

        # 设置默认日期 - end_date 默认今天，start_date 从请求参数获取（无默认值）
        if not request.end_date:
            request.end_date = datetime.now().strftime("%Y%m%d")
        if not request.start_date:
            request.start_date = "20180101"

        # 获取所有股票代码
        stock_df = dm.get_stock_list()
        if stock_df.empty:
            raise HTTPException(status_code=404, detail="没有找到股票数据，请先同步股票基础信息")
        
        stock_codes = stock_df['stock_code'].tolist()

        # 排除禁用同步的股票
        from app.server.api.exclusions import get_excluded_set
        excluded = get_excluded_set('stock', 'sync')
        if excluded:
            before = len(stock_codes)
            stock_codes = [c for c in stock_codes if c not in excluded]
            logger.info(f"排除 {before - len(stock_codes)} 只禁用股票，实际同步 {len(stock_codes)} 只")

        # 如果指定了最小上市天数，过滤不满足条件的股票
        min_days = request.min_days
        if min_days and min_days > 0:
            from datetime import datetime as dt
            end_date_obj = dt.strptime(request.end_date, "%Y%m%d")
            
            # 从stock_basics获取上市日期（比查询daily_data快100倍）
            from app.data.db import get_db
            db = get_db()
            
            # 批量获取上市日期
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
                        days_listed = (end_date_obj - list_date_obj).days
                        if days_listed >= min_days:
                            filtered_codes.append(code)
                    except:
                        filtered_codes.append(code)
                else:
                    # 没有上市日期的股票也加入
                    filtered_codes.append(code)
            
            logger.info(f"过滤股票：原始 {len(stock_codes)} 只，过滤后 {len(filtered_codes)} 只（最小上市天数: {min_days}）")
            stock_codes = filtered_codes

        # 创建任务
        task_id = tm.create_task(len(stock_codes))

        # 在后台线程中执行同步
        thread = threading.Thread(
            target=_run_sync_task,
            args=(task_id, request.start_date, request.end_date, request.max_workers)
        )
        thread.daemon = True
        thread.start()

        return {
            "success": True,
            "task_id": task_id,
            "message": f"后台同步任务已启动，共 {len(stock_codes)} 只股票需要同步，线程数: {request.max_workers}",
            "total_count": len(stock_codes)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动同步任务失败: {e}")
        return {
            "success": False,
            "message": f"启动同步失败: {str(e)}"
        }


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
        logger.error(f"计算冗余字段失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"计算冗余字段失败: {str(e)}"
        }
