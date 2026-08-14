"""
重点关注列表API
"""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from app.data.db import get_db, get_collection
from app.server.models import WatchlistAddRequest, WatchlistItem, WatchlistResponse
from app.engine.watchlist_alert import check_latest, get_alerts, get_tdx_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

# 列表行情字段投影（与 /etf 一致）
_QUOTE_FIELDS = {
    'close': 1, 'chg_pct': 1, 'chg_5d': 1, 'chg_10d': 1, 'chg_20d': 1,
    'chg_50d': 1, 'chg_120d': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1, '_id': 0,
}


def _resolve(entry: dict) -> WatchlistItem:
    """将 watchlist 条目解析为带行情与名称的列表项"""
    code = entry['code']
    typ = entry.get('type', 'etf')
    if typ == 'etf':
        basic = get_db()['etf_basics'].find_one({'code': code}, {'_id': 0, 'name': 1})
        name = basic['name'] if basic else code
        coll = get_collection('etf')
    else:
        basic = get_db()['stock_basics'].find_one({'stock_code': code}, {'_id': 0, 'stock_name': 1})
        name = basic['stock_name'] if basic else code
        coll = get_collection('stock')
    latest = coll.find_one(
        {'stock_code': code, 'close': {'$gt': 0}},
        sort=[('trade_date', -1)],
        projection=_QUOTE_FIELDS,
    )
    if latest:
        quote_fields = {k: latest.get(k) for k in _QUOTE_FIELDS if k not in ('_id', 'chg_pct')}
        return WatchlistItem(code=code, name=name, type=typ, change_pct=latest.get('chg_pct'),
                             tdx_status=entry.get('tdx_status'), **quote_fields)
    return WatchlistItem(code=code, name=name, type=typ, tdx_status=entry.get('tdx_status'))


@router.get("", response_model=WatchlistResponse)
def get_watchlist(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    sort_by: Optional[str] = Query(None, description="排序字段"),
    sort_order: Optional[str] = Query("desc", description="排序方向"),
    rps_red: Optional[str] = Query(None, description="RPS红筛选: one/two/three"),
    tdx_status: Optional[str] = Query(None, description="通达信状态: red/green/blue"),
):
    """获取重点关注列表（含最新行情）"""
    db = get_db()
    entries = list(db['watchlist'].find({}, {'_id': 0}).sort('created_at', 1))
    items = [_resolve(e) for e in entries]

    # 搜索过滤
    if keyword:
        kw = keyword.lower()
        items = [i for i in items if kw in i.code.lower() or kw in i.name.lower()]

    # RPS红筛选（阈值87，与 /etf 一致）
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

    # 通达信状态筛选（包含匹配：日红、周绿等）
    if tdx_status in ('红', '绿', '蓝'):
        items = [i for i in items if i.tdx_status and tdx_status in i.tdx_status]

    # 排序
    if sort_by and sort_by in ('change_pct', 'chg_5d', 'chg_10d', 'chg_20d', 'chg_50d', 'chg_120d', 'close', 'rps_10', 'rps_20', 'rps_50'):
        reverse = sort_order != 'asc'
        items.sort(key=lambda x: getattr(x, sort_by) or 0, reverse=reverse)

    return WatchlistResponse(total=len(items), data=items)


@router.post("", status_code=201)
def add_watchlist(req: WatchlistAddRequest):
    """添加代码到重点关注（自动识别个股/ETF）"""
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="代码不能为空")
    db = get_db()
    if db['etf_basics'].find_one({'code': code}, {'_id': 1}):
        typ = 'etf'
    elif db['stock_basics'].find_one({'stock_code': code}, {'_id': 1}):
        typ = 'stock'
    else:
        raise HTTPException(status_code=400, detail="未找到该代码")
    try:
        db['watchlist'].insert_one({'code': code, 'type': typ, 'created_at': datetime.now()})
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="已在列表中")
    return {'success': True, 'code': code, 'type': typ}


@router.delete("/{code}")
def remove_watchlist(code: str):
    """从重点关注删除"""
    db = get_db()
    r = db['watchlist'].delete_one({'code': code})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="不在列表中")
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
