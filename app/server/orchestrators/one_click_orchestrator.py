"""
One Click Update Orchestrator - 一键更新编排器

核心逻辑：
1. 查询 base_data_daily 中最后更新日期
2. 从该日期+1 到 今天，计算需要补算的天数 N
3. 对每一天（从最早到今天），依次执行7个步骤
4. 总步骤数 = N × 7

步骤逻辑：
- 步骤1-3（数据同步）：有缓存检查，盘后永久缓存/盘中30分钟缓存
- 步骤4-7（RPS/PE/预计算）：每次都重算
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.server.orchestrators.base import BaseOrchestrator

logger = logging.getLogger(__name__)


class OneClickUpdateOrchestrator(BaseOrchestrator):
    """
    一键更新编排器
    流程：查询最后更新日期 → 计算日期范围 → 对每天执行7个步骤
    """
    
    STEP_KEYS = ['sync_index', 'sync_stocks', 'sync_sectors', 'rps_stock', 'rps_sector', 'sync_pe', 'precompute']
    STEP_NAMES = ['同步指数', '同步个股', '同步板块', '计算个股RPS', '计算板块RPS', '更新PE', '预计算基础数据']
    
    def get_steps(self) -> List[Dict[str, str]]:
        # 动态生成步骤，在 execute() 中设置
        return [{'key': k, 'name': n} for k, n in zip(self.STEP_KEYS, self.STEP_NAMES)]
    
    def _get_last_update_date(self) -> Optional[str]:
        """查询 base_data_daily 中最后更新日期"""
        from app.data.db import get_db
        db = get_db()
        
        latest = db['base_data_daily'].find_one(
            {},
            sort=[('date', -1)],
            projection={'date': 1, '_id': 0}
        )
        
        if latest and latest.get('date'):
            return latest['date']
        return None
    
    def _get_date_range(self, last_date: Optional[str], today: str) -> List[str]:
        """计算需要补算的日期范围（仅包含交易日）"""
        from app.data.holidays import is_workday
        
        if not last_date:
            # 没有历史数据，从250天前开始
            start = datetime.strptime(today, '%Y%m%d') - timedelta(days=250)
            last_date = start.strftime('%Y%m%d')
        
        if last_date >= today:
            # 已经是最新，只检查今天是否为交易日
            if is_workday(today):
                return [today]
            return []
        
        # 从 last_date+1 到今天，只保留交易日
        dates = []
        current = datetime.strptime(last_date, '%Y%m%d') + timedelta(days=1)
        end = datetime.strptime(today, '%Y%m%d')
        
        while current <= end:
            date_str = current.strftime('%Y%m%d')
            if is_workday(date_str):
                dates.append(date_str)
            current += timedelta(days=1)
        
        return dates
    
    def _is_data_synced_for_date(self, collection_name: str, date_field: str, target_date: str) -> bool:
        """
        检查指定日期的数据是否已同步
        盘中（15:30前）：30分钟缓存，需要重新同步
        盘后（15:30后）：永久缓存，已同步就跳过
        """
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
            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            
            if (now - updated_at) > timedelta(minutes=30):
                return False
            
            return True
    
    def _get_step_totals(self) -> Dict[str, int]:
        """查询各步骤的实际数据量（仅启用的记录）"""
        from app.data.db import get_db
        db = get_db()
        
        # 启用的指数数量（is_disable 为 False）
        index_count = db['index_basics'].count_documents({'is_disable': False})
        
        # 启用的个股数量（is_disable 为 False）
        stock_count = db['stock_basics'].count_documents({'is_disable': False})
        
        # 启用的板块数量（is_disable 为 False）
        sector_count = db['sector_basics'].count_documents({'is_disable': False})
        
        logger.info(f"[一键更新] 启用数量: 指数={index_count}, 个股={stock_count}, 板块={sector_count}")
        
        return {
            'sync_index': index_count,
            'sync_stocks': stock_count,
            'sync_sectors': sector_count,
            'rps_stock': 1,  # 单次计算
            'rps_sector': 1,  # 单次计算
            'sync_pe': index_count,  # PE同步数量与指数相同
            'precompute': 1,  # 单次计算
        }
    
    def execute(self, target_date: Optional[str] = None) -> str:
        """
        执行一键更新
        :param target_date: 目标日期，None 表示自动计算
        :return: task_id
        """
        today = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
        target = target_date or today
        
        # 查询最后更新日期
        last_date = self._get_last_update_date()
        logger.info(f"[一键更新] 最后更新日期: {last_date}")
        
        # 计算日期范围
        dates = self._get_date_range(last_date, target)
        logger.info(f"[一键更新] 需要更新的日期: {dates} (共{len(dates)}天)")
        
        # 查询各步骤的实际数据量
        step_totals = self._get_step_totals()
        
        # 生成步骤：每个日期 × 7个步骤
        steps = []
        for date in dates:
            for key, name in zip(self.STEP_KEYS, self.STEP_NAMES):
                steps.append({
                    'key': key,
                    'name': f'{date} {name}',
                    'date': date,
                    'total_count': step_totals.get(key, 1),
                    'completed_count': 0,
                })
        
        logger.info(f"[一键更新] 总步骤数: {len(steps)}")
        
        # 创建任务
        import uuid
        task_id = str(uuid.uuid4())
        self.task_repo.create_task(task_id, steps)
        
        # 使用线程池提交任务
        from app.server.orchestrators.base import _executor
        _executor.submit(self._run, task_id, dates)
        
        return task_id
    
    def _run(self, task_id: str, dates: List[str]) -> None:
        """后台执行流程"""
        import threading
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()
        
        total_dates = len(dates)
        logger.info(f"[一键更新] 开始执行，共 {total_dates} 个日期")
        
        for date_idx, date in enumerate(dates):
            logger.info(f"[一键更新] ===== 日期 {date_idx+1}/{total_dates}: {date} =====")
            
            for step_idx, step_key in enumerate(self.STEP_KEYS):
                # 计算全局步骤索引
                global_step_idx = date_idx * len(self.STEP_KEYS) + step_idx
                
                # 检查任务是否已取消
                if tm.is_cancelled(task_id):
                    logger.info(f'任务 {task_id} 已取消，停止执行')
                    return
                
                step_name = self.STEP_NAMES[step_idx]
                logger.info(f"[一键更新] 步骤 {step_idx+1}/7: {step_name}")
                
                self.task_repo.update_step_progress(task_id, global_step_idx, status='running')
                self.task_repo.update_task_progress(task_id, current_step=global_step_idx)
                
                # 启动进度同步线程
                sync_stop = threading.Event()
                sync_thread = threading.Thread(
                    target=self._sync_progress,
                    args=(task_id, global_step_idx, sync_stop),
                    daemon=True
                )
                sync_thread.start()
                
                try:
                    self.execute_step(step_key, task_id, date)
                except Exception as e:
                    logger.error(f'[一键更新] 步骤 {date} {step_name} 失败: {e}', exc_info=True)
                    sync_stop.set()
                    sync_thread.join(timeout=5)
                    self.task_repo.update_step_progress(
                        task_id, global_step_idx,
                        status='failed',
                        message=str(e)[:200]
                    )
                    self.task_repo.fail_task(task_id, f'步骤失败: {str(e)[:200]}')
                    return
                finally:
                    sync_stop.set()
                    sync_thread.join(timeout=5)
                
                self.task_repo.update_step_progress(
                    task_id, global_step_idx, 
                    status='completed', 
                    message=f'{date} {step_name}完成'
                )
                logger.info(f"[一键更新] 步骤 {step_idx+1}/7: {step_name} 完成")
            
            logger.info(f"[一键更新] ===== 日期 {date} 全部完成 =====")
        
        self.task_repo.complete_task(task_id, '全部完成')
        logger.info(f'[一键更新] 全部完成，共处理 {total_dates} 个日期')
    
    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str]) -> None:
        """执行单个步骤"""
        from app.server.factories import (
            get_index_factory, get_stock_factory, 
            get_sector_factory, get_market_aggregator
        )
        
        # 日线数据同步步骤：如果已同步过则跳过
        if step_key in ['sync_index', 'sync_stocks', 'sync_sectors']:
            if step_key == 'sync_index':
                collection, field = 'index_daily', 'trade_date'
            elif step_key == 'sync_stocks':
                collection, field = 'stock_daily', 'trade_date'
            else:  # sync_sectors
                collection, field = 'sector_daily', 'trade_date'
            
            if self._is_data_synced_for_date(collection, field, target_date):
                logger.info(f"[一键更新] {step_key} 日期 {target_date} 已有数据，跳过同步")
                return
            else:
                logger.info(f"[一键更新] {step_key} 日期 {target_date} 需要同步")
        
        # 执行步骤
        logger.info(f"[一键更新] 执行 {step_key} 日期 {target_date}")
        
        if step_key == 'sync_index':
            factory = get_index_factory()
            factory.sync_kline(target_date, task_id=task_id)
        
        elif step_key == 'sync_stocks':
            factory = get_stock_factory()
            factory.sync_daily(target_date, task_id=task_id)
        
        elif step_key == 'sync_sectors':
            factory = get_sector_factory()
            factory.sync_daily(target_date, task_id=task_id)
        
        elif step_key == 'rps_stock':
            factory = get_stock_factory()
            logger.info(f"[一键更新] 计算个股涨幅字段")
            factory.compute_chg(target_date)
            logger.info(f"[一键更新] 计算个股RPS")
            factory.compute_rps(target_date)
        
        elif step_key == 'rps_sector':
            factory = get_sector_factory()
            logger.info(f"[一键更新] 计算板块涨幅字段")
            factory.compute_chg(target_date)
            logger.info(f"[一键更新] 计算板块RPS")
            factory.compute_rps(target_date)
        
        elif step_key == 'sync_pe':
            factory = get_index_factory()
            logger.info(f"[一键更新] 同步PE数据")
            factory.sync_pe(target_date)
        
        elif step_key == 'precompute':
            aggregator = get_market_aggregator()
            logger.info(f"[一键更新] 预计算基础数据")
            aggregator.precompute_base_data(target_date, task_id=task_id)
        
        logger.info(f"[一键更新] {step_key} 日期 {target_date} 执行完成")
