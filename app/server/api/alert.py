"""
ETF预警API
"""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Query

from app.engine.ene_alert import get_recent_alerts, get_alerts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/etf/alerts", tags=["etf-alerts"])


@router.get("")
def list_alerts(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """分页查询ETF预警记录"""
    return get_alerts(start_date, end_date, page, page_size)


@router.get("/recent")
def recent_alerts(
    since: Optional[str] = Query(None, description="ISO时间戳，返回此时间之后的新预警"),
    limit: int = Query(20, ge=1, le=100),
):
    """获取最近的预警（用于前端轮询推送）"""
    since_dt = datetime.fromisoformat(since) if since else None
    return get_recent_alerts(since=since_dt, limit=limit)


@router.post("/backfill")
def backfill():
    """手动触发历史回刷"""
    from app.engine.ene_alert import backfill_alerts
    count = backfill_alerts()
    return {'success': True, 'new_alerts': count}
