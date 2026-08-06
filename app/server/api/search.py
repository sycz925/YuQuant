"""
统一搜索API - 同时搜索股票和板块
"""
import logging
from fastapi import APIRouter, Query
from app.data.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["搜索"])


@router.get("")
def unified_search(keyword: str = Query(..., description="搜索关键词")):
    """
    统一搜索接口 - 同时搜索股票、板块和ETF
    返回格式：{ stocks: [...], sectors: [...], etfs: [...] }
    """
    try:
        db = get_db()
        results = {'stocks': [], 'sectors': [], 'etfs': []}
        
        # 搜索股票（支持代码、名称、拼音）
        if keyword:
            # 按代码搜索
            stock_by_code = list(db['stock_basics'].find(
                {'stock_code': {'$regex': keyword, '$options': 'i'}},
                {'_id': 0, 'stock_code': 1, 'stock_name': 1}
            ).limit(5))
            
            # 按名称搜索
            stock_by_name = list(db['stock_basics'].find(
                {'stock_name': {'$regex': keyword, '$options': 'i'}},
                {'_id': 0, 'stock_code': 1, 'stock_name': 1}
            ).limit(10))
            
            # 合并去重
            seen_codes = set()
            for s in stock_by_code + stock_by_name:
                if s['stock_code'] not in seen_codes:
                    seen_codes.add(s['stock_code'])
                    results['stocks'].append({
                        'code': s['stock_code'],
                        'name': s['stock_name']
                    })
            
            results['stocks'] = results['stocks'][:15]
        
        # 搜索板块
        if keyword:
            sector_cursor = db['sector_basics'].find(
                {'name': {'$regex': keyword, '$options': 'i'}},
                {'_id': 0, 'code': 1, 'name': 1}
            ).limit(10)
            results['sectors'] = [{'code': s['code'], 'name': s['name']} for s in sector_cursor]

        # 搜索ETF
        if keyword:
            etf_by_code = list(db['etf_basics'].find(
                {'code': {'$regex': keyword, '$options': 'i'}},
                {'_id': 0, 'code': 1, 'name': 1}
            ).limit(5))
            etf_by_name = list(db['etf_basics'].find(
                {'name': {'$regex': keyword, '$options': 'i'}},
                {'_id': 0, 'code': 1, 'name': 1}
            ).limit(10))
            seen_codes = set()
            for e in etf_by_code + etf_by_name:
                if e['code'] not in seen_codes:
                    seen_codes.add(e['code'])
                    results['etfs'].append({'code': e['code'], 'name': e['name']})
            results['etfs'] = results['etfs'][:15]

        return {
            'success': True,
            'data': results
        }
        
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        return {'success': False, 'data': {'stocks': [], 'sectors': []}, 'error': str(e)}
