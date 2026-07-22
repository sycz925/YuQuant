"""
Orchestrators - 编排层
组合工厂原子能力，形成业务流程
"""
from app.server.orchestrators.base import BaseOrchestrator
from app.server.orchestrators.one_click_orchestrator import OneClickUpdateOrchestrator
from app.server.orchestrators.daily_recalc_orchestrator import DailyRecalcOrchestrator
from app.server.orchestrators.monthly_recalc_orchestrator import MonthlyRecalcOrchestrator

# 单例实例
_one_click_orchestrator: OneClickUpdateOrchestrator = None
_daily_recalc_orchestrator: DailyRecalcOrchestrator = None
_monthly_recalc_orchestrator: MonthlyRecalcOrchestrator = None


def get_one_click_orchestrator() -> OneClickUpdateOrchestrator:
    """获取一键更新编排器单例"""
    global _one_click_orchestrator
    if _one_click_orchestrator is None:
        _one_click_orchestrator = OneClickUpdateOrchestrator()
    return _one_click_orchestrator


def get_daily_recalc_orchestrator() -> DailyRecalcOrchestrator:
    """获取单日重算编排器单例"""
    global _daily_recalc_orchestrator
    if _daily_recalc_orchestrator is None:
        _daily_recalc_orchestrator = DailyRecalcOrchestrator()
    return _daily_recalc_orchestrator


def get_monthly_recalc_orchestrator() -> MonthlyRecalcOrchestrator:
    """获取月度重算编排器单例"""
    global _monthly_recalc_orchestrator
    if _monthly_recalc_orchestrator is None:
        _monthly_recalc_orchestrator = MonthlyRecalcOrchestrator()
    return _monthly_recalc_orchestrator


__all__ = [
    'BaseOrchestrator',
    'OneClickUpdateOrchestrator',
    'DailyRecalcOrchestrator',
    'MonthlyRecalcOrchestrator',
    'get_one_click_orchestrator',
    'get_daily_recalc_orchestrator',
    'get_monthly_recalc_orchestrator',
]
