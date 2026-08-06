"""
ETF数据API
"""
import logging
import threading
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
import pandas as pd

from app.data.manager import get_data_manager
from app.data.db import get_db, get_collection, get_daily_data
from app.server.models import (
    EtfBasic, EtfListItem, EtfListResponse, DailyDataResponse, DailyBar
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/etf", tags=["etf"])

# 全局线程池
_executor = None
_executor_lock = threading.Lock()


def _get_executor():
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                from concurrent.futures import ThreadPoolExecutor
                _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="etf_sync")
    return _executor


@router.get("", response_model=EtfListResponse)
def get_etf_list(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    sort_by: Optional[str] = Query(None, description="排序字段"),
    sort_order: Optional[str] = Query("desc", description="排序方向"),
    rps_red: Optional[str] = Query(None, description="RPS红筛选: one/two/three")
):
    """获取ETF列表（含最新行情数据）"""
    try:
        dm = get_data_manager()
        df = dm.get_etf_list()

        if df.empty:
            return EtfListResponse(total=0, data=[])

        # 搜索过滤
        if keyword:
            keyword_lower = keyword.lower()
            mask = (
                df["code"].str.lower().str.contains(keyword_lower, na=False) |
                df["name"].str.lower().str.contains(keyword_lower, na=False)
            )
            df = df[mask]

        # 获取每个ETF的最新日线数据
        etf_coll = get_collection('etf')
        items = []

        for _, row in df.iterrows():
            code = row["code"]
            name = row["name"]

            latest = etf_coll.find_one(
                {'stock_code': code, 'close': {'$gt': 0}},
                sort=[('trade_date', -1)],
                projection={'close': 1, 'chg_pct': 1, 'chg_5d': 1, 'chg_10d': 1,
                            'chg_20d': 1, 'chg_50d': 1, 'chg_120d': 1,
                            'rps_10': 1, 'rps_20': 1, 'rps_50': 1, '_id': 0}
            )

            if latest:
                item = EtfListItem(
                    code=code,
                    name=name,
                    close=latest.get('close'),
                    change_pct=latest.get('chg_pct'),
                    chg_5d=latest.get('chg_5d'),
                    chg_10d=latest.get('chg_10d'),
                    chg_20d=latest.get('chg_20d'),
                    chg_50d=latest.get('chg_50d'),
                    chg_120d=latest.get('chg_120d'),
                    rps_10=latest.get('rps_10'),
                    rps_20=latest.get('rps_20'),
                    rps_50=latest.get('rps_50'),
                )
                items.append(item)
            else:
                items.append(EtfListItem(code=code, name=name))

        # RPS红筛选
        if rps_red in ('one', 'two', 'three'):
            rps_threshold = 87
            filtered = []
            for item in items:
                rps_values = [v for v in (item.rps_10, item.rps_20, item.rps_50) if v is not None]
                red_count = sum(1 for v in rps_values if v > rps_threshold)
                if rps_red == 'one' and red_count >= 1:
                    filtered.append(item)
                elif rps_red == 'two' and red_count >= 2:
                    filtered.append(item)
                elif rps_red == 'three' and red_count >= 3:
                    filtered.append(item)
            items = filtered

        # 排序
        if sort_by and sort_by in ('change_pct', 'chg_5d', 'chg_10d', 'chg_20d', 'chg_50d', 'chg_120d', 'close', 'rps_10', 'rps_20', 'rps_50'):
            reverse = sort_order != 'asc'
            items.sort(key=lambda x: getattr(x, sort_by) or 0, reverse=reverse)

        return EtfListResponse(total=len(items), data=items)

    except Exception as e:
        logger.error(f"获取ETF列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取ETF列表失败")


@router.post("/sync")
def sync_etf():
    """同步ETF数据（基础信息 + 日线 + RPS，后台任务模式）"""
    try:
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()

        dm = get_data_manager()
        df = dm.get_etf_list()
        etf_count = len(df) if not df.empty else 84

        steps = [
            {'key': 'basics', 'name': '同步ETF基础信息', 'total_count': 1, 'completed_count': 0},
            {'key': 'daily', 'name': '同步ETF日线', 'total_count': etf_count, 'completed_count': 0},
            {'key': 'rps', 'name': '计算ETF RPS', 'total_count': 1, 'completed_count': 0},
            {'key': 'alert', 'name': '计算ENE预警', 'total_count': 1, 'completed_count': 0},
        ]
        task_id = tm.create_task_with_steps(steps, name='ETF同步')

        _get_executor().submit(_run_etf_sync, task_id)

        return {"success": True, "task_id": task_id, "message": "ETF同步已启动"}
    except Exception as e:
        logger.error(f"启动ETF同步失败: {e}")
        return {"success": False, "message": f"启动失败: {str(e)}"}


