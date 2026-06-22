"""
MongoDB 数据库操作封装
"""
import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
import pandas as pd

# 加载环境变量
load_dotenv()

# 全局数据库连接实例
_db_instance = None

# 日线数据集合映射
COLLECTION_MAP = {
    'stock': 'stock_daily',
    'sector': 'sector_daily',
    'index': 'index_daily'
}


def get_db():
    """获取数据库连接单例"""
    global _db_instance
    if _db_instance is None:
        mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
        db_name = os.getenv('MONGODB_DB_NAME', 'yuquant')
        client = MongoClient(mongodb_uri)
        _db_instance = client[db_name]
        _create_indexes(_db_instance)
    return _db_instance


def get_collection(data_type: str):
    """根据数据类型返回对应集合"""
    coll_name = COLLECTION_MAP.get(data_type)
    if not coll_name:
        raise ValueError(f"未知数据类型: {data_type}")
    return get_db()[coll_name]


def get_all_daily_collections():
    """返回所有日线集合"""
    return [get_db()[name] for name in COLLECTION_MAP.values()]


def _create_indexes(db):
    """创建数据库索引"""
    # 股票基础信息索引
    db['stock_basics'].create_index([('stock_code', ASCENDING)], unique=True)
    db['stock_basics'].create_index([('market', ASCENDING)])

    # 指数基础信息索引（统一用 code 字段，兼容新格式）
    db['index_basics'].create_index([('code', ASCENDING)], unique=True)

    # 新日线集合索引（stock_daily, sector_daily, index_daily）
    for coll_name in COLLECTION_MAP.values():
        db[coll_name].create_index([('stock_code', ASCENDING), ('trade_date', DESCENDING)])
        db[coll_name].create_index([('trade_date', DESCENDING)])


# ==================== 股票基础信息操作 ====================

def upsert_stock_basics(stock_code: str, stock_name: str, market: str, **kwargs):
    """更新或插入股票基础信息"""
    doc = {
        'stock_code': stock_code,
        'stock_name': stock_name,
        'market': market,
        'list_date': kwargs.get('list_date'),
        'delist_date': kwargs.get('delist_date'),
        'is_st': kwargs.get('is_st', False),
        'suspend': kwargs.get('suspend', False),
        'update_time': datetime.utcnow()
    }

    db = get_db()
    try:
        db['stock_basics'].update_one(
            {'stock_code': stock_code},
            {'$set': doc},
            upsert=True
        )
    except Exception as e:
        print(f"更新股票基础信息失败 {stock_code}: {e}")


def bulk_upsert_stock_basics(docs: List[Dict[str, Any]]):
    """批量更新或插入股票基础信息"""
    db = get_db()
    for doc in docs:
        doc['update_time'] = datetime.utcnow()
        try:
            db['stock_basics'].update_one(
                {'stock_code': doc['stock_code']},
                {'$set': doc},
                upsert=True
            )
        except Exception as e:
            print(f"批量更新股票基础信息失败 {doc['stock_code']}: {e}")


def get_stock_basics(stock_code: Optional[str] = None) -> pd.DataFrame:
    """获取股票基础信息"""
    db = get_db()
    query = {}
    if stock_code:
        query['stock_code'] = stock_code

    cursor = db['stock_basics'].find(query, {'_id': 0})
    df = pd.DataFrame(list(cursor))
    return df


# ==================== 日线数据操作 ====================

def upsert_daily_data(stock_code: str, trade_date: str, data: Dict[str, Any], data_source: str = 'unknown', data_type: str = 'stock'):
    """更新或插入单条日线数据"""
    coll = get_collection(data_type)
    doc = {
        'stock_code': stock_code,
        'trade_date': trade_date,
        'data_source': data_source,
        'update_time': datetime.utcnow()
    }
    doc.update(data)

    try:
        coll.update_one(
            {'stock_code': stock_code, 'trade_date': trade_date},
            {'$set': doc},
            upsert=True
        )
    except Exception as e:
        print(f"更新日线数据失败 {stock_code} {trade_date}: {e}")


