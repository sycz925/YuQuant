"""
产业地图 API 路由
输入关键字 → 返回上游/中游/下游产业链生态图谱（后台任务 + 缓存）
"""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.server.api.deepseek_analyst import is_deepseek_available
from app.server.services.industry_map_service import (
    delete_cached_industry_map,
    get_cached_industry_map,
    get_industry_intersection,
    import_industry_map,
    list_history,
    start_industry_map_task,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/industry-map", tags=["产业地图"])


class IntersectRequest(BaseModel):
    keywords: List[str]


class ImportRequest(BaseModel):
    json_text: str
    keyword: Optional[str] = None


@router.post("/intersect")
def intersect_industry_map_api(payload: IntersectRequest):
    """求多个产业的交集个股（同时存在于这些产业产业链中的个股）"""
    try:
        keywords = [k for k in (payload.keywords or []) if k and str(k).strip()]
        if not keywords:
            raise ValueError("keywords 不能为空")
        result = get_industry_intersection(keywords)
        return {'success': True, 'count': len(result), 'data': result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"求产业交集失败: {e}")
        raise HTTPException(status_code=500, detail=f"求产业交集失败: {str(e)}")


@router.post("/import")
def import_industry_map_api(payload: ImportRequest):
    """导入外部查好的产业链 JSON 文本：跳过 DeepSeek，直接归一化 + 个股代码匹配 + 落库"""
    try:
        result = import_industry_map(payload.json_text, payload.keyword)
        return {'success': True, 'data': result}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"导入产业链失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.post("/generate")
def generate_industry_map_api(
    keyword: str = Query(..., description="产业关键字，如：国产CPU、创新药、光伏"),
    refresh: bool = Query(False, description="是否强制重新生成（默认取缓存）"),
):
    """生成产业链图谱：缓存命中直接返回；否则需遵循 DeepSeek 时间窗口，再启动后台任务"""
    try:
        keyword = (keyword or '').strip()
        if not keyword:
            raise ValueError("产业关键字不能为空")

        if not refresh:
            cached = get_cached_industry_map(keyword)
            if cached:
                return {'success': True, 'cached': True, 'data': cached}

        # 缓存未命中或强制更新，需调 DeepSeek，遵循时间窗口
        available, msg = is_deepseek_available()
        if not available:
            raise HTTPException(status_code=400, detail=msg)

        task_id = start_industry_map_task(keyword)
        return {'success': True, 'cached': False, 'task_id': task_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"生成产业地图失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成产业地图失败: {str(e)}")


@router.get("")
def get_industry_map_api(
    keyword: str = Query(..., description="产业关键字"),
):
    """查询缓存中的产业链图谱（任务完成后取结果用）"""
    try:
        cached = get_cached_industry_map((keyword or '').strip())
        return {'success': True, 'data': cached}
    except Exception as e:
        logger.error(f"查询产业地图失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询产业地图失败: {str(e)}")


@router.get("/history")
def get_industry_map_history_api():
    """历史记录列表（按生成时间倒序）"""
    try:
        return {'success': True, 'data': list_history()}
    except Exception as e:
        logger.error(f"查询产业地图历史失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询历史失败: {str(e)}")


@router.delete("")
def delete_industry_map_api(
    keyword: str = Query(..., description="产业关键字"),
):
    """删除指定关键字的缓存"""
    try:
        keyword = (keyword or '').strip()
        if not keyword:
            raise ValueError("产业关键字不能为空")
        deleted = delete_cached_industry_map(keyword)
        return {'success': True, 'deleted': deleted}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"删除产业地图失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除产业地图失败: {str(e)}")


@router.get("/deepseek-available")
def get_deepseek_available_api():
    """查询 DeepSeek API 是否在当前时间窗口内可用"""
    available, msg = is_deepseek_available()
    return {'available': available, 'message': msg}
