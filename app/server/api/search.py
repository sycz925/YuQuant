"""
统一搜索API - 同时搜索股票、板块和ETF
"""
import logging
from fastapi import APIRouter, Query
from app.server.repositories import get_search_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["搜索"])


@router.get("")
def unified_search(keyword: str = Query(..., description="搜索关键词")):
    """
    统一搜索接口 - 同时搜索股票、板块和ETF
    返回格式：{ stocks: [...], sectors: [...], etfs: [...] }
    """
    try:
        repo = get_search_repo()
        results = {
            'stocks': repo.search_stocks(keyword) if keyword else [],
            'sectors': repo.search_sectors(keyword) if keyword else [],
            'etfs': repo.search_etfs(keyword) if keyword else [],
        }
        return {
            'success': True,
            'data': results
        }
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        return {'success': False, 'data': {'stocks': [], 'sectors': [], 'etfs': []}, 'error': str(e)}
