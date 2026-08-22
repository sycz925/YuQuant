"""
重点关注列表API
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from app.server.models import WatchlistAddRequest, WatchlistItem, WatchlistResponse
from app.server.repositories import get_watchlist_repo
from app.engine.watchlist_alert import check_latest, get_alerts, get_tdx_status, delete_alerts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=WatchlistResponse)
def get_watchlist(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    sort_by: Optional[str] = Query(None, description="排序字段"),
    sort_order: Optional[str] = Query("desc", description="排序方向"),
    rps_red: Optional[str] = Query(None, description="RPS红筛选: one/two/three"),
    tdx_status: Optional[str] = Query(None, description="通达信状态: red/green/blue"),
):
    """获取重点关注列表（含最新行情）"""
    repo = get_watchlist_repo()
    items = [WatchlistItem(**repo.resolve_entry(e)) for e in repo.list_entries()]

    # 搜索过滤
    if keyword:
        kw = keyword.lower()
        items = [i for i in items if kw in i.code.lower() or kw in i.name.lower()]

    # RPS红筛选（阈值87，与 /etf 一致）
    if rps_red in ('one', 'two', 'three'):
        rps_threshold = 87
        filtered = []
        for item in items:
            rps_values = [v for v in (item.rps_10, item.rps_50, item.rps_120) if v is not None]
            red_count = sum(1 for v in rps_values if v > rps_threshold)
            if rps_red == 'one' and red_count >= 1:
                filtered.append(item)
            elif rps_red == 'two' and red_count >= 2:
                filtered.append(item)
            elif rps_red == 'three' and red_count >= 3:
                filtered.append(item)
        items = filtered

    # 通达信状态筛选（包含匹配：日红、周绿等）
    if tdx_status in ('红', '绿', '蓝'):
        items = [i for i in items if i.tdx_status and tdx_status in i.tdx_status]

    # 排序
    if sort_by and sort_by in ('change_pct', 'chg_5d', 'chg_10d', 'chg_20d', 'chg_50d', 'chg_120d', 'close', 'rps_10', 'rps_50', 'rps_120'):
        reverse = sort_order != 'asc'
        items.sort(key=lambda x: getattr(x, sort_by) or 0, reverse=reverse)

    return WatchlistResponse(total=len(items), data=items)


@router.post("", status_code=201)
def add_watchlist(req: WatchlistAddRequest):
    """添加代码到重点关注（自动识别个股/ETF）"""
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="代码不能为空")
    repo = get_watchlist_repo()
    typ = repo.find_type(code)
    if not typ:
        raise HTTPException(status_code=400, detail="未找到该代码")
    try:
        repo.add(code, typ)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="已在列表中")
    return {'success': True, 'code': code, 'type': typ}


@router.delete("/{code}")
def remove_watchlist(code: str):
    """从重点关注删除（同步清理该代码的均线预警记录）"""
    repo = get_watchlist_repo()
    if not repo.remove(code):
        raise HTTPException(status_code=404, detail="不在列表中")
    delete_alerts(code)
    return {'success': True, 'code': code}


@router.post("/alerts/check")
def trigger_alerts_check():
    """扫描关注列表最新交易日，生成均线预警记录，并返回各标的TDX状态"""
    result = check_latest()
    return result


@router.get("/alerts")
def list_alerts(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """分页查询关注列表均线预警记录"""
    return get_alerts(start_date, end_date, page, page_size)
