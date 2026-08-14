"""
DataManager — MongoDB + 多数据源 + 多线程 同步 A 股日线数据
"""
import logging
import os
import time
import socket
import pandas as pd
import numpy as np
import threading
from typing import List, Optional, Dict, Tuple, Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from .db import (
    get_stock_basics, bulk_upsert_stock_basics,
    get_daily_data, bulk_upsert_daily_data, has_daily_data,
    get_stock_sync_start_date, get_sector_sync_start_date,
    get_index_basics, upsert_index_basics,
    get_etf_basics, bulk_upsert_etf_basics,
    get_xdxr_fingerprint, set_xdxr_fingerprint
)
from .sources.pytdx_source import PytdxSource as PyTdXSource, MARKET_SH, MARKET_SZ
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

# ==================== 数据源并发与超时保护 ====================
# 根因：单只股票对每个数据源启动一个 daemon 线程 + join(timeout=30)，
# 超时后线程仍存活不销毁。当数据源（akshare/baostock/yfinance）的底层
# 请求没有真实超时、网络又出问题时，线程会无限累积，最终突破 macOS
# 每进程 4096 线程限制（kern.num_taskthreads），导致 getaddrinfo() 无法
# 创建线程、/api/health 无响应、前端显示离线。
#
# 修复策略：
# 1. 全局信号量限制同时进行的数据源请求数，从源头掐断线程爆炸
# 2. socket.setdefaulttimeout 提供兜底超时，保证请求线程最终会结束
MAX_SOURCE_CONCURRENCY = 16
_SOURCE_SEMAPHORE = threading.BoundedSemaphore(MAX_SOURCE_CONCURRENCY)
_SOCKET_TIMEOUT = 30  # 秒，兜底网络超时（线程池内避免阻塞）

# 数据源熔断：连续失败达到阈值后暂停该源一段时间
BREAKER_FAIL_THRESHOLD = 10
BREAKER_COOLDOWN_SECONDS = 120

# xdxr 除权指纹缓存（进程生命周期内，按日期隔离）
# 同一交易日内同一股票的 xdxr 事件不变，无需反复拉取
# 结构：{date: {stock_code: fingerprint}}，fingerprint None=拉取失败，''=无事件
_XDXR_FINGERPRINT_CACHE: Dict[str, Dict[str, Optional[str]]] = {}


class _SourceBreaker:
    """数据源熔断器：连续失败 N 次后暂停该源 cooldown 秒"""

    def __init__(self):
        self._failures: Dict[str, int] = {}
        self._open_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def record_failure(self, source_name: str) -> bool:
        """记录一次失败，返回是否触发熔断"""
        with self._lock:
            count = self._failures.get(source_name, 0) + 1
            self._failures[source_name] = count
            if count >= BREAKER_FAIL_THRESHOLD:
                self._open_until[source_name] = time.time() + BREAKER_COOLDOWN_SECONDS
                self._failures[source_name] = 0
                logger.warning(f"数据源 {source_name} 连续失败 {count} 次，熔断 {BREAKER_COOLDOWN_SECONDS}s")
                return True
            return False

    def record_success(self, source_name: str):
        with self._lock:
            self._failures[source_name] = 0
            self._open_until.pop(source_name, None)

    def is_open(self, source_name: str) -> bool:
        """是否处于熔断打开状态（应跳过该源）"""
        with self._lock:
            until = self._open_until.get(source_name)
            if until is None:
                return False
            if time.time() >= until:
                self._open_until.pop(source_name, None)
                return False
            return True


_SOURCE_BREAKER = _SourceBreaker()