def bulk_upsert_daily_data(stock_code: str, records: List[Dict[str, Any]], data_source: str = 'unknown', data_type: str = 'stock'):
    """批量更新或插入日线数据（高性能 bulk_write 版本）

    写入时直接计算所有冗余字段：chg_pct, MA, VOL_MA, 区间涨幅。

    Args:
        stock_code: 股票/指数代码
        records: 日线数据列表
        data_source: 数据源
        data_type: 数据类型 - 'stock'(个股), 'sector'(板块), 'index'(指数)
    """
    from pymongo import UpdateOne
    import numpy as np
    coll = get_collection(data_type)

    update_time = datetime.utcnow()
    local_now = datetime.utcnow() + timedelta(hours=8)
    today_local = local_now.strftime('%Y%m%d')

    sorted_records = sorted(records, key=lambda r: str(r['trade_date']))
    if not sorted_records:
        return

    # 过滤周末和节假日
    from .holidays import is_workday
    sorted_records = [r for r in sorted_records if is_workday(str(r['trade_date']))]
    if not sorted_records:
        return

    earliest_date = str(sorted_records[0]['trade_date'])

    # 查历史数据（用于计算MA/VOL_MA/区间涨幅）
    vol_field = 'volume' if data_type == 'sector' else 'vol'
    hist_cursor = coll.find(
        {'stock_code': stock_code, 'trade_date': {'$lt': earliest_date}, 'close': {'$gt': 0}},
        {'_id': 0, 'trade_date': 1, 'close': 1, vol_field: 1, 'amount': 1}
    ).sort('trade_date', -1).limit(300)
    hist_docs = list(hist_cursor)
    hist_docs.reverse()

    # 合并历史+新数据
    def _get_vol(d):
        v = d.get(vol_field, 0) or 0
        if v <= 0:
            amt = d.get('amount', 0) or 0
            c = d.get('close', 0) or 0
            if amt > 0 and c > 0:
                v = amt / c
        return v

    all_docs = hist_docs + [{'trade_date': str(r['trade_date']), 'close': r.get('close', 0),
                              vol_field: r.get(vol_field, 0) or 0, 'amount': r.get('amount', 0) or 0}
                             for r in sorted_records]
    n = len(all_docs)
    closes = np.array([d.get('close', 0) or 0 for d in all_docs], dtype=np.float64)
    vols = np.array([_get_vol(d) for d in all_docs], dtype=np.float64)
    dates = [str(d['trade_date']) for d in all_docs]

    hist_count = len(hist_docs)

    # 只计算新写入的记录
    new_set = set(str(r['trade_date']) for r in sorted_records)

    operations = []
    for i in range(hist_count, n):
        trade_date_str = dates[i]
        is_final = True if trade_date_str < today_local else (local_now.hour >= 15 if trade_date_str == today_local else False)

        doc = {
            'stock_code': stock_code,
            'trade_date': trade_date_str,
            'data_source': data_source,
            'update_time': update_time,
            'is_final': is_final
        }
        # 写入原始字段
        orig = sorted_records[i - hist_count]
        doc.update({k: v for k, v in orig.items()
                    if k not in ('stock_code', 'trade_date', 'data_source', 'update_time', 'is_final')})

        # 板块无vol时用amount/close补写
        if data_type == 'sector' and (not doc.get('vol') or doc.get('vol', 0) <= 0):
            amt = doc.get('amount', 0) or 0
            c = doc.get('close', 0) or 0
            if amt > 0 and c > 0:
                doc['vol'] = round(amt / c, 2)

        curr_close = closes[i]
        if curr_close <= 0:
            operations.append(UpdateOne({'stock_code': stock_code, 'trade_date': trade_date_str}, {'$set': doc}, upsert=True))
            continue

        # chg_pct
        if i > 0 and closes[i - 1] > 0:
            doc['chg_pct'] = round(float((curr_close - closes[i - 1]) / closes[i - 1] * 100), 2)

        # MA
        for p in [10, 20, 50, 120]:
            if i >= p - 1:
                doc[f'ma{p}'] = round(float(np.mean(closes[i - p + 1:i + 1])), 2)

        # VOL_MA
        for p in [5, 10, 20, 50]:
            if i >= p - 1 and vols[i] > 0:
                doc[f'vol_ma{p}'] = round(float(np.mean(vols[i - p + 1:i + 1])), 2)

        # 区间涨幅
        for p in [5, 10, 20, 50, 120, 250]:
            if i >= p and closes[i - p] > 0:
                doc[f'chg_{p}d'] = round(float((curr_close - closes[i - p]) / closes[i - p] * 100), 2)

        operations.append(UpdateOne({'stock_code': stock_code, 'trade_date': trade_date_str}, {'$set': doc}, upsert=True))

    if operations:
        try:
            coll.bulk_write(operations, ordered=False)
        except Exception as e:
            print(f"批量更新日线数据失败 {stock_code}: {e}")


def get_daily_data(stock_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None, data_type: str = 'stock') -> pd.DataFrame:
    """获取日线数据"""
    coll = get_collection(data_type)
    query = {'stock_code': stock_code}

    if start_date:
        query['trade_date'] = {'$gte': start_date}
    if end_date:
        if 'trade_date' in query:
            query['trade_date']['$lte'] = end_date
        else:
            query['trade_date'] = {'$lte': end_date}

    cursor = coll.find(query, {'_id': 0}).sort('trade_date', ASCENDING)
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df = df.set_index('trade_date').sort_index()
    return df


def has_daily_data(stock_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None, data_type: str = 'stock') -> bool:
    """检查指定类型数据在指定日期范围内是否有日线数据"""
    coll = get_collection(data_type)
    query = {'stock_code': stock_code}

    if start_date:
        query['trade_date'] = {'$gte': start_date}
    if end_date:
        if 'trade_date' in query:
            query['trade_date']['$lte'] = end_date
        else:
            query['trade_date'] = {'$lte': end_date}

    count = coll.count_documents(query)
    return count > 0


