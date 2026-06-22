"""
全局内存缓存 - 避免频繁查询数据库
"""
import threading
from datetime import datetime

# 全局缓存
_cache = {
    'latest_trade_date': None,
    'trade_dates': [],
}

_lock = threading.Lock()


def init_trade_dates():
    """初始化交易日缓存（应用启动时调用）"""
    try:
        from app.data.db import get_db
        db = get_db()
        # 使用 find_one + sort 代替 distinct（快100倍）
        doc = db['stock_daily'].find_one(
            {'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        latest = doc['trade_date'] if doc else None
        
        # 获取最近30个交易日（用于前端日期选择）
        dates_cursor = db['stock_daily'].find(
            {'close': {'$gt': 0}},
            projection={'trade_date': 1, '_id': 0}
        ).sort('trade_date', -1).limit(30)
        dates = list(set(d['trade_date'] for d in dates_cursor))
        dates.sort(reverse=True)
        
        with _lock:
            _cache['trade_dates'] = dates
            _cache['latest_trade_date'] = latest
        print(f"[缓存] 初始化交易日: {len(dates)} 天, 最新: {latest}")
    except Exception as e:
        print(f"[缓存] 初始化交易日失败: {e}")


def get_latest_trade_date() -> str:
    """获取最新交易日（从缓存读取）"""
    with _lock:
        return _cache['latest_trade_date']


def get_trade_dates() -> list:
    """获取交易日列表（从缓存读取）"""
    with _lock:
        return _cache['trade_dates']


def refresh_trade_dates():
    """刷新交易日缓存"""
    init_trade_dates()