# 当日无数据股票缓存（date -> set[stock_code]）
# 停牌/退市/未上市股票在目标日无数据（源返回空 DataFrame），
# 首次确认后本轮同步直接跳过，避免对每只无数据股票反复拉取多个源。
_NO_DATA_CACHE: Dict[str, set] = {}


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

        # 清理名称中的临时前缀（XD/XR/DR 除权除息标记），避免脏前缀留库
        df['stock_name'] = df['stock_name'].apply(PyTdXSource.clean_stock_name)

        # 从 AkShare 获取正确名称覆盖（通达信除权除息日名称可能不完整）
        try:
            ak_df = self.akshare.get_stock_basics()
            if ak_df is not None and not ak_df.empty:
                ak_map = dict(zip(ak_df['stock_code'], ak_df['stock_name']))
                corrected = 0
                for idx, row in df.iterrows():
                    correct_name = ak_map.get(row['stock_code'])
                    if correct_name and correct_name != row['stock_name']:
                        df.at[idx, 'stock_name'] = correct_name
                        corrected += 1
                if corrected > 0:
                    logger.info(f'[数据更新] AkShare名称纠错: {corrected} 条')
        except Exception as e:
            logger.warning(f'[数据更新] AkShare名称纠错失败: {e}')

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

    def sync_etf_basics(self) -> int:
        """从 etf.txt 同步ETF基础信息"""
        etf_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'etf.txt')
        if not os.path.exists(etf_file):
            logger.error("etf.txt 不存在")
            return 0

        docs = []
        with open(etf_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('\t') if '\t' in line else line.split()
                if len(parts) >= 2 and parts[0] and parts[-1].isdigit() and len(parts[-1]) == 6:
                    docs.append({'code': parts[-1].strip(), 'name': parts[0].strip()})

        if docs:
            bulk_upsert_etf_basics(docs)
        logger.info(f"ETF基础信息同步完成: {len(docs)} 只")
        return len(docs)

    @staticmethod
    @staticmethod
    def _should_full_reload(stored_fp: Optional[str], current_fp: Optional[str]) -> bool:
        """判断是否需要触发该股全量重拉

        语义（指纹约定：None=从未记录，''=已记录但无事件，其他=事件指纹）：
        - stored_fp is None（从未记录）→ 不重拉（首次同步本身就是全量回溯）
        - stored_fp == current_fp → 无变化，不重拉
        - 其他情况（有记录且发生变化）→ 触发全量重拉
        """
        if stored_fp is None:
            return False
        return stored_fp != current_fp

    def _forward_adjust_records(self, records: List[Dict]) -> List[Dict]:
        """检测除权跳空，对 close/open/high/low 做前复权。

        前复权（最新为基准，历史价格向下除）：
          检测到除权日时，该日之前的全部价格除以复权系数 prev_close/open。
          原始价格存入 close_raw/open_raw/high_raw/low_raw。
        """
        # 数据源可能返回乱序（如 PyTdX 分段拉取拼接），必须先按日期升序，否则断点被误判为除权跳空
        records = sorted(records, key=lambda r: str(r['trade_date']))
        n = len(records)
        if n < 2:
            return records

        arr = {}
        for field in ('close', 'open', 'high', 'low'):
            arr[field] = np.array([r.get(field, r['close']) for r in records], dtype=float)

        cum_factor = 1.0
        xdxr_boundaries = []
        for i in range(n - 1, 0, -1):
            prev_close = arr['close'][i - 1]
            curr_open = arr['open'][i]
            if prev_close <= 0 or curr_open <= 0:
                continue
            gap = abs(curr_open / prev_close - 1)
            if gap > 0.15:
                factor = prev_close / curr_open
                cum_factor *= factor
                xdxr_boundaries.append((i, cum_factor))

        if not xdxr_boundaries:
            return records

        for r in records:
            r['close_raw'] = r['close']
            r['open_raw'] = r.get('open', 0)
            r['high_raw'] = r.get('high', 0)
            r['low_raw'] = r.get('low', 0)

        xdxr_boundaries.reverse()
        prev_idx = 0
        for idx, factor in xdxr_boundaries:
            if prev_idx < idx:
                for field in ('close', 'open', 'high', 'low'):
                    arr[field][prev_idx:idx] /= factor
            prev_idx = idx

        for i, r in enumerate(records):
            for field in ('close', 'open', 'high', 'low'):
                r[field] = round(float(arr[field][i]), 4)

        return records

    def sync_etf_daily(self, etf_codes: List[str] = None, max_workers: int = 16,
                       task_id: str = None, progress_callback: Callable = None) -> dict:
        """同步ETF日线数据 — 逐日检查，跳过已同步日期（与一键更新个股同步逻辑一致）"""
        from .db import get_db
        from .task_manager import get_task_manager

        db = get_db()
        tm = get_task_manager() if task_id else None

        df = get_etf_basics()
        if df.empty:
            return {'total': 0, 'success': 0, 'fail': 0, 'skipped': 0}

        if etf_codes is not None:
            df = df[df['code'].isin(etf_codes)]

        etf_list = df.to_dict('records')
        total = len(etf_list)
        today = self._today_str()

        # 确定需要同步的日期列表（从最新交易日往前）
        from .holidays import is_workday

        # 从数据库获取最新交易日
        latest_doc = db['stock_daily'].find_one(
            {'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        latest_trade = latest_doc['trade_date'] if latest_doc else today

        # 收集需要同步的日期（最多回溯10天）
        dates_to_check = []
        day = latest_trade
        for _ in range(10):
            if is_workday(day):
                dates_to_check.append(day)
            day = (datetime.strptime(day, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')

        # 逐日检查是否需要同步
        dates_to_sync = []
        for date in dates_to_check:
            if not self._is_etf_synced_for_date(date, total):
                dates_to_sync.append(date)
            else:
                logger.info(f"[ETF同步] 日期 {date} 已有数据，跳过")

        if not dates_to_sync:
            logger.info(f"[ETF同步] 所有日期数据已存在，跳过")
            return {'total': total, 'success': 0, 'fail': 0, 'skipped': total}

        logger.info(f"[ETF同步] 需要同步 {len(dates_to_sync)} 个日期: {dates_to_sync}")

        success = 0
        fail = 0
        days_synced = 0

        # 逐日同步（与一键更新逻辑一致）
        for date in dates_to_sync:
            days_synced += 1
            logger.info(f"[ETF同步] 同步日期 {date}")

            if progress_callback:
                progress_callback(0, total, f"同步 {date}...")
            elif tm and task_id:
                tm.update_task_progress(task_id, current_stock=date,
                                        current_stock_name=f"同步 {date}...",
                                        total_count=total, completed_count=0)

            day_success = 0
            day_fail = 0

            def _sync_one(etf: dict) -> bool:
                code = etf['code']
                sources = [
                    (self.pytdx, 'PyTdX'),
                    (self.akshare, 'AkShare'),
                ]
                for source_obj, source_name in sources:
                    try:
                        if source_name == 'PyTdX':
                            df_data, src = source_obj.get_daily_data(code, date, date)
                        elif source_name == 'AkShare':
                            df_data, src = source_obj.get_etf_daily(code, date, date)
                        else:
                            df_data, src = source_obj.get_daily_data(code, date, date)
                        if df_data is not None and not df_data.empty:
                            records = df_data.to_dict('records')
                            records = self._forward_adjust_records(records)
                            bulk_upsert_daily_data(code, records, src, 'etf')
                            return True
                    except Exception as e:
                        logger.warning(f"ETF {code} {source_name} 同步失败: {e}")
                return False

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_sync_one, etf): etf for etf in etf_list}
                for future in as_completed(futures):
                    if future.result():
                        day_success += 1
                    else:
                        day_fail += 1

                    done = day_success + day_fail
                    if done % 50 == 0 or done == total:
                        if progress_callback:
                            progress_callback(done, total, f"同步 {date}")
                        elif tm and task_id:
                            tm.update_task_progress(task_id, current_stock=date,
                                                    current_stock_name=f"同步 {date}",
                                                    total_count=total, completed_count=done)

            success += day_success
            fail += day_fail
            logger.info(f"[ETF同步] {date} 完成: 成功{day_success} 失败{day_fail}")

            # 检查失败率，超过50%则停止（ETF数量少，阈值放宽）
            if total > 0 and day_fail / total > 0.5:
                logger.error(f"[ETF同步] {date} 失败率 {day_fail/total:.1%} 超过阈值，停止执行")
                break

        logger.info(f"ETF日线同步完成: {days_synced}天, 成功{success}, 失败{fail}")

        # RPS 计算由调用方（_run_etf_sync Step2）负责，此处不重复计算

        return {'total': total, 'success': success, 'fail': fail, 'skipped': total * days_synced - success}

    def _is_etf_synced_for_date(self, target_date: str, expected_count: int = 0) -> bool:
        """
        检查指定日期的ETF数据是否已同步（与一键更新 _is_data_synced_for_date 逻辑一致）
        盘中（15:30前）：30分钟缓存，需要重新同步
        盘后（15:30后）：is_final=True 才跳过
        """
        from .db import get_db
        db = get_db()
        now = datetime.now(BJ_TZ)
        today_str = now.strftime('%Y%m%d')

        # 非今天的数据，检查 is_final=True
        if target_date != today_str:
            count = db['etf_daily'].count_documents({'trade_date': target_date, 'is_final': True})
            if expected_count > 0:
                return count >= expected_count
            return count > 0

        # 今天的数据
        is_market_closed = now.hour > 15 or (now.hour == 15 and now.minute >= 30)

        if is_market_closed:
            # 盘后：检查 is_final=True
            count = db['etf_daily'].count_documents({'trade_date': target_date, 'is_final': True})
            if expected_count > 0:
                return count >= expected_count
            return count > 0
        else:
            # 盘中：30分钟缓存，检查最后更新时间
            latest = db['etf_daily'].find_one(
                {'trade_date': target_date},
                sort=[('updated_at', -1)],
                projection={'updated_at': 1, '_id': 0}
            )
            if not latest:
                return False

            updated_at = latest.get('updated_at')
            if not updated_at:
                return False

            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))

            if (now - updated_at) > timedelta(minutes=30):
                return False

            if expected_count > 0:
                count = db['etf_daily'].count_documents({'trade_date': target_date})
                if count < expected_count:
                    return False

            return True

    def _get_xdxr_fingerprint(self, stock_code: str) -> Optional[str]:
        """获取个股当前 xdxr 除权事件指纹（带日内缓存）

        约定：None=拉取失败/无事件（与 db 中 None 语义一致），
        实际指纹字符串=有事件。缓存按日期隔离，当日重复调用零开销。
        """
        today = self._today_str()
        cache = _XDXR_FINGERPRINT_CACHE.setdefault(today, {})
        if stock_code in cache:
            return cache[stock_code]

        fp = None
        try:
            xdxr = PyTdXSource._fetch_xdxr_events(
                MARKET_SH if stock_code.startswith(('5', '6', '8', '9')) else MARKET_SZ,
                stock_code
            )
            fp = PyTdXSource.xdxr_fingerprint(xdxr) if xdxr else ''
        except Exception as e:
            logger.warning(f"获取 {stock_code} xdxr 指纹失败: {e}")
            fp = None

        cache[stock_code] = fp
        return fp

    def _full_reload_stock(self, stock_code: str, end_date: str) -> bool:
        """除权基准变化后全量重拉该股历史并覆盖写入

        前复权基准基于最新 xdxr 事件，新除权会令全部历史价格等比缩放。
        个股同步默认增量（只写目标日），历史 is_final 记录不会随新除权
        重算，导致除权日前后价格断裂。此处拉全量历史覆盖，修复漂移。

        :return: 是否重拉成功
        """
        # 全量窗口：回溯到足够深的历史（上限10年由 _find_sync_boundary 界定，
        # 这里从今天往前推10年，与逐日回溯覆盖范围对齐）
        start_date = (datetime.now(BJ_TZ) - timedelta(days=3650)).strftime('%Y%m%d')
        try:
            df, source = self.pytdx.get_daily_data(stock_code, start_date, end_date)
        except Exception as e:
            logger.warning(f"{stock_code} 全量重拉数据源异常: {e}")
            return False
        if df is None or (hasattr(df, 'empty') and df.empty):
            logger.warning(f"{stock_code} 全量重拉无数据，跳过")
            return False

        records = df.to_dict('records')
        bulk_upsert_daily_data(stock_code, records, source or 'pytdx')
        logger.info(f"{stock_code} 除权基准变化，全量重拉 {len(records)} 条 ({start_date}~{end_date})")
        return True

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

        # 一次查询：获取该股票最新交易日数据（含 is_final）
        # 同时用于：数据存在检查 + 停牌判断
        latest = stock_coll.find_one(
            {'stock_code': stock_code, 'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, 'is_final': 1, '_id': 0}
        )
        if latest:
            latest_date = latest['trade_date']

            # 最新数据 >= 目标日期 → 已有数据，跳过
            if latest_date >= end_date:
                t = self._time_minutes()
                if t >= AFTER_MARKET_START:
                    if latest.get('is_final'):
                        result['status'] = 'skipped'
                        return result
                else:
                    result['status'] = 'skipped'
                    return result

            # 最新数据远早于目标日期 → 停牌跳过
            if latest_date < end_date:
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
# 使用 daemon 线程 + join(timeout) 实现超时，避免 ThreadPoolExecutor
# shutdown(wait=True) 在超时后仍阻塞等待后台线程的问题。
# 并通过全局信号量限制并发请求数，防止线程无限累积导致系统资源耗尽。
        import threading

        # yfinance 对 A 股支持极差（DNS 无法解析），且底层无超时，
        # 是线程残留的最大来源，已从瀑布中移除。
        # BaoStock 因 IP 被服务端列入黑名单（登录返回"黑名单用户"），
        # 已从瀑布移除，避免每次同步空耗登录失败。
        sources = [
            (self.pytdx, 'PyTdX'),
            (self.akshare, 'AkShare'),
        ]
        failure_reasons = []

        # 当日无数据记忆化（date -> set[stock_code]）
        # 停牌/退市/未上市股票在目标日无数据，源返回空 DataFrame 而非故障。
        # 首次确认后本轮同步直接跳过，避免对每只无数据股票反复拉取。
        # 模块级缓存，进程生命周期内有效，按日期隔离。
        no_data_cache = _NO_DATA_CACHE.setdefault(end_date, set())
        if stock_code in no_data_cache:
            result['status'] = 'skipped'
            result['error'] = f'{end_date} 无数据（已确认）'
            return result

        breaker = _SOURCE_BREAKER

        for source_obj, source_name in sources:
            if breaker.is_open(source_name):
                failure_reasons.append(f"{source_name}: 熔断中")
                continue

            holder = []

            def _run_source(_source=source_obj, _holder=holder):
                try:
                    _holder.append(_source.get_daily_data(stock_code, start_date, end_date))
                except Exception as e:
                    _holder.append((None, f"{source_name}异常: {e}"))

            with _SOURCE_SEMAPHORE:
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(_SOCKET_TIMEOUT)
                try:
                    t = threading.Thread(target=_run_source, daemon=True)
                    t.start()
                    t.join(timeout=30)
                finally:
                    socket.setdefaulttimeout(old_timeout)

            if t.is_alive():
                failure_reasons.append(f"{source_name}: 超时 30s")
                breaker.record_failure(source_name)
                continue

            if not holder:
                failure_reasons.append(f"{source_name}: 未返回数据")
                breaker.record_failure(source_name)
                continue

            df, source = holder[0]
            if df is not None and not df.empty:
                # 复权基准漂移检测：仅对 PyTdX 源执行（有 xdxr 事件）
                # 除权事件变化 → 全量重拉覆盖历史，修复前复权断裂
                if source_name == 'PyTdX':
                    stored_fp = get_xdxr_fingerprint(stock_code)
                    current_fp = self._get_xdxr_fingerprint(stock_code)
                    # current_fp 为 None 表示本次拉取失败，不触发重拉
                    if current_fp is not None and self._should_full_reload(stored_fp, current_fp):
                        reloaded = self._full_reload_stock(stock_code, end_date)
                        if reloaded:
                            set_xdxr_fingerprint(stock_code, current_fp)
                            result['status'] = 'success'
                            result['source'] = source
                            result['reloaded'] = True
                            breaker.record_success(source_name)
                            return result
                        logger.warning(f"{stock_code} 全量重拉失败，回退增量写入")

                records = df.to_dict('records')
                bulk_upsert_daily_data(stock_code, records, source)
                # 同步成功即记录指纹（首次记录或确认无变化）
                if source_name == 'PyTdX':
                    current_fp = self._get_xdxr_fingerprint(stock_code)
                    set_xdxr_fingerprint(stock_code, current_fp)
                result['status'] = 'success'
                result['source'] = source
                breaker.record_success(source_name)
                return result
            # df 为空 → 该股无数据（停牌/退市/未上市），不是数据源故障
            # 不记录失败，避免无数据股票连续出现导致数据源被误熔断
            failure_reasons.append(f"{source_name}: 无数据")
            no_data_cache.add(stock_code)
            result['status'] = 'skipped'
            result['error'] = f'{end_date} 无数据'
            return result

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
                if t >= AFTER_MARKET_START or day < today:
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
                    # 通达信概念板块：先用pytdx获取
                    try:
                        kline = self.pytdx.get_tdx_index_daily(
                            tdx_code, market=1, start_date=prev_day, end_date=day, max_bars=5
                        )
                    except Exception as e:
                        logger.warning(f"pytdx获取通达信板块 {sector_code} 失败: {e}")

                    # pytdx失败时回退到东方财富概念板块（用akshare通过板块名称获取）
                    if kline is None or len(kline) == 0:
                        sector_name = sec.get('name', '')
                        if sector_name:
                            try:
                                kline = self.akshare.get_concept_hist(sector_name, prev_day, day)
                            except Exception as e:
                                logger.warning(f"akshare回退获取概念板块 {sector_name}({sector_code}) 失败: {e}")

                if kline is not None and len(kline) > 0:
                    new_records = []
                    for _, r in kline.iterrows():
                        if str(r['trade_date']) == day:
                            record = {
                                'trade_date': day,
                                'close': float(r['close']),
                                'open': float(r.get('open', 0)),
                                'high': float(r.get('high', 0)),
                                'low': float(r.get('low', 0)),
                                'amount': float(r.get('amount', 0)),
                            }
                            # akshare返回volume单位是"手"，转为"股"与pytdx一致
                            vol = float(r.get('volume', 0) or 0)
                            if vol > 0:
                                record['vol'] = vol * 100
                            new_records.append(record)
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

        # 盘后强制重刷前一个交易日，修正盘中同步的暂态值
        if self._time_minutes() >= AFTER_MARKET_START:
            prev_day = (datetime.strptime(today, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
            prev_count = _count_final_records('sector', prev_day)
            if prev_count > 0:
                logger.info(f"盘后重刷前一个交易日 {prev_day}，覆盖盘中暂态值...")
                sector_coll.update_many(
                    {'trade_date': prev_day, 'is_final': True},
                    {'$set': {'is_final': False}}
                )
                sync_day(prev_day)

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
            target: 'all' - 全部, 'stock' - 仅个股, 'sector' - 仅板块, 'etf' - 仅ETF
            max_dates: 仅计算最近 N 天（None 则计算所有历史）
        """
        from app.engine.factor_engine import FactorEngine
        engine = FactorEngine()
        result = {}
        if target in ('all', 'stock'):
            result['stock'] = engine.calculate_rps(data_type='stock', max_dates=max_dates)
        if target in ('all', 'sector'):
            result['sector'] = engine.calculate_rps(data_type='sector', max_dates=max_dates)
        if target in ('all', 'etf'):
            result['etf'] = engine.calculate_rps(data_type='etf', max_dates=max_dates)
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

    def get_etf_list(self) -> pd.DataFrame:
        """获取ETF列表"""
        return get_etf_basics()

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
