"""
Repository 基类 - 封装 MongoDB 通用操作
"""
from typing import Any, Dict, List, Optional, TypeVar, Type
from pymongo.collection import Collection
from pymongo.cursor import Cursor
from bson import ObjectId

T = TypeVar('T')


class BaseRepository:
    """Repository 基类，封装 MongoDB 通用 CRUD 操作"""
    
    def __init__(self, collection_name: str):
        self._collection_name = collection_name
        self._collection: Optional[Collection] = None
    
    @property
    def collection(self) -> Collection:
        """延迟加载集合连接"""
        if self._collection is None:
            from app.data.db import get_db
            db = get_db()
            self._collection = db[self._collection_name]
        return self._collection
    
    def find_one(self, query: Dict, projection: Optional[Dict] = None) -> Optional[Dict]:
        """查询单条记录"""
        return self.collection.find_one(query, projection)
    
    def find_many(self, query: Dict, projection: Optional[Dict] = None, 
                  sort: Optional[List] = None, limit: int = 0) -> List[Dict]:
        """查询多条记录"""
        cursor = self.collection.find(query, projection)
        if sort:
            cursor = cursor.sort(sort)
        if limit > 0:
            cursor = cursor.limit(limit)
        return list(cursor)
    
    def find_cursor(self, query: Dict, projection: Optional[Dict] = None,
                    sort: Optional[List] = None) -> Cursor:
        """返回游标（用于大数据集）"""
        cursor = self.collection.find(query, projection)
        if sort:
            cursor = cursor.sort(sort)
        return cursor
    
    def count(self, query: Optional[Dict] = None) -> int:
        """计数"""
        return self.collection.count_documents(query or {})
    
    def distinct(self, field: str, query: Optional[Dict] = None) -> List:
        """去重查询"""
        return self.collection.distinct(field, query or {})
    
    def insert_one(self, document: Dict) -> ObjectId:
        """插入单条记录"""
        result = self.collection.insert_one(document)
        return result.inserted_id
    
    def insert_many(self, documents: List[Dict]) -> List[ObjectId]:
        """插入多条记录"""
        result = self.collection.insert_many(documents)
        return result.inserted_ids
    
    def update_one(self, query: Dict, update: Dict, upsert: bool = False) -> int:
        """更新单条记录。

        注意：返回 modified_count；当 upsert=True 且命中插入（而非更新）时 modified_count 为 0，
        需判断是否发生插入时应改用 update_one_result() 读取 upserted_id。
        """
        result = self.collection.update_one(query, update, upsert=upsert)
        return result.modified_count

    def update_one_result(self, query: Dict, update: Dict, upsert: bool = False):
        """更新单条记录并返回完整 UpdateResult（含 matched_count/modified_count/upserted_id）。"""
        return self.collection.update_one(query, update, upsert=upsert)
    
    def update_many(self, query: Dict, update: Dict, upsert: bool = False) -> int:
        """更新多条记录"""
        result = self.collection.update_many(query, update, upsert=upsert)
        return result.modified_count
    
    def delete_one(self, query: Dict) -> int:
        """删除单条记录"""
        result = self.collection.delete_one(query)
        return result.deleted_count
    
    def delete_many(self, query: Dict) -> int:
        """删除多条记录"""
        result = self.collection.delete_many(query)
        return result.deleted_count
    
    def aggregate(self, pipeline: List[Dict]) -> List[Dict]:
        """聚合查询"""
        return list(self.collection.aggregate(pipeline))
    
    def bulk_write(self, operations: List, ordered: bool = False):
        """批量写入"""
        return self.collection.bulk_write(operations, ordered=ordered)