def get_stock_sync_start_date(stock_code: str) -> Optional[str]:
    """获取单只股票的同步起始日期

    逻辑：
    1. 查询该股票最新数据日期
    2. 如果没有数据 → 返回 None（需要全量同步）
    3. 如果最新数据 is_final=True（收盘数据）→ 返回下一天
    4. 如果最新数据 is_final=False（盘中数据）→ 返回那天本身（需要重新同步）
    """
    from datetime import datetime as dt, timedelta

    # 查询该股票最新数据
    coll = get_collection('stock')
    latest = coll.find_one(
        {'stock_code': stock_code},
        sort=[('trade_date', -1)],
        projection={'trade_date': 1, 'is_final': 1, '_id': 0}
    )

    if not latest:
        return None  # 没有数据，需要全量同步

    latest_date = latest['trade_date']
    is_final = latest.get('is_final', False)  # 旧数据默认为已收盘

    if is_final:
        # 已收盘数据，从下一天开始同步
        try:
            dt_obj = dt.strptime(latest_date, '%Y%m%d')
            next_day = dt_obj + timedelta(days=1)
            return next_day.strftime('%Y%m%d')
        except Exception:
            return None
    else:
        # 盘中数据，需要从那天重新同步
        return latest_date


def get_sector_sync_start_date(sector_code: str) -> Optional[str]:
    """获取单个板块的同步起始日期

    逻辑：
    1. 查询该板块最新数据日期
    2. 如果没有数据 → 返回 None（需要全量同步）
    3. 如果最新数据 is_final=True（收盘数据）→ 返回下一天
    4. 如果最新数据 is_final=False（盘中数据）→ 返回那天本身（需要重新同步）
    """
    from datetime import datetime as dt, timedelta

    # 查询该板块最新数据
    coll = get_collection('sector')
    latest = coll.find_one(
        {'stock_code': sector_code},
        sort=[('trade_date', -1)],
        projection={'trade_date': 1, 'is_final': 1, '_id': 0}
    )

    if not latest:
        return None  # 没有数据，需要全量同步

    latest_date = latest['trade_date']
    is_final = latest.get('is_final', False)  # 旧数据默认为已收盘

    if is_final:
        # 已收盘数据，从下一天开始同步
        try:
            dt_obj = dt.strptime(latest_date, '%Y%m%d')
            next_day = dt_obj + timedelta(days=1)
            return next_day.strftime('%Y%m%d')
        except Exception:
            return None
    else:
        # 盘中数据，需要从那天重新同步
        return latest_date


def bulk_patch_is_final() -> Dict[str, int]:
    """批量修复所有日线集合中的 is_final 字段。

    逻辑（以 Asia/Shanghai UTC+8 本地时间判定 today_local）：
      - trade_date < today_local → is_final = True （已收盘的历史数据）
      - trade_date == today_local → is_final = False （今天的数据随时可能被覆盖）
      - trade_date > today_local → is_final = False （防御性）

    Returns:
        {'patched_final': 被标为 True 的数量,
        'patched_not_final': 被标为 False 的数量,
        'total': 集合中总文档数,
        'today': today_local
    }
    """
    update_time = datetime.utcnow()
    local_now = datetime.utcnow() + timedelta(hours=8)
    today_local = local_now.strftime('%Y%m%d')

    total_patched_final = 0
    total_patched_not_final = 0
    total_count = 0

    for coll_name in COLLECTION_MAP.values():
        col = get_db()[coll_name]

        # 1) trade_date < today → 标记 is_final=True（历史数据）
        r1 = col.update_many(
            {'trade_date': {'$lt': today_local},
             '$or': [{'is_final': {'$exists': False}}, {'is_final': {'$ne': True}}]},
            {'$set': {'is_final': True, 'update_time': update_time}}
        )
        total_patched_final += r1.modified_count

        # 2) trade_date >= today → 标记 is_final=False
        r2 = col.update_many(
            {'trade_date': {'$gte': today_local},
             '$or': [{'is_final': {'$exists': False}}, {'is_final': {'$ne': False}}]},
            {'$set': {'is_final': False, 'update_time': update_time}}
        )
        total_patched_not_final += r2.modified_count

        total_count += col.estimated_document_count()

    return {
        'patched_final': total_patched_final,
        'patched_not_final': total_patched_not_final,
        'total': total_count,
        'today': today_local
    }


# ==================== 指数基础信息操作 ====================

def upsert_index_basics(code: str, name: str, market: int = 1, tdx_code: Optional[str] = None):
    """更新或插入指数基础信息（使用新字段：code/name/tdx_code/market）"""
    if tdx_code is None:
        tdx_code = code
    doc = {
        'code': code,
        'name': name,
        'tdx_code': tdx_code,
        'market': market,
        'update_time': datetime.utcnow()
    }

    db = get_db()
    db['index_basics'].update_one(
        {'code': code},
        {'$set': doc},
        upsert=True
    )


def get_index_basics(code: Optional[str] = None) -> pd.DataFrame:
    """获取指数基础信息（使用新字段：code/name/tdx_code/market）"""
    db = get_db()
    query = {}
    if code:
        query['code'] = code

    cursor = db['index_basics'].find(query, {'_id': 0})
    df = pd.DataFrame(list(cursor))
    return df



