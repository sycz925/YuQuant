"""限售股解禁 API 路由"""

from fastapi import APIRouter, HTTPException, Query
from app.server.services.restricted_release_service import (
    get_restricted_release_service
)

router = APIRouter(prefix="/api/restricted-release", tags=["restricted-release"])


@router.get("/summary")
async def get_summary(year: int = Query(..., ge=2010, le=2030)):
    """获取指定年份的月度解禁汇总"""
    try:
        service = get_restricted_release_service()
        result = service.get_monthly_summary(year)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detail")
async def get_detail(
    year: int = Query(..., ge=2010, le=2030),
    month: int = Query(..., ge=1, le=12)
):
    """获取指定月份的解禁详情"""
    try:
        service = get_restricted_release_service()
        result = service.get_monthly_detail(year, month)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def sync_data(year: int = Query(..., ge=2010, le=2030)):
    """同步指定年份的解禁数据"""
    try:
        service = get_restricted_release_service()
        result = service.sync_year_data(year)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
