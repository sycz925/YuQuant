"""中国交易日判断 - 三级读取：数据库 > API > chinese_calendar"""
import json
import time
from datetime import datetime, timedelta
from typing import Set, List, Optional

# 交易日集合缓存（内存级）
_workday_cache = {}
_cache_year = None


def _get_collection():
    from app.data.db import get_db
    db = get_db()
    return db['holidays']


def _load_from_db(year: int) -> Optional[Set[str]]:
    """从数据库读取节假日"""
    coll = _get_collection()
    doc = coll.find_one({'year': year})
    if doc and 'dates' in doc:
        return set(doc['dates'])
    return None


def _save_to_db(year: int, holidays: Set[str]):
    """保存节假日到数据库"""
    coll = _get_collection()
    coll.update_one(
        {'year': year},
        {'$set': {'year': year, 'dates': sorted(holidays), 'update_time': datetime.utcnow()}},
        upsert=True
    )


def _fetch_from_api(year: int) -> Optional[Set[str]]:
    """从 timor.tech API 获取节假日"""
    import urllib.request
    url = f"https://timor.tech/api/holiday/year/{year}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if data.get('code') != 0:
            return None

        holidays = set()
        for date_str, info in data.get('holiday', {}).items():
            if info.get('holiday', False):
                holidays.add(date_str)

        if holidays:
            _save_to_db(year, holidays)
        return holidays
    except Exception as e:
        print(f"API获取{year}年节假日失败: {e}")
        return None


def _fetch_from_chinese_calendar(year: int) -> Optional[Set[str]]:
    """从 chinese_calendar 库获取节假日"""
    try:
        from chinese_calendar import is_holiday, is_workday
        from datetime import date as _date

        holidays = set()
        d = _date(year, 1, 1)
        end = _date(year, 12, 31)
        while d <= end:
            if is_holiday(d):
                holidays.add(d.strftime('%m-%d'))
            d += timedelta(days=1)

        if holidays:
            _save_to_db(year, holidays)
        return holidays
    except ImportError:
        print("chinese_calendar 未安装，跳过")
        return None
    except Exception as e:
        print(f"chinese_calendar获取{year}年节假日失败: {e}")
        return None


def _get_holidays(year: int) -> Set[str]:
    """获取节假日，三级读取：数据库 > API > chinese_calendar"""
    # 1. 数据库
    holidays = _load_from_db(year)
    if holidays is not None:
        return holidays

    # 2. API
    holidays = _fetch_from_api(year)
    if holidays is not None:
        return holidays

    # 3. chinese_calendar
    holidays = _fetch_from_chinese_calendar(year)
    if holidays is not None:
        return holidays

    # 兜底：只返回空集合（仅靠周末判断）
    return set()


def is_holiday(date_str: str) -> bool:
    """判断YYYYMMDD格式的日期是否是法定节假日"""
    try:
        dt = datetime.strptime(date_str, '%Y%m%d')
        mm_dd = dt.strftime('%m-%d')
        holidays = _get_holidays(dt.year)
        return mm_dd in holidays
    except Exception:
        return False


def is_workday(date_str: str) -> bool:
    """判断YYYYMMDD格式的日期是否是交易日
    交易日 = 周一到周五 且 非法定节假日
    """
    try:
        dt = datetime.strptime(date_str, '%Y%m%d')
        if dt.weekday() >= 5:
            return False
        return not is_holiday(date_str)
    except Exception:
        return False


def filter_workdays(start_date: str, end_date: str) -> List[str]:
    """过滤日期范围，只返回交易日列表"""
    try:
        sd = datetime.strptime(start_date, '%Y%m%d')
        ed = datetime.strptime(end_date, '%Y%m%d')
    except Exception:
        return []

    # 预加载年份数据
    _get_holidays(sd.year)
    if ed.year != sd.year:
        _get_holidays(ed.year)

    workdays = []
    d = sd
    while d <= ed:
        date_str = d.strftime('%Y%m%d')
        if is_workday(date_str):
            workdays.append(date_str)
        d += timedelta(days=1)
    return workdays


def sync_holidays_to_db(years: List[int] = None):
    """手动同步节假日数据到数据库"""
    if years is None:
        years = [datetime.now().year, datetime.now().year + 1]
    for year in years:
        print(f"同步{year}年节假日...")
        _get_holidays(year)
    print("节假日同步完成")
