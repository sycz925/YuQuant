"""
DataManager — MongoDB + 多数据源 + 多线程 同步 A 股日线数据
"""
import logging
import pandas as pd
import threading
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from .db import (
    get_stock_basics, bulk_upsert_stock_basics,
    get_daily_data, bulk_upsert_daily_data, has_daily_data,
    get_stock_sync_start_date, get_sector_sync_start_date,
    get_index_basics, upsert_index_basics
)
from .sources.pytdx_source import PytdxSource as PyTdXSource
from .sources.akshare_source import AkShareSource
from .sources.baostock_source import BaoStockSource
from .sources.yfinance_source import YFinanceSource

logger = logging.getLogger(__name__)

# 北京时间时区
BJ_TZ = ZoneInfo('Asia/Shanghai')

# 时间窗口常量（分钟数，从 00:00 起算）
LUNCH_START = 11 * 60 + 30   # 11:30 盘中同步开放
LUNCH_END = 13 * 60          # 13:00 盘中同步关闭
AFTER_MARKET_START = 15 * 60 + 30  # 15:30 盘后同步开放（留30分钟缓冲，等交易所清算）


class DataManager:
    def __init__(self):
        # 数据源（按优先级：PyTdX > AkShare > BaoStock > yfinance）
        self.pytdx = PyTdXSource()
        self.akshare = AkShareSource()
        self.baostock = BaoStockSource()
        self.yfinance = YFinanceSource()

    @staticmethod
    def _now_bj() -> datetime:
        """获取当前北京时间"""
        return datetime.now(BJ_TZ)

    @staticmethod
    def _time_minutes() -> int:
        """获取当前北京时间的分钟数（从 00:00 起算）"""
        now = datetime.now(BJ_TZ)
        return now.hour * 60 + now.minute

    @staticmethod
    def _today_str() -> str:
        """获取当前北京时间的今天日期字符串 YYYYMMDD"""
        return datetime.now(BJ_TZ).strftime('%Y%m%d')

    def sync_stock_basics(self) -> int:
        """同步股票基础信息，返回成功数量（不获取流通股本，保持快速）"""
        # 按优先级尝试获取数据
        df = None

        df = self.pytdx.get_stock_basics()
        if df is None or df.empty:
            df = self.akshare.get_stock_basics()
        if df is None or df.empty:
            df = self.baostock.get_stock_basics()

        if df is None or df.empty:
            return 0

        # 保存到 MongoDB
        docs = []
        for _, row in df.iterrows():
            doc = {
                'stock_code': row['stock_code'],
                'stock_name': row['stock_name'],
                'market': row['market'],
                'list_date': row.get('list_date'),
                'is_st': 'ST' in row['stock_name'],
                'suspend': False,
            }
            docs.append(doc)

        bulk_upsert_stock_basics(docs)
        return len(docs)

    def sync_index_basics(self) -> int:
        """同步指数基础信息"""
        # 从数据库 index_basics 读取指数配置（如果有），否则写入默认种子数据
        indexes = [
            ('000001', '上证指数', 1, '000001'),
            ('000688', '科创50', 1, '000688'),
            ('399006', '创业板指', 0, '399006'),
            ('000905', '中证500', 1, '000905'),
            ('399106', '深圳综指', 0, '399106'),
            ('880003', '平均股价', 1, '880003'),
        ]

        for code, name, market, tdx_code in indexes:
            upsert_index_basics(code, name, market, tdx_code)

        return len(indexes)

    def _sync_single_stock(self, stock_code: str, stock_name: str, start_date: str, end_date: str) -> Dict:
        """同步单只股票数据（线程池内调用，不更新任务状态）
        数据源瀑布：PyTdX → AkShare → BaoStock → yfinance
        """
        result = {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'status': 'pending',
            'source': '',
            'error': None
        }

        # 防护：起始日期晚于结束日期，无需同步
        if start_date and end_date and start_date > end_date:
            result['status'] = 'skipped'
            return result

        from app.data.db import get_collection
        stock_coll = get_collection('stock')

        # 检查该股票当天是否已有数据，有则跳过
        # 盘后(15:30+)：is_final=true 才跳过（需要更新收盘价）
        # 盘中(11:30-13:00)：有数据就跳过
        if end_date:
            t = self._time_minutes()
            if t >= AFTER_MARKET_START:
                # 盘后：检查 is_final=true
                existing = stock_coll.find_one(
                    {'stock_code': stock_code, 'trade_date': end_date,
                     'is_final': True, 'close': {'$gt': 0}},
                    projection={'_id': 1}
                )
            else:
                # 盘中：有数据就跳过
                existing = stock_coll.find_one(
                    {'stock_code': stock_code, 'trade_date': end_date, 'close': {'$gt': 0}},
                    projection={'_id': 1}
                )
            if existing:
                result['status'] = 'skipped'
                return result

        # 检查是否停牌
        latest_doc = stock_coll.find_one(
            {'stock_code': stock_code, 'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, 'is_final': 1, '_id': 0}
        )
        if latest_doc:
            latest_date = latest_doc.get('trade_date', '')

            # 如果最新数据日期早于请求的结束日期，可能是停牌
            if latest_date and latest_date < end_date:
                recent_doc = stock_coll.find_one(
                    {'stock_code': stock_code, 'trade_date': {'$gte': end_date}, 'close': {'$gt': 0}},
                    projection={'trade_date': 1, '_id': 0}
                )
                if not recent_doc:
                    from app.data.holidays import filter_workdays
                    try:
                        workdays = filter_workdays(latest_date, end_date)
                        suspend_days = len(workdays) - 1
                        if suspend_days >= 3:
                            result['status'] = 'skipped'
                            result['error'] = f'停牌中（最后交易日{latest_date}，已停牌{suspend_days}个交易日）'
                            return result
                    except Exception:
                        pass

        # 数据源瀑布：按优先级逐个尝试，每个源最多 30 秒
        sources = [
            (self.pytdx, 'PyTdX'),
            (self.akshare, 'AkShare'),
            (self.baostock, 'BaoStock'),
            (self.yfinance, 'yfinance'),
        ]
        failure_reasons = []

        for source_obj, source_name in sources:
            try:
                with ThreadPoolExecutor(max_workers=1) as source_executor:
                    future = source_executor.submit(
                        source_obj.get_daily_data, stock_code, start_date, end_date
                    )
                    df, source = future.result(timeout=30)
                if df is not None and not df.empty:
                    # 成功获取数据，写入 MongoDB
                    records = df.to_dict('records')
                    bulk_upsert_daily_data(stock_code, records, source)
                    result['status'] = 'success'
                    result['source'] = source
                    return result
                failure_reasons.append(f"{source_name}: 未返回数据")
            except TimeoutError:
                failure_reasons.append(f"{source_name}: 超时 30s")
            except Exception as e:
                failure_reasons.append(f"{source_name}: {str(e)}")

        # 所有数据源都失败
        result['status'] = 'failed'
        result['error'] = " | ".join(failure_reasons) if failure_reasons else '获取数据失败'
        return result

    @staticmethod
    def _count_final_records(data_type: str, trade_date: str) -> int:
        """统计某天 is_final=true 的收盘数据记录数"""
        from .db import get_collection
        coll = get_collection(data_type)
        return coll.count_documents({
            'trade_date': trade_date,
            'is_final': True,
            'close': {'$gt': 0}
        })

    def _find_sync_boundary(self, data_type: str, start_day: str, expected: int,
                            sync_fn=None, **sync_kwargs) -> Optional[str]:
        """边找边界边同步
        返回 None：数据已完整（或超过10年），停止
        返回日期：该天需要同步，sync_fn 已执行，继续检查上一天
        """
        day = start_day
        while True:
            # 超过10年停止
            try:
                day_dt = datetime.strptime(day, '%Y%m%d')
                if (datetime.now(BJ_TZ).date() - day_dt.date()).days > 3650:
                    return None
            except Exception:
                return None

            from .holidays import is_workday
            if not is_workday(day):
                day = (datetime.strptime(day, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
                continue

            # 是交易日，检查数据量
            count = self._count_final_records(data_type, day)
            threshold = int(expected * 0.95)

            if count >= threshold:
                return None  # 数据已完整，停止

            # 数据不足，执行同步
            if sync_fn:
                sync_fn(day, **sync_kwargs)

            # 返回上一天继续找
            return (datetime.strptime(day, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')

    def sync_daily_data(self, stock_codes: List[str], end_date: str = None,
                        task_id: Optional[str] = None, max_workers: int = 16, is_external: bool = False,
                        progress_callback: Callable = None) -> dict:
        """同步个股日线数据 — 逐天回溯模式"""
        from .task_manager import get_task_manager

        tm = get_task_manager() if task_id else None
        expected = len(stock_codes)
        today = self._today_str()

        # 获取股票名称
        stock_df = self.get_stock_list()
        stock_name_map = {}
        if not stock_df.empty:
            stock_name_map = dict(zip(stock_df['stock_code'], stock_df['stock_name']))

        total_success = 0
        total_fail = 0
        total_skipped = 0
        data_sources_used = {}
        days_synced = 0

        def sync_day(day, **kwargs):
            nonlocal total_success, total_fail, total_skipped, days_synced
            days_synced += 1
            logger.info(f"同步 {day}")

            # 如果有 progress_callback，使用它更新步骤进度
            # 否则更新顶层进度（兼容旧代码）
            if progress_callback:
                progress_callback(0, expected, f"同步 {day}...")
            elif tm and task_id:
                tm.update_task_progress(task_id, current_stock=day,
                                        current_stock_name=f"同步 {day}...",
                                        total_count=expected,
                                        completed_count=0)

            day_processed = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {}
                for stock_code in stock_codes:
                    stock_name = stock_name_map.get(stock_code, stock_code)
                    future = executor.submit(
                        self._sync_single_stock, stock_code, stock_name, day, day
                    )
                    future_map[future] = (stock_code, stock_name)

                for future in as_completed(future_map):
                    if tm and tm.is_cancelled(task_id):
                        for f in future_map:
                            f.cancel()
                        break
                    try:
                        stock_code, stock_name = future_map[future]
                        try:
                            result = future.result(timeout=60)
                        except TimeoutError:
                            logger.error(f"同步超时 60s: {stock_code} {stock_name}")
                            total_fail += 1
                            if progress_callback:
                                progress_callback(day_processed, expected, f"同步超时: {stock_code}")
                            elif tm and task_id:
                                tm.update_task_progress(task_id, increment_failed=1,
                                    failed_stock={'stock_code': stock_code, 'stock_name': stock_name,
                                                  'error': '同步超时 60s'})
                            day_processed += 1
                            if progress_callback:
                                progress_callback(day_processed, expected, f"同步 {day}")
                            elif tm and task_id:
                                tm.update_task_progress(task_id,
                                    current_stock=day,
                                    current_stock_name=f"同步 {day}",
                                    total_count=expected,
                                    completed_count=day_processed)
                            continue
                        result['stock_code'] = stock_code
                        result['stock_name'] = stock_name
                        if result['status'] == 'success':
                            total_success += 1
                            if result['source']:
                                data_sources_used[result['source']] = data_sources_used.get(result['source'], 0) + 1
                        elif result['status'] == 'failed':
                            total_fail += 1
                        else:
                            total_skipped += 1
                    except Exception as e:
                        logger.warning(f"任务异常: {stock_code} {stock_name} - {e}")
                        total_fail += 1

                    day_processed += 1
                    if day_processed % 500 == 0:
                        logger.info(f"  {day} 进度: {day_processed}/{expected} "
                                    f"(成功{total_success} 失败{total_fail} 跳过{total_skipped})")
                    if progress_callback:
                        progress_callback(day_processed, expected, f"同步 {day}")
                    elif tm and task_id:
                        tm.update_task_progress(task_id,
                            current_stock=day,
                            current_stock_name=f"同步 {day}",
                            total_count=expected,
                            completed_count=day_processed)

        # 循环调用 _find_sync_boundary，直到返回 None
        day = today
        while True:
            result = self._find_sync_boundary('stock', day, expected, sync_fn=sync_day)
            if result is None:
                break
            day = result

        if days_synced == 0:
            logger.info("✓ 个股数据已完整，无需同步")
            if tm and task_id and not is_external:
                tm.complete_task(task_id, "无需同步")
            return {'total': expected, 'success': 0, 'fail': 0, 'skipped': expected, 'sources': {}}

        logger.info("计算涨幅字段...")
        try:
            self.calculate_chg_fields(target='stock')
        except Exception as e:
            logger.error(f"计算涨幅字段失败: {e}")

        msg = f"同步完成: {days_synced} 天, 成功 {total_success}, 跳过 {total_skipped}, 失败 {total_fail}"
        logger.info(msg)
        if tm and task_id and not is_external:
            tm.complete_task(task_id, msg, data_sources_used)

        return {
            'total': expected, 'success': total_success, 'fail': total_fail,
            'skipped': total_skipped, 'sources': data_sources_used
        }

    # ==================== 板块同步 ====================

    @staticmethod
    def _update_sector_is_final(sector_coll):
        """更新 sector_daily 的 is_final 字段
        规则：只把今天之前的日期标为 is_final=True
        今天的 is_final 由 bulk_upsert_daily_data 在写入时设置（盘后后=True）
        """
        try:
            today_str = datetime.now(BJ_TZ).strftime('%Y%m%d')
            sector_coll.update_many(
                {'trade_date': {'$lt': today_str}, 'is_final': {'$ne': True}},
                {'$set': {'is_final': True}}
            )
        except Exception as e:
            logger.error(f"更新sector is_final失败: {e}")

    def sync_sector_indices(self, task_id=None, progress_callback=None, enabled_codes=None, is_external=False) -> dict:
        """同步板块指数日线 — 边找边界边同步"""
        from .db import get_db, get_collection
        from .task_manager import get_task_manager

        tm = get_task_manager() if task_id else None
        db = get_db()

        if progress_callback:
            progress_callback(0, 0, "读取板块列表...")

        # 查询所有启用的板块（包括通达信和东方财富）
        query = {'is_disable': {'$ne': True}}
        if enabled_codes is not None:
            query['code'] = {'$in': list(enabled_codes)}
        
        existing_sectors = list(db['sector_basics'].find(
            query,
            {'_id': 0, 'code': 1, 'name': 1, 'tdx_code': 1, 'source': 1}
        ))

        if not existing_sectors:
            return {'block_count': 0, 'sector_daily_count': 0, 'error': '没有可同步的板块'}

        total_sectors = len(existing_sectors)
        today = self._today_str()
        sector_coll = get_collection('sector')
        days_synced = 0

        def sync_day(day, **kwargs):
            nonlocal days_synced
            days_synced += 1
            logger.info(f"同步板块 {day}")

            if tm and task_id:
                tm.update_task_progress(task_id, current_stock=day,
                                        current_stock_name=f"同步板块 {day}...")

            try:
                prev_day = (datetime.strptime(day, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
            except Exception:
                prev_day = (datetime.now(BJ_TZ) - timedelta(days=365)).strftime('%Y%m%d')

            from threading import Lock
            from concurrent.futures import ThreadPoolExecutor, as_completed
            progress_lock = Lock()
            day_written = 0
            day_processed = 0

            def _sync_sector_day(idx, sec):
                nonlocal day_written
                sector_code = sec['code']
                tdx_code = sec.get('tdx_code', sector_code)
                source = sec.get('source', 'unknown')
                
                # 根据source设置data_source标记
                if source == '同花顺':
                    data_source = 'ths'
                elif source == '东方财富':
                    data_source = 'eastmoney'
                elif source == '通达信概念':
                    data_source = 'tdx_concept'
                else:
                    data_source = 'pytdx'

                # 检查该板块当天是否已有数据
                t = self._time_minutes()
                if t >= AFTER_MARKET_START:
                    existing = sector_coll.find_one(
                        {'stock_code': sector_code, 'trade_date': day,
                         'is_final': True, 'close': {'$gt': 0}},
                        projection={'_id': 1}
                    )
                else:
                    existing = sector_coll.find_one(
                        {'stock_code': sector_code, 'trade_date': day, 'close': {'$gt': 0}},
                        projection={'_id': 1}
                    )
                if existing:
                    return

                # 根据source获取数据：东方财富用akshare，通达信用pytdx
                kline = None
                if source == '东方财富':
                    # 东方财富行业板块：用akshare获取
                    try:
                        kline = self.akshare.get_industry_hist(sector_code, prev_day, day)
                    except Exception as e:
                        logger.warning(f"akshare获取东方财富行业 {sector_code} 失败: {e}")
                else:
                    # 通达信概念板块：用pytdx获取
                    try:
                        kline = self.pytdx.get_tdx_index_daily(
                            tdx_code, market=1, start_date=prev_day, end_date=day, max_bars=5
                        )
                    except Exception as e:
                        logger.warning(f"pytdx获取通达信板块 {sector_code} 失败: {e}")

                if kline is not None and len(kline) > 0:
                    new_records = []
                    for _, r in kline.iterrows():
                        if str(r['trade_date']) == day:
                            new_records.append({
                                'trade_date': day,
                                'close': float(r['close']),
                                'open': float(r.get('open', 0)),
                                'high': float(r.get('high', 0)),
                                'low': float(r.get('low', 0)),
                                'volume': float(r.get('volume', 0)),
                                'amount': float(r.get('amount', 0)),
                            })
                    if new_records:
                        from app.data.db import bulk_upsert_daily_data
                        bulk_upsert_daily_data(sector_code, new_records, data_source, 'sector')
                        with progress_lock:
                            day_written += len(new_records)

            max_workers = min(16, total_sectors)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_sync_sector_day, idx, sec): idx
                           for idx, sec in enumerate(existing_sectors)}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.warning(f"板块同步异常: {e}")
                    day_processed += 1
                    if tm and task_id:
                        tm.update_task_progress(task_id,
                            current_stock=day,
                            current_stock_name=f"同步板块 {day}",
                            total_count=total_sectors,
                            completed_count=day_processed)

            logger.info(f"  {day} 写入 {day_written} 条")

        # 循环调用 _find_sync_boundary
        day = today
        while True:
            result = self._find_sync_boundary('sector', day, total_sectors, sync_fn=sync_day)
            if result is None:
                break
            day = result

        # 更新历史数据的 is_final
        self._update_sector_is_final(sector_coll)

        if days_synced == 0:
            logger.info("✓ 板块数据已完整，无需同步")
            if tm and task_id and not is_external:
                tm.complete_task(task_id, "无需同步")
        else:
            msg = f"板块同步完成: {days_synced} 天"
            logger.info(msg)
            if tm and task_id and not is_external:
                tm.complete_task(task_id, msg)

        return {'block_count': total_sectors, 'sector_daily_count': days_synced}

    # ==================== RPS 计算 ====================

    def calculate_rps(self, target: str = 'all', max_dates: Optional[int] = None) -> dict:
        """
        计算 RPS
        Args:
            target: 'all' - 全部, 'stock' - 仅个股, 'sector' - 仅板块
            max_dates: 仅计算最近 N 天（None 则计算所有历史）
        """
        from app.engine.factor_engine import FactorEngine
        engine = FactorEngine()
        result = {}
        if target in ('all', 'stock'):
            result['stock'] = engine.calculate_rps(data_type='stock', max_dates=max_dates)
        if target in ('all', 'sector'):
            result['sector'] = engine.calculate_rps(data_type='sector', max_dates=max_dates)
        return result

    def calculate_chg_fields(self, target: str = 'all', trade_date: str = None) -> dict:
        """
        计算涨幅字段 - 只计算指定日期或最新日期，不全量加载
        使用向量化 shift 替代 lambda transform，性能提升 10x+
        """
        from app.data.db import get_collection
        from pymongo import UpdateOne
        import time as _time

        result = {}
        for data_type in (['stock', 'sector'] if target == 'all' else [target]):
            coll = get_collection(data_type)
            t0 = _time.time()

            # 确定日期
            if trade_date:
                dates = [trade_date]
            else:
                latest = coll.find_one({'close': {'$gt': 0}}, sort=[('trade_date', -1)], projection={'trade_date': 1, '_id': 0})
                if not latest:
                    result[data_type] = 0
                    continue
                dates = [latest['trade_date']]

            # 加载这些日期 + 前250天数据（计算区间涨幅需要）
            try:
                max_date = max(dates)
                min_date = (datetime.strptime(max_date, '%Y%m%d') - timedelta(days=300)).strftime('%Y%m%d')
            except Exception:
                min_date = dates[0]

            cursor = coll.find(
                {'trade_date': {'$gte': min_date}, 'close': {'$gt': 0}},
                {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
            )
            df = pd.DataFrame(list(cursor))
            if df.empty:
                result[data_type] = 0
                continue

            df = df.sort_values(['stock_code', 'trade_date']).reset_index(drop=True)
            g = df.groupby('stock_code')

            # 向量化计算：用 shift 替代 lambda transform
            df['_prev'] = g['close'].shift(1)
            df['chg_pct'] = ((df['close'] - df['_prev']) / df['_prev'] * 100).round(2)

            # 获取每只股票的第一天收盘价（用于数据不足时的回退）
            first_close = g['close'].transform('first')

            for p in [5, 10, 20, 50, 120, 250]:
                shifted = g['close'].shift(p)
                # 数据不足p天时，用第一天收盘价作为基准
                shifted_filled = shifted.fillna(first_close)
                df[f'chg_{p}d'] = ((df['close'] / shifted_filled - 1) * 100).round(2)

            # 只写入目标日期的数据
            target_df = df[df['trade_date'].isin(dates)]
            fields = ['chg_pct'] + [f'chg_{p}d' for p in [5, 10, 20, 50, 120, 250]]

            update_time = datetime.utcnow()
            ops = []
            for rec in target_df[['stock_code', 'trade_date'] + [f for f in fields if f in target_df.columns]].to_dict('records'):
                set_doc = {'update_time': update_time}
                for f in fields:
                    v = rec.get(f)
                    if v is not None and not pd.isna(v):
                        set_doc[f] = float(v)
                if len(set_doc) > 1:
                    ops.append(UpdateOne(
                        {'stock_code': rec['stock_code'], 'trade_date': rec['trade_date']},
                        {'$set': set_doc}
                    ))

            if ops:
                coll.bulk_write(ops, ordered=False)

            elapsed = _time.time() - t0
            logger.info(f"[chg-{data_type}] {dates} {len(ops)} 条, {elapsed:.0f}秒")
            result[data_type] = len(ops)

        return result

    def calculate_all_derived_fields(self, target: str = 'all', trade_date: str = None, backfill: bool = False) -> dict:
        """
        计算所有冗余字段（MA、VOL_MA、CHG、涨跌幅、百分位）
        Args:
            target: 'all' - 全部, 'stock' - 仅个股, 'sector' - 仅板块
            trade_date: 指定日期，None则计算最新日期
            backfill: True则回刷所有历史数据
        """
        from app.engine.factor_engine import FactorEngine
        engine = FactorEngine()
        result = {}
        if target in ('all', 'stock'):
            result['stock'] = engine.calculate_all_derived(data_type='stock', trade_date=trade_date, backfill=backfill)
        if target in ('all', 'sector'):
            result['sector'] = engine.calculate_all_derived(data_type='sector', trade_date=trade_date, backfill=backfill)
        return result

    # ==================== 查询方法 ====================

    def get_stock_list(self) -> pd.DataFrame:
        """获取股票列表"""
        return get_stock_basics()

    def get_index_list(self) -> pd.DataFrame:
        """获取指数列表"""
        return get_index_basics()

    def get_stock_daily_data(self, stock_code: str, start_date: Optional[str] = None,
                              end_date: Optional[str] = None) -> pd.DataFrame:
        """获取股票日线数据"""
        return get_daily_data(stock_code, start_date, end_date)

    # ==================== 兼容旧接口 ====================

    def has_daily_data(self, stock_code: str) -> bool:
        """检查是否有日线数据"""
        df = self.get_stock_daily_data(stock_code)
        return not df.empty

    def close(self):
        """关闭（旧接口兼容）"""
        pass


# 全局单例
_data_manager_instance = None


def get_data_manager() -> DataManager:
    """获取 DataManager 单例"""
    global _data_manager_instance
    if _data_manager_instance is None:
        _data_manager_instance = DataManager()
    return _data_manager_instance
