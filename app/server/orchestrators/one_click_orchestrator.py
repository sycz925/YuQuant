"""
One Click Update Orchestrator - 一键更新编排器
流程：指数同步 → 个股同步 → 板块同步 → 个股RPS → 板块RPS → PE同步 → 预计算

逻辑：
- 日线数据同步（步骤1-3）：如果今天已同步过则跳过
- RPS计算、PE同步、预计算（步骤4-7）：每次都重算
"""
import logging
from typing import List, Dict, Optional

from app.server.orchestrators.base import BaseOrchestrator

logger = logging.getLogger(__name__)


class OneClickUpdateOrchestrator(BaseOrchestrator):
    """
    一键更新编排器
    流程：指数同步 → 个股同步 → 板块同步 → 个股RPS → 板块RPS → PE同步 → 预计算
    7个步骤严格顺序执行，任一步骤失败则停止
    """
    
    def get_steps(self) -> List[Dict[str, str]]:
        return [
            {'key': 'sync_index', 'name': '同步指数'},
            {'key': 'sync_stocks', 'name': '同步个股'},
            {'key': 'sync_sectors', 'name': '同步板块'},
            {'key': 'rps_stock', 'name': '计算个股RPS'},
            {'key': 'rps_sector', 'name': '计算板块RPS'},
            {'key': 'sync_pe', 'name': '更新PE'},
            {'key': 'precompute', 'name': '预计算基础数据'},
        ]
    
    def _is_data_synced_for_date(self, collection_name: str, date_field: str, target_date: str) -> bool:
        """
        检查指定日期的数据是否已同步
        盘中（15:30前）：30分钟缓存，需要重新同步
        盘后（15:30后）：永久缓存，已同步就跳过
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        today_str = now.strftime('%Y%m%d')
        
        # 非今天的数据，检查是否有数据
        if target_date != today_str:
            from app.data.db import get_db
            db = get_db()
            count = db[collection_name].count_documents({date_field: target_date})
            return count > 0
        
        # 今天的数据
        is_market_closed = now.hour > 15 or (now.hour == 15 and now.minute >= 30)
        
        if is_market_closed:
            # 盘后：永久缓存，检查是否有数据
            from app.data.db import get_db
            db = get_db()
            count = db[collection_name].count_documents({date_field: target_date})
            return count > 0
        else:
            # 盘中：30分钟缓存，检查最后更新时间
            from app.data.db import get_db
            db = get_db()
            latest = db[collection_name].find_one(
                {date_field: target_date},
                sort=[('updated_at', -1)],
                projection={'updated_at': 1, '_id': 0}
            )
            if not latest:
                return False
            
            updated_at = latest.get('updated_at')
            if not updated_at:
                return False
            
            # 如果更新时间超过30分钟，需要重新同步
            from datetime import timedelta
            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            
            if (now - updated_at) > timedelta(minutes=30):
                return False
            
            return True
    
    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str]) -> None:
        """执行单个步骤"""
        from app.server.factories import (
            get_index_factory, get_stock_factory, 
            get_sector_factory, get_market_aggregator
        )
        from app.server.repositories.task_repository import TaskRepository
        
        step_idx = next(i for i, s in enumerate(self.get_steps()) if s['key'] == step_key)
        callback = self._make_callback(task_id, step_idx)
        task_repo = TaskRepository()
        
        # 获取目标日期
        date = target_date or self._get_today()
        
        # 日线数据同步步骤：如果今天已同步过则跳过
        if step_key in ['sync_index', 'sync_stocks', 'sync_sectors']:
            if step_key == 'sync_index':
                collection, field = 'index_daily', 'trade_date'
            elif step_key == 'sync_stocks':
                collection, field = 'stock_daily', 'trade_date'
            else:  # sync_sectors
                collection, field = 'sector_daily', 'trade_date'
            
            if self._is_data_synced_for_date(collection, field, date):
                logger.info(f"[一键更新] {step_key} 日期 {date} 已有数据，跳过同步")
                task_repo.update_step_progress(
                    task_id, step_idx,
                    status='completed',
                    message=f'{date} 数据已存在，跳过同步'
                )
                return
        
        # 执行步骤
        if step_key == 'sync_index':
            factory = get_index_factory()
            factory.sync_kline(target_date, task_id=task_id, progress_callback=callback)
        
        elif step_key == 'sync_stocks':
            factory = get_stock_factory()
            factory.sync_daily(target_date, task_id=task_id, progress_callback=callback)
        
        elif step_key == 'sync_sectors':
            factory = get_sector_factory()
            factory.sync_daily(target_date, task_id=task_id, progress_callback=callback)
        
        elif step_key == 'rps_stock':
            factory = get_stock_factory()
            factory.compute_chg(target_date, callback)
            factory.compute_rps(target_date, callback)
        
        elif step_key == 'rps_sector':
            factory = get_sector_factory()
            factory.compute_chg(target_date, callback)
            factory.compute_rps(target_date, callback)
        
        elif step_key == 'sync_pe':
            factory = get_index_factory()
            factory.sync_pe(target_date, callback)
        
        elif step_key == 'precompute':
            aggregator = get_market_aggregator()
            aggregator.precompute_base_data(date, task_id=task_id, progress_callback=callback)
    
    def _get_today(self) -> str:
        """获取今日日期"""
        from datetime import datetime
        return datetime.now().strftime('%Y%m%d')
