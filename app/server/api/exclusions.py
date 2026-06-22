"""
排除配置管理 API
管理指数、个股、板块的同步/RPS/显示排除设置
"""
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.data.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exclusions", tags=["exclusions"])


class ExclusionItem(BaseModel):
    """排除项"""
    code: str
    name: Optional[str] = None
    category: Optional[str] = None  # 分类: index/stock/sector
    exclude_sync: bool = False      # 排除同步
    exclude_rps: bool = False       # 排除 RPS 计算
    exclude_display: bool = False   # 排除页面显示


class ExclusionUpdate(BaseModel):
    """批量更新排除设置"""
    items: List[ExclusionItem]


def _get_collection():
    """获取排除配置集合"""
    db = get_db()
    col = db['exclusions']
    # 确保有索引
    try:
        col.create_index('code', unique=True)
    except Exception:
        pass
    return col


@router.get("")
def get_exclusions(
    category: Optional[str] = Query(None, description="分类: index/stock/sector")
):
    """获取排除配置列表"""
    try:
        col = _get_collection()
        query = {}
        if category:
            query['category'] = category
        
        items = list(col.find(query, {'_id': 0}))
        return {'items': items, 'total': len(items)}
    except Exception as e:
        logger.error(f"获取排除配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
def update_exclusions(update: ExclusionUpdate):
    """批量更新排除设置"""
    try:
        col = _get_collection()
        
        for item in update.items:
            update_doc = {
                'code': item.code,
                'name': item.name or item.code,
                'exclude_sync': item.exclude_sync,
                'exclude_rps': item.exclude_rps,
                'exclude_display': item.exclude_display,
            }
            if item.category:
                update_doc['category'] = item.category
            col.update_one(
                {'code': item.code},
                {'$set': update_doc},
                upsert=True
            )
        
        return {'success': True, 'message': f'更新了 {len(update.items)} 项配置'}
    except Exception as e:
        logger.error(f"更新排除配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{code}")
def delete_exclusion(code: str):
    """删除排除配置"""
    try:
        col = _get_collection()
        result = col.delete_one({'code': code})
        return {'success': True, 'deleted': result.deleted_count}
    except Exception as e:
        logger.error(f"删除排除配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check/{code}")
def check_exclusion(code: str):
    """检查某项是否被排除"""
    try:
        col = _get_collection()
        item = col.find_one({'code': code}, {'_id': 0})
        if item:
            return item
        return {'code': code, 'exclude_sync': False, 'exclude_rps': False, 'exclude_display': False}
    except Exception as e:
        logger.error(f"检查排除配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def get_excluded_codes_helper(category: str, exclude_type: str) -> list:
    """获取被排除的代码列表（内部辅助函数）"""
    try:
        col = _get_collection()
        field = f'exclude_{exclude_type}'
        items = list(col.find(
            {'category': category, field: True},
            {'_id': 0, 'code': 1}
        ))
        return [item['code'] for item in items]
    except Exception:
        return []


def get_excluded_set(category: str, exclude_type: str) -> set:
    """获取被排除的代码集合（内部辅助函数）"""
    return set(get_excluded_codes_helper(category, exclude_type))


@router.get("/excluded")
def get_excluded_codes(
    category: str = Query(..., description="分类: index/stock/sector"),
    exclude_type: str = Query(..., description="排除类型: sync/rps/display")
):
    """获取被排除的代码列表"""
    try:
        col = _get_collection()
        field = f'exclude_{exclude_type}'
        items = list(col.find(
            {'category': category, field: True},
            {'_id': 0, 'code': 1, 'name': 1}
        ))
        return {'codes': [item['code'] for item in items], 'total': len(items)}
    except Exception as e:
        logger.error(f"获取排除列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
