"""
One Click Update Orchestrator - 一键更新编排器

核心逻辑：
1. 查询 base_data_daily 中最后更新日期
2. 从该日期+1 到 今天，计算需要补算的交易日
3. 固定7个步骤，每个步骤的 total_count 根据实际数据量设置
4. 日线数据同步可以处理多天，其他步骤处理所有需要的天数

步骤逻辑：
- 步骤0-2（数据同步）：有缓存检查，盘后永久缓存/盘中30分钟缓存
- 步骤3-7（RPS/PE/预计算）：每次都重算
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.server.orchestrators.base import BaseOrchestrator
from app.server.orchestrators.daily_recalc_orchestrator import DailyRecalcOrchestrator as _DailyRecalc

logger = logging.getLogger(__name__)


class OneClickUpdateOrchestrator(BaseOrchestrator):
    """
    一键更新编排器
    固定7个步骤：同步指数 → 同步个股 → 板块同步 → 个股RPS → 板块RPS → PE同步 → 预计算
    RPS和预计算步骤委托给 DailyRecalcOrchestrator
    """
    
    STEP_KEYS = ['sync_index', 'sync_stocks', 'sync_sectors', 'rps_stock', 'rps_sector', 'sync_pe', 'precompute']
    STEP_NAMES = ['同步指数', '同步个股', '同步板块', '计算个股RPS', '计算板块RPS', '更新PE', '预计算基础数据']

    def get_steps(self) -> List[Dict[str, str]]:
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
    
    def _get_step_totals(self, dates: List[str]) -> Dict[str, int]:
        """
        查询各步骤的实际数据量
        - sync_index: index_basics启用数
        - sync_stocks: stock_basics启用数
        - sync_sectors: sector_basics启用数
        - rps_stock: 需要计算的交易天数
        - rps_sector: 需要计算的交易天数
        - sync_pe: 需要更新的交易天数（与指数数相同）
        - precompute: 需要计算的交易天数
        """
        from app.data.db import get_db
        db = get_db()
        
        # 启用的数量
        index_count = db['index_basics'].count_documents({'is_disable': False})
        stock_count = db['stock_basics'].count_documents({'is_disable': False})
        sector_count = db['sector_basics'].count_documents({'is_disable': False})
        
        # 需要计算的交易天数
        trading_days_count = len(dates)
        
        logger.info(f"[一键更新] 数据量: 指数={index_count}, 个股={stock_count}, 板块={sector_count}, 交易天数={trading_days_count}")
        
        return {
            'sync_index': index_count,
            'sync_stocks': stock_count,
            'sync_sectors': sector_count,
            'rps_stock': trading_days_count,
            'rps_sector': trading_days_count,
            'sync_pe': trading_days_count,
            'precompute': trading_days_count,
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
        step_totals = self._get_step_totals(dates)
        
        # 生成固定7个步骤
        steps = []
        for key, name in zip(self.STEP_KEYS, self.STEP_NAMES):
            steps.append({
                'key': key,
                'name': name,
                'total_count': step_totals.get(key, 1),
                'completed_count': 0,
            })
        
        logger.info(f"[一键更新] 步骤配置: {[(s['name'], s['total_count']) for s in steps]}")
        
        # 创建任务
        import uuid
        task_id = str(uuid.uuid4())
        self.task_repo.create_task(task_id, steps, name='一键更新')
        
        # 使用线程池提交任务
        from app.server.orchestrators.base import _executor
        _executor.submit(self._run, task_id, dates)
        
        return task_id
    
    def _run(self, task_id: str, dates: List[str]) -> None:
        """后台执行流程"""
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()

        total_dates = len(dates)
        logger.info(f"[一键更新] 开始执行，共 {total_dates} 个交易日")

        for step_idx, step_key in enumerate(self.STEP_KEYS):
            # 检查任务是否已取消
            if tm.is_cancelled(task_id):
                logger.info(f'任务 {task_id} 已取消，停止执行')
                return

            step_name = self.STEP_NAMES[step_idx]
            logger.info(f"[一键更新] 步骤 {step_idx+1}/7: {step_name}")

            # 重置步骤进度（只更新 current_step 和 status）
            self.task_repo.update_step_progress(task_id, step_idx, status='running', completed_count=0)
            self.task_repo.update_task_progress(task_id, current_step=step_idx)

            try:
                self.execute_step(step_key, task_id, dates, step_idx)
            except Exception as e:
                logger.error(f'[一键更新] 步骤 {step_name} 失败: {e}', exc_info=True)
                self.task_repo.update_step_progress(
                    task_id, step_idx,
                    status='failed',
                    message=str(e)[:200]
                )
                self.task_repo.fail_task(task_id, f'步骤失败: {str(e)[:200]}')
                return

            self.task_repo.update_step_progress(
                task_id, step_idx,
                status='completed',
                message=f'{step_name}完成'
            )
            logger.info(f"[一键更新] 步骤 {step_idx+1}/7: {step_name} 完成")

        self.task_repo.complete_task(task_id, '全部完成')
        logger.info(f'[一键更新] 全部完成，共处理 {total_dates} 个交易日')
    
    def _is_data_synced_for_date(self, collection_name: str, date_field: str, target_date: str, expected_count: int = 0) -> bool:
        """
        检查指定日期的数据是否已同步
        盘中（15:30前）：30分钟缓存，需要重新同步
        盘后（15:30后）：is_final=True 才跳过（需要更新收盘价）
        :param expected_count: 期望的数据量，0表示不检查数量
        """
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        today_str = now.strftime('%Y%m%d')

        from app.data.db import get_db
        db = get_db()

        # 非今天的数据，检查 is_final=True
        if target_date != today_str:
            count = db[collection_name].count_documents({date_field: target_date, 'is_final': True})
            if expected_count > 0:
                return count >= expected_count
            return count > 0

        # 今天的数据
        is_market_closed = now.hour > 15 or (now.hour == 15 and now.minute >= 30)

        if is_market_closed:
            # 盘后：检查 is_final=True（需要更新收盘价）
            count = db[collection_name].count_documents({date_field: target_date, 'is_final': True})
            if expected_count > 0:
                return count >= expected_count
            return count > 0
        else:
            # 盘中：30分钟缓存，检查最后更新时间
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

            # 盘中缓存命中还需检查数据量是否达标，避免部分同步被误判为已完成
            if expected_count > 0:
                count = db[collection_name].count_documents({date_field: target_date})
                if count < expected_count:
                    return False

            return True
    
    def execute_step(self, step_key: str, task_id: str, dates: List[str], step_idx: int = 0) -> None:
        """执行单个步骤"""
        from app.server.factories import get_index_factory

        total_dates = len(dates)

        # 步骤0-2：数据同步（检查缓存，进度由 _sync_progress 线程同步）
        if step_key in ['sync_index', 'sync_stocks', 'sync_sectors']:
            self._execute_sync_step(step_key, task_id, dates, step_idx)

        # 步骤3-4：RPS计算 → 复用 DailyRecalcOrchestrator.compute_for_step
        elif step_key in ('rps_stock', 'rps_sector'):
            for i, date in enumerate(dates):
                _DailyRecalc.compute_for_step(step_key, date)
                self.task_repo.update_step_progress(task_id, step_idx, completed_count=i + 1, message=f'{date} {step_key}')

        elif step_key == 'sync_pe':
            factory = get_index_factory()
            for i, date in enumerate(dates):
                logger.info(f"[一键更新] 更新 {date} PE数据")
                factory.sync_pe(date)
                self.task_repo.update_step_progress(task_id, step_idx, completed_count=i + 1, message=f'{date} PE')

        # 步骤6：预计算 → 复用 DailyRecalcOrchestrator.compute_for_step
        elif step_key == 'precompute':
            for i, date in enumerate(dates):
                _DailyRecalc.compute_for_step(step_key, date, task_id=task_id)
                self.task_repo.update_step_progress(task_id, step_idx, completed_count=i + 1, message=f'{date} 预计算')
    
    def _execute_sync_step(self, step_key: str, task_id: str, dates: List[str], step_idx: int = 0) -> None:
        """执行数据同步步骤（检查缓存，失败率超过5%则停止）"""
        from app.server.factories import get_index_factory, get_stock_factory, get_sector_factory

        if step_key == 'sync_index':
            collection, field = 'index_daily', 'trade_date'
            factory = get_index_factory()
            sync_method = factory.sync_kline
        elif step_key == 'sync_stocks':
            collection, field = 'stock_daily', 'trade_date'
            factory = get_stock_factory()
            sync_method = factory.sync_daily
        else:  # sync_sectors
            collection, field = 'sector_daily', 'trade_date'
            factory = get_sector_factory()
            sync_method = factory.sync_daily

        # 检查哪些日期需要同步
        # 获取期望的数据量（从步骤的 total_count）
        from app.data.db import get_db
        db = get_db()
        step_doc = db['sync_tasks'].find_one(
            {'task_id': task_id},
            {'_id': 0, 'steps': 1}
        )
        expected_count = 0
        if step_doc and 'steps' in step_doc and step_idx < len(step_doc['steps']):
            expected_count = step_doc['steps'][step_idx].get('total_count', 0)

        dates_to_sync = []
        for date in dates:
            if not self._is_data_synced_for_date(collection, field, date, expected_count):
                dates_to_sync.append(date)
            else:
                logger.info(f"[一键更新] {step_key} 日期 {date} 已有数据，跳过")

        if not dates_to_sync:
            logger.info(f"[一键更新] {step_key} 所有日期数据已存在，跳过")
            # 标记步骤完成：completed_count = total_count
            db['sync_tasks'].update_one(
                {'task_id': task_id},
                {'$set': {
                    f'steps.{step_idx}.completed_count': expected_count,
                    f'steps.{step_idx}.message': '数据已存在，跳过同步'
                }}
            )
            # 同步指数后需要计算涨跌幅（chg_pct）
            if step_key == 'sync_index':
                logger.info(f"[一键更新] {step_key} 计算指数涨跌幅")
                factory.compute_chg()
            return

        logger.info(f"[一键更新] {step_key} 需要同步 {len(dates_to_sync)} 个日期: {dates_to_sync}")

        # 执行同步
        for i, date in enumerate(dates_to_sync):
            logger.info(f"[一键更新] 同步 {step_key} 日期 {date}")

            # 创建进度回调，实时更新步骤进度
            def progress_callback(current, total, message=''):
                self.task_repo.update_step_progress(
                    task_id, step_idx,
                    completed_count=current,
                    total_count=total,
                    message=message or f'同步 {date}'
                )

            result = sync_method(date, task_id=task_id, progress_callback=progress_callback)

            # 更新步骤进度（最终状态）：不覆盖 completed_count，保留 progress_callback 设的实际值
            self.task_repo.update_step_progress(task_id, step_idx, message=f'同步 {date} 完成')

            # 检查失败率，超过5%则停止
            if hasattr(result, 'failed') and hasattr(result, 'total'):
                if result.total > 0:
                    fail_rate = result.failed / result.total
                    if fail_rate > 0.05:
                        raise Exception(f'{step_key} 失败率 {fail_rate:.1%} 超过阈值，停止执行')

        # 同步指数后需要计算涨跌幅（chg_pct）
        if step_key == 'sync_index':
            logger.info(f"[一键更新] {step_key} 计算指数涨跌幅")
            factory.compute_chg()
