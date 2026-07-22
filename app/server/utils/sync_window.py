"""
同步时间窗口工具 - 统一管理同步时间检查逻辑
避免在 sync.py、one_click_update.py、factors.py 中重复实现
"""
from datetime import datetime
from typing import Tuple


def check_sync_time() -> Tuple[bool, str]:
    """
    检查当前是否在允许同步的时间窗口内
    
    规则：
    - 非交易日：全天可同步
    - 交易日：盘中 11:30-13:00，盘后 16:00-23:59
    
    Returns:
        (allowed: bool, message: str)
    """
    from app.data.holidays import is_workday
    from app.server.config import get_settings
    
    settings = get_settings()
    now = datetime.now()
    today_str = now.strftime('%Y%m%d')
    
    # 非交易日全天可同步
    if not is_workday(today_str):
        return True, ""
    
    hour, minute = now.hour, now.minute
    t = hour * 60 + minute  # 转为分钟数
    
    # 盘中窗口：11:30(690) - 13:00(780)
    if settings.SYNC_WINDOW_LUNCH_START <= t < settings.SYNC_WINDOW_LUNCH_END:
        return True, ""
    
    # 盘后窗口：16:00(960) - 23:59(1439)
    if settings.SYNC_WINDOW_AFTER_MARKET_START <= t <= 1439:
        return True, ""
    
    # 不在允许时段
    return False, f"当前 {now.strftime('%H:%M')}，同步开放时间为 11:30-13:00 或 16:00-24:00"
