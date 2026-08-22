"""
Stock Repository - 股票数据访问层
"""
from typing import Dict, List, Optional
from app.server.repositories.base import BaseRepository


class StockRepository(BaseRepository):
    """股票基础信息和日线数据仓库"""
    
    def __init__(self):
        super().__init__('stock_basics')
    
    @property
    def daily(self):
        """获取日线数据集合"""
        from app.data.db import get_db
        return get_db()['stock_daily']
    
    def get_enabled_codes(self) -> List[str]:
        """获取所有启用的股票代码"""
        return [
            doc['stock_code'] for doc in self.collection.find(
                {'is_disable': {'$ne': True}},
                {'_id': 0, 'stock_code': 1}
            )
        ]

    def get_disabled_codes(self) -> set:
        """获取所有禁用股票的代码集合"""
        return {
            doc['stock_code'] for doc in self.collection.find(
                {'is_disable': True},
                {'_id': 0, 'stock_code': 1}
            )
        }

    def get_all_codes(self) -> set:
        """获取所有股票代码集合"""
        return {
            doc.get('stock_code', '') for doc in self.collection.find(
                {}, {'_id': 0, 'stock_code': 1}
            )
        }
    
    def get_enabled_list(self) -> List[Dict]:
        """获取所有启用的股票列表"""
        return list(self.collection.find(
            {'is_disable': {'$ne': True}},
            {'_id': 0, 'stock_code': 1, 'stock_name': 1, 'market': 1}
        ))
    
    def get_by_code(self, stock_code: str) -> Optional[Dict]:
        """根据股票代码获取股票信息"""
        return self.collection.find_one(
            {'stock_code': stock_code},
            {'_id': 0}
        )
    
    def search(self, keyword: str) -> List[Dict]:
        """搜索股票（代码、名称）"""
        return list(self.collection.find(
            {'$or': [
                {'stock_code': {'$regex': keyword, '$options': 'i'}},
                {'stock_name': {'$regex': keyword, '$options': 'i'}}
            ]},
            {'_id': 0, 'stock_code': 1, 'stock_name': 1, 'market': 1}
        ).limit(50))
    
    def get_daily_data(self, stock_code: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """获取股票日线数据"""
        query = {'stock_code': stock_code, 'close': {'$gt': 0}}
        if start_date:
            query['trade_date'] = {'$gte': start_date}
        if end_date:
            query.setdefault('trade_date', {})['$lte'] = end_date
        
        return list(self.daily.find(
            query,
            {'_id': 0}
        ).sort('trade_date', -1).limit(limit))
    
    def get_latest_trade_date(self, codes: Optional[List[str]] = None) -> Optional[str]:
        """获取最新交易日（可按 codes 探测）"""
        query = {'close': {'$gt': 0}}
        if codes:
            query['stock_code'] = {'$in': list(codes[:1])}
        latest = self.daily.find_one(
            query, sort=[('trade_date', -1)], projection={'trade_date': 1, '_id': 0})
        return latest['trade_date'] if latest else None
    
    def get_daily_quotes(self, codes: List[str], trade_date: str, projection: Dict) -> List[Dict]:
        """获取指定交易日的成分股行情"""
        return list(self.daily.find(
            {'stock_code': {'$in': list(codes)}, 'trade_date': trade_date, 'close': {'$gt': 0}},
            projection
        ))
    
    def get_stock_names(self, codes: List[str]) -> Dict[str, str]:
        """获取股票名映射 {stock_code: stock_name}"""
        return {
            b['stock_code']: b.get('stock_name', '') for b in self.collection.find(
                {'stock_code': {'$in': list(codes)}},
                {'_id': 0, 'stock_code': 1, 'stock_name': 1})
        }

    def get_liutong_map(self) -> Dict[str, Dict]:
        """获取流通股本映射 {stock_code: {liutongguben, name}}"""
        result = {}
        for b in self.collection.find(
            {'liutongguben': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'liutongguben': 1, 'stock_name': 1}):
            result[b['stock_code']] = {
                'liutongguben': b.get('liutongguben', 0),
                'name': b.get('stock_name', ''),
            }
        return result
    
    def count_documents(self, query: Optional[Dict] = None) -> int:
        """计数（覆盖基类，使用 stock_basics）"""
        return self.collection.count_documents(query or {})
    
    def update_disable_status(self, stock_code: str, is_disable: bool) -> int:
        """更新禁用状态"""
        return self.update_one(
            {'stock_code': stock_code},
            {'$set': {'is_disable': is_disable}}
        )
    
    def get_stock_list(self, page: Optional[int] = None, page_size: int = 50,
                       keyword: Optional[str] = None, filter_mode: Optional[str] = None) -> Dict:
        """获取股票列表（支持分页、搜索、筛选）"""
        query = {}
        
        if keyword:
            query['$or'] = [
                {'stock_code': {'$regex': keyword, '$options': 'i'}},
                {'stock_name': {'$regex': keyword, '$options': 'i'}}
            ]
        
        if filter_mode == 'enabled':
            query['is_disable'] = {'$ne': True}
        elif filter_mode == 'disabled':
            query['is_disable'] = True
        
        total = self.collection.count_documents(query)
        
        cursor = self.collection.find(query, {'_id': 0, 'stock_code': 1, 'stock_name': 1, 'market': 1})
        
        if page is not None:
            skip = (page - 1) * page_size
            cursor = cursor.skip(skip).limit(page_size)
        
        data = list(cursor)
        
        return {
            'total': total,
            'data': data,
            'page': page,
            'page_size': page_size
        }
