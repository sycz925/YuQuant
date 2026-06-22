"""
因子 API 路由层

路由函数只负责：接收请求 → 调用 FactorService → 返回结果。
所有业务逻辑、数据库访问、后台任务调度均在 FactorService 中。
"""
import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query, UploadFile

from app.server.services.factor_service import get_factor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/factors", tags=["factors"])


# ==================== CR5% ====================

@router.get("/cr5")
def get_cr5_factor(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    include_index: bool = Query(True, description="是否包含指数数据"),
    period: str = Query("day", description="聚合周期: day/week/month/quarter/year"),
):
    """获取CR5%因子数据（支持日/周/月/季/年聚合，默认近一年日数据）"""
    try:
        svc = get_factor_service()
        result = svc.get_cr5_data(start_date, end_date, include_index, period)
        if result is None:
            raise HTTPException(status_code=404, detail="暂无因子数据")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取CR5因子失败: {e}")
        raise HTTPException(status_code=500, detail="获取因子数据失败")


# ==================== 指数管理 ====================

@router.get("/indices")
def get_indices_list(
    page: Optional[int] = Query(None, ge=1, description="页码"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词（代码或名称）"),
    filter_mode: Optional[str] = Query(None, description="筛选模式: enabled/disabled"),
):
    """获取指数列表（支持分页、搜索和状态筛选）"""
    try:
        return get_factor_service().get_indices_list(page, page_size or 50, keyword, filter_mode)
    except Exception as e:
        logger.error(f"获取指数列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取指数列表失败")


@router.get("/indices/search")
def search_indices(keyword: str = Query(..., description="搜索关键词（代码或名称）")):
    """搜索指数（先本地数据库，再查通达信 TDX）"""
    try:
        return get_factor_service().search_indices(keyword)
    except Exception as e:
        logger.error(f"搜索指数失败: {e}")
        raise HTTPException(status_code=500, detail="搜索指数失败")


@router.post("/sync-indices")
def sync_index_data(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    max_workers: Optional[int] = Query(4, description="最大线程数"),
):
    """同步所有指数数据（后台任务）"""
    try:
        return get_factor_service().sync_index_data(start_date, end_date, max_workers or 4)
    except Exception as e:
        logger.error(f"启动指数同步任务失败: {e}")
        return {"success": False, "message": str(e)}


# ==================== RPS ====================

@router.post("/rps/calculate", response_model=Dict[str, Any])
def calculate_and_save_rps(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    target_date: Optional[str] = Query(None, description="只计算指定日期的 RPS（增量模式）"),
    target: str = Query('stock', description="'stock' 个股 | 'sector' 板块 | 'all' 全部"),
    max_workers: Optional[int] = Query(16, description="最大线程数"),
    min_days: Optional[int] = Query(None, description="最小上市天数（可选）"),
):
    """计算并保存 RPS 指标（后台任务）"""
    try:
        return get_factor_service().calculate_rps(
            start_date, end_date, target_date, target, max_workers or 16, min_days,
        )
    except Exception as e:
        logger.error(f"启动 RPS 计算任务失败: {e}")
        return {"success": False, "message": f"启动任务失败: {str(e)}"}


@router.post("/tasks/clear", response_model=Dict[str, Any])
def clear_all_tasks():
    """清除所有后台任务状态（用于重置脏数据）"""
    try:
        return get_factor_service().clear_all_tasks()
    except Exception as e:
        logger.error(f"清除任务状态失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/rps", response_model=Dict[str, Any])
def delete_rps_data(
    target: str = Query('all', description="'stock' 只清个股RPS | 'sector' 只清板块RPS | 'all' 全部"),
):
    """清除 RPS 数据（不删除日线，只清 rps_* 字段）"""
    try:
        return get_factor_service().delete_rps_data(target)
    except Exception as e:
        logger.error(f"清除 RPS 数据失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/rps/{code}", response_model=Dict[str, Any])
def get_stock_rps(
    code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    period: str = Query("day", description="数据周期: day/week/month"),
):
    """获取指定股票的 RPS 数据（支持日/周/月线聚合）"""
    try:
        result = get_factor_service().get_stock_rps(code, start_date, end_date, period)
        if result is None:
            raise HTTPException(status_code=404, detail=f"股票 {code} 没有找到 RPS 数据")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取股票 RPS 失败: {e}")
        raise HTTPException(status_code=500, detail="获取 RPS 失败")


@router.get("/rps", response_model=Dict[str, Any])
def get_rps_by_date(
    trade_date: str = Query(..., description="交易日期 YYYYMMDD"),
    min_rps: Optional[int] = Query(None, description="最低 RPS 阈值（0-99），只返回 RPS 大于等于该值的股票"),
):
    """获取指定交易日的所有股票 RPS 数据"""
    try:
        result = get_factor_service().get_rps_by_date(trade_date, min_rps)
        if result is None:
            raise HTTPException(status_code=404, detail=f"日期 {trade_date} 没有找到 RPS 数据")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日期 RPS 失败: {e}")
        raise HTTPException(status_code=500, detail="获取 RPS 失败")


# ==================== 板块 ====================

@router.post("/sync-sectors", response_model=Dict[str, Any])
def sync_sectors(
    start_date: Optional[str] = Query(None, description="起始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="截止日期 YYYYMMDD"),
    max_workers: Optional[int] = Query(16, description="最大线程数"),
    min_days: Optional[int] = Query(None, description="最小天数（可选）"),
):
    """同步板块概念 + 聚合板块日线（后台任务）"""
    try:
        return get_factor_service().sync_sectors(start_date, end_date, max_workers or 16, min_days)
    except Exception as e:
        logger.error(f"启动板块同步任务失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/sectors", response_model=Dict[str, Any])
def get_sector_list(
    page: Optional[int] = Query(None, ge=1, description="页码"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词（代码或名称）"),
    filter_mode: Optional[str] = Query(None, description="筛选模式: enabled/disabled"),
    limit: Optional[int] = Query(None, description="返回数量（兼容旧接口）"),
    min_stock_count: Optional[int] = Query(5, description="最少成分股数"),
):
    """获取板块列表（支持分页、搜索和状态筛选，含RPS数据）"""
    try:
        return get_factor_service().get_sector_list(
            page, page_size or 50, keyword, filter_mode, limit, min_stock_count or 0,
        )
    except Exception as e:
        logger.error(f"获取板块列表失败: {e}")
        return {"success": False, "message": str(e), "total": 0, "items": []}


@router.post("/sectors/import-codes")
async def import_sector_codes(file: UploadFile):
    """导入板块代码映射（Excel/CSV），用于将中文板块名匹配到数字代码"""
    try:
        content = await file.read()
        filename = file.filename or ''
        return get_factor_service().import_sector_codes(content, filename)
    except Exception as e:
        logger.error(f"导入板块代码失败: {e}")
        return {"success": False, "message": str(e)}