def _run_etf_sync(task_id: str):
    """后台执行ETF同步"""
    from app.data.task_manager import get_task_manager
    from app.data.manager import get_data_manager
    from app.data.db import get_db

    tm = get_task_manager()
    dm = get_data_manager()

    try:
        # Step 1: 同步基础信息
        tm.start_step(task_id, 0)
        count = dm.sync_etf_basics()
        tm.complete_step(task_id, 0, f'基础信息 {count} 只')

        if tm.is_cancelled(task_id):
            return

        # Step 2: 同步日线
        tm.start_step(task_id, 1)
        result = dm.sync_etf_daily()
        success = result.get('success', 0)
        fail = result.get('fail', 0)
        db = get_db()
        from datetime import datetime as dt
        db['sync_tasks'].update_one(
            {'task_id': task_id},
            {'$set': {
                f'steps.1.completed_count': success + fail,
                f'steps.1.message': f'成功{success} 失败{fail}',
                'updated_at': dt.utcnow().isoformat()
            }}
        )
        tm.complete_step(task_id, 1, f'日线: 成功{success} 失败{fail}')

        if tm.is_cancelled(task_id):
            return

        # Step 3: 计算RPS
        tm.start_step(task_id, 2)
        from app.engine.factor_engine import FactorEngine
        engine = FactorEngine()
        rps_result = engine.calculate_rps(data_type='etf', max_dates=50)
        tm.complete_step(task_id, 2, f'RPS: {rps_result.get("dates", 0)}天')

        if tm.is_cancelled(task_id):
            return

        # Step 4: 计算ENE预警
        tm.start_step(task_id, 3)
        from app.engine.ene_alert import backfill_alerts
        new_count = backfill_alerts()
        tm.complete_step(task_id, 3, f'新增{new_count}条预警')

        tm.complete_task(task_id, 'ETF同步全部完成')
        logger.info(f'ETF同步任务 {task_id} 全部完成')

    except Exception as e:
        logger.error(f'ETF同步任务 {task_id} 异常: {e}', exc_info=True)
        try:
            tm.fail_task(task_id, str(e)[:200])
        except Exception:
            pass


@router.get("/{code}/daily", response_model=DailyDataResponse)
def get_etf_daily_data(
    code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    limit: Optional[int] = Query(200, description="返回数据条数，默认200条")
):
    """获取ETF日线数据"""
    try:
        from datetime import datetime, timedelta
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

        df = get_daily_data(code, start_date, end_date, data_type='etf')

        if df.empty:
            raise HTTPException(status_code=404, detail=f"ETF {code} 暂无数据")

        df = df.sort_index(ascending=False).head(limit)

        bars = []
        for trade_date, row in df.iterrows():
            vol_val = row.get("vol")
            if vol_val is None or pd.isna(vol_val):
                vol_val = row.get("volume")
            else:
                vol_val = vol_val * 100  # 手转换为股

            bar = DailyBar(
                trade_date=str(trade_date),
                open=float(row["open"]) if "open" in row and not pd.isna(row["open"]) else None,
                high=float(row["high"]) if "high" in row and not pd.isna(row["high"]) else None,
                low=float(row["low"]) if "low" in row and not pd.isna(row["low"]) else None,
                close=float(row["close"]) if "close" in row and not pd.isna(row["close"]) else None,
                volume=int(vol_val) if vol_val is not None and not pd.isna(vol_val) else None,
                amount=float(row["amount"]) if "amount" in row and not pd.isna(row["amount"]) else None,
                amplitude=float(row.get("amplitude", 0)) if "amplitude" in row and not pd.isna(row.get("amplitude")) else None,
                change_pct=float(row.get("change_pct", 0)) if "change_pct" in row and not pd.isna(row.get("change_pct")) else None,
                change=float(row.get("change", 0)) if "change" in row and not pd.isna(row.get("change")) else None,
                turnover=float(row.get("turnover", 0)) if "turnover" in row and not pd.isna(row.get("turnover")) else None,
                ma10=float(row["ma10"]) if "ma10" in row and not pd.isna(row["ma10"]) else None,
                ma20=float(row["ma20"]) if "ma20" in row and not pd.isna(row["ma20"]) else None,
                ma50=float(row["ma50"]) if "ma50" in row and not pd.isna(row["ma50"]) else None,
                ma120=float(row["ma120"]) if "ma120" in row and not pd.isna(row["ma120"]) else None,
                vol_ma5=float(row["vol_ma5"]) if "vol_ma5" in row and not pd.isna(row["vol_ma5"]) else None,
                vol_ma10=float(row["vol_ma10"]) if "vol_ma10" in row and not pd.isna(row["vol_ma10"]) else None,
                vol_ma20=float(row["vol_ma20"]) if "vol_ma20" in row and not pd.isna(row["vol_ma20"]) else None,
                vol_ma50=float(row["vol_ma50"]) if "vol_ma50" in row and not pd.isna(row["vol_ma50"]) else None,
                rps_10=int(row["rps_10"]) if "rps_10" in row and not pd.isna(row["rps_10"]) else None,
                rps_20=int(row["rps_20"]) if "rps_20" in row and not pd.isna(row["rps_20"]) else None,
                rps_50=int(row["rps_50"]) if "rps_50" in row and not pd.isna(row["rps_50"]) else None,
                rps_120=int(row["rps_120"]) if "rps_120" in row and not pd.isna(row["rps_120"]) else None,
                rps_250=int(row["rps_250"]) if "rps_250" in row and not pd.isna(row["rps_250"]) else None,
            )
            bars.append(bar)

        bars.reverse()
        return DailyDataResponse(code=code, total=len(bars), data=bars)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取ETF日线数据失败: {e}")
        raise HTTPException(status_code=500, detail="获取ETF日线数据失败")



