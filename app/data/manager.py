"""
新的 DataManager，使用 MongoDB + 多数据源 + 多线程
"""
import pandas as pd
import threading
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
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
from .sources.tqcenter_source import TqCenterSource


class DataManager:
    def __init__(self):
        # 初始化数据源（按优先级：TqCenter > PyTdX > AkShare > BaoStock > yfinance）
        self.tqcenter = TqCenterSource()
        self.pytdx = PyTdXSource()
        self.akshare = AkShareSource()
        self.baostock = BaoStockSource()
        self.yfinance = YFinanceSource()

    def sync_stock_basics(self) -> int:
        """同步股票基础信息，返回成功数量"""
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
                'suspend': False
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
        """同步单只股票数据的内部方法（不更新任务，只做数据同步）"""
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

        # 检查是否停牌
        from app.data.db import get_collection
        stock_coll = get_collection('stock')
        latest_doc = stock_coll.find_one(
            {'stock_code': stock_code, 'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, 'is_final': 1, '_id': 0}
        )
        if latest_doc:
            latest_date = latest_doc.get('trade_date', '')
            is_final = latest_doc.get('is_final', False)
            # 如果最新数据日期早于请求的结束日期，可能是停牌
            if latest_date and latest_date < end_date:
                # 检查是否有更近的数据（排除非最终数据）
                recent_doc = stock_coll.find_one(
                    {'stock_code': stock_code, 'trade_date': {'$gte': end_date}, 'close': {'$gt': 0}},
                    projection={'trade_date': 1, '_id': 0}
                )
                if not recent_doc:
                    # 用交易日（排除节假日）判断停牌天数
                    from datetime import datetime as _dt
                    from app.data.holidays import filter_workdays
                    try:
                        workdays = filter_workdays(latest_date, end_date)
                        suspend_days = len(workdays) - 1  # 不含起始日
                        if suspend_days >= 3:
                            result['status'] = 'skipped'
                            result['error'] = f'停牌中（最后交易日{latest_date}，已停牌{suspend_days}个交易日）'
                            return result
                    except:
                        pass

        # 用于记录各个数据源的失败原因
        failure_reasons = []

        try:
            df = None
            source = ''
            
            # 按优先级尝试获取数据：PyTdX > AkShare > BaoStock > yfinance
            try:
                df, source = self.pytdx.get_daily_data(stock_code, start_date, end_date)
                if df is None or df.empty:
                    failure_reasons.append("PyTdX: 未返回数据")
            except Exception as e:
                failure_reasons.append(f"PyTdX: {str(e)}")
            
            if df is None or df.empty:
                try:
                    df, source = self.akshare.get_daily_data(stock_code, start_date, end_date)
                    if df is None or df.empty:
                        failure_reasons.append("AkShare: 未返回数据")
                except Exception as e:
                    failure_reasons.append(f"AkShare: {str(e)}")
            
            if df is None or df.empty:
                try:
                    df, source = self.baostock.get_daily_data(stock_code, start_date, end_date)
                    if df is None or df.empty:
                        failure_reasons.append("BaoStock: 未返回数据")
                except Exception as e:
                    failure_reasons.append(f"BaoStock: {str(e)}")
            
            if df is None or df.empty:
                try:
                    df, source = self.yfinance.get_daily_data(stock_code, start_date, end_date)
                    if df is None or df.empty:
                        failure_reasons.append("yfinance: 未返回数据")
                except Exception as e:
                    failure_reasons.append(f"yfinance: {str(e)}")
            
            if df is None or df.empty:
                result['status'] = 'failed'
                if failure_reasons:
                    result['error'] = " | ".join(failure_reasons)
                else:
                    result['error'] = '获取数据失败'
                return result
            
            # 保存到 MongoDB
            records = df.to_dict('records')
            bulk_upsert_daily_data(stock_code, records, source)
            
            result['status'] = 'success'
            result['source'] = source
            
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
        
        return result

    def sync_daily_data(self, stock_codes: List[str], start_date: str, end_date: str, 
                        task_id: Optional[str] = None, max_workers: int = 16) -> dict:
        """同步日线数据（多线程版本），返回统计结果"""
        from .task_manager import get_task_manager
        from .holidays import filter_workdays
        import time
        from threading import Lock

        # 过滤：只保留交易日（排除周末+法定节假日）
        workdays = filter_workdays(start_date, end_date)
        if not workdays:
            print(f"日期范围 {start_date}~{end_date} 内无交易日，跳过同步")
            return {'total': len(stock_codes), 'success': 0, 'fail': 0, 'skipped': len(stock_codes), 'sources': {}}
        start_date = workdays[0]
        end_date = workdays[-1]
        print(f"交易日过滤: {start_date} ~ {end_date} ({len(workdays)} 天)")
        
        success_count = 0
        fail_count = 0
        skipped_count = 0
        data_sources_used = {}
        failed_stocks_list = []
        
        # 获取任务管理器并更新状态为 running
        tm = get_task_manager() if task_id else None
        if tm and task_id:
            tm.update_task_progress(
                task_id,
                current_stock="0",
                current_stock_name=f"正在检查 {len(stock_codes)} 只股票数据...",
                total_count=len(stock_codes),
                completed_count=0
            )
        
        # 获取股票基础信息用于显示名称
        stock_df = self.get_stock_list()
        stock_name_map = {}
        if not stock_df.empty:
            stock_name_map = dict(zip(stock_df['stock_code'], stock_df['stock_name']))
        
        # 🔴 第一步：批量获取每只股票的同步起始日期
        if tm and task_id:
            tm.update_task_progress(
                task_id,
                current_stock_name="正在批量检查已有数据..."
            )
        print(f"正在批量检查 {len(stock_codes)} 只股票的同步起始日期...")
        stock_start_dates = {}
        try:
            from .db import get_stock_sync_start_date
            for code in stock_codes:
                stock_start_dates[code] = get_stock_sync_start_date(code)
            print(f"检查完成：{len(stock_codes)} 只股票")
        except Exception as e:
            print(f"批量检查失败，将使用默认起始日期: {e}")

        # 使用线程池进行并行同步
        print(f"开始使用 {max_workers} 个线程同步 {len(stock_codes)} 只股票数据...")
        if tm and task_id:
            tm.update_task_progress(
                task_id,
                current_stock_name=f"开始同步 {len(stock_codes)} 只股票..."
            )
        
        # 用于跟踪进度
        processed_count = 0
        last_update_time = 0
        progress_lock = Lock()
        
        def process_result(result, tm):
            nonlocal success_count, fail_count, skipped_count
            nonlocal processed_count
            
            if result['status'] == 'success':
                success_count += 1
                if result['source']:
                    data_sources_used[result['source']] = data_sources_used.get(result['source'], 0) + 1
                if tm:
                    tm.update_task_progress(
                        task_id,
                        increment_completed=1,
                        sources={result['source']: 1} if result['source'] else None
                    )
            elif result['status'] == 'failed':
                fail_count += 1
                failed_stocks_list.append({
                    'stock_code': result['stock_code'],
                    'stock_name': result['stock_name'],
                    'error': result['error']
                })
                if tm:
                    tm.update_task_progress(
                        task_id, 
                        increment_failed=1,
                        failed_stock={
                            'stock_code': result['stock_code'],
                            'stock_name': result['stock_name'],
                            'error': result['error']
                        }
                    )
            elif result['status'] == 'skipped':
                skipped_count += 1
                if tm:
                    tm.update_task_progress(
                        task_id, increment_skipped=1
                    )
            
            processed_count += 1
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务，用字典记录股票信息
            future_map = {}
            for stock_code in stock_codes:
                stock_name = stock_name_map.get(stock_code, stock_code)
                # 获取该股票的同步起始日期
                stock_start = stock_start_dates.get(stock_code)
                # 如果没有数据，使用请求的 start_date
                if not stock_start:
                    stock_start = start_date
                # 如果起始日期 > end_date，跳过该股票
                if stock_start and stock_start > end_date:
                    skipped_count += 1
                    processed_count += 1
                    if tm:
                        tm.update_task_progress(task_id, increment_skipped=1)
                    continue
                future = executor.submit(
                    self._sync_single_stock,
                    stock_code,
                    stock_name,
                    stock_start,
                    end_date,
                )
                future_map[future] = (stock_code, stock_name)
            
            # 使用 as_completed 快速处理完成的任务
            for future in as_completed(future_map):
                # 检查任务是否被取消
                if tm and tm.is_cancelled(task_id):
                    logger.info(f"任务 {task_id} 已取消，停止提交新任务")
                    # 取消所有尚未开始的 future
                    for f in future_map:
                        f.cancel()
                    break

                try:
                    stock_code, stock_name = future_map[future]
                    result = future.result()
                    result['stock_code'] = stock_code
                    result['stock_name'] = stock_name
                    
                    # 在主循环中顺序处理结果，无需 lock
                    process_result(result, tm)

                    # 每隔一定时间更新一下当前处理股票
                    current_time = time.time()
                    if tm and (current_time - last_update_time > 0.5):
                        tm.update_task_progress(
                            task_id,
                            current_stock=stock_code,
                            current_stock_name=stock_name
                        )
                        last_update_time = current_time
                
                except Exception as e:
                    print(f"任务执行异常: {e}")
                    fail_count += 1
        
        print(f"同步完成: 成功 {success_count}, 跳过 {skipped_count}, 失败 {fail_count}")
        
        return {
            'total': len(stock_codes),
            'success': success_count,
            'fail': fail_count,
            'skipped': skipped_count,
            'sources': data_sources_used
        }

    # ==================== 板块同步 ====================

    def sync_sector_indices(self, start_date=None, end_date=None, progress_callback=None, excluded_codes=None) -> dict:
        """
        同步板块指数日线数据（仅同步 sector_basics 中已有的板块）
        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 截止日期 YYYYMMDD
            progress_callback: 可选回调 fn(current_idx, total_count, sector_name)
            excluded_codes: 排除的板块代码集合
        返回: {block_count, sector_daily_count}
        """
        from .db import get_db
        from pymongo import UpdateOne
        from datetime import datetime as _dt, timedelta
        from .holidays import filter_workdays

        # 过滤：只保留交易日
        if start_date and end_date:
            workdays = filter_workdays(start_date, end_date)
            if not workdays:
                print(f"日期范围 {start_date}~{end_date} 内无交易日，跳过板块同步")
                return {'block_count': 0, 'sector_daily_count': 0}
            start_date = workdays[0]
            end_date = workdays[-1]

        db = get_db()
        update_time = datetime.utcnow()

        # ========== 第一阶段：从 sector_basics 读取已启用的板块列表 ==========
        if progress_callback:
            progress_callback(0, 0, "读取板块列表...")

        # 只读取 sector_basics 中已有的板块（有880/881代码的）
        existing_sectors = list(db['sector_basics'].find(
            {'code': {'$regex': '^88[01]'}},
            {'_id': 0, 'code': 1, 'name': 1, 'tdx_code': 1}
        ))

        if not existing_sectors:
            return {'block_count': 0, 'sector_daily_count': 0, 'error': '没有可同步的板块'}

        # 排除指定板块
        if excluded_codes:
            before_count = len(existing_sectors)
            existing_sectors = [s for s in existing_sectors if s['code'] not in excluded_codes]
            print(f"排除 {before_count - len(existing_sectors)} 个板块（用户配置）")

        total_sectors = len(existing_sectors)
        print(f"✓ 板块列表: 共 {total_sectors} 个")

        # ========== 第二阶段：增量下载板块指数日线 ==========
        if progress_callback:
            progress_callback(0, total_sectors, "准备下载板块日线...")

        # 查询已有最新日期（增量）
        from .db import get_collection
        sector_coll = get_collection('sector')
        all_sector_codes = [s['code'] for s in existing_sectors]
        sector_latest_dates = {}
        try:
            cursor = sector_coll.aggregate([
                {'$match': {'stock_code': {'$in': all_sector_codes}}},
                {'$group': {'_id': '$stock_code',
                            'latest_date': {'$max': '$trade_date'}}}
            ])
            for item in cursor:
                sector_latest_dates[item['_id']] = item['latest_date']
            print(f"✓ 已检查 {len(sector_latest_dates)} 个板块的已有数据")
        except Exception as e:
            print(f"批量查询板块最新日期失败: {e}")

        import time as tm
        from datetime import date as date_cls

        # 计算需要同步的板块数量，全部已最新则跳过 TDX 连接
        if not start_date:
            today = date_cls.today()
            needs_sync = 0
            for sec in existing_sectors:
                latest = sector_latest_dates.get(sec['code'])
                if not latest:
                    needs_sync += 1
                    continue
                try:
                    latest_dt = datetime.strptime(str(latest), '%Y%m%d')
                    if (today - latest_dt.date()).days > 3:
                        needs_sync += 1
                except Exception:
                    needs_sync += 1
            if needs_sync == 0:
                print(f"✓ 全部 {total_sectors} 个板块数据已是最新，无需同步")
                return {'block_count': total_sectors, 'sector_daily_count': 0}
            print(f"  需同步: {needs_sync}/{total_sectors} 个板块")
        elif start_date and end_date:
            # 指定日期范围时，跳过已有数据的板块
            needs_sync = 0
            for sec in existing_sectors:
                latest = sector_latest_dates.get(sec['code'])
                if not latest or latest < start_date:
                    needs_sync += 1
                elif latest < end_date:
                    needs_sync += 1
            if needs_sync == 0:
                print(f"✓ 全部 {total_sectors} 个板块在 {start_date}~{end_date} 范围内已有数据，无需同步")
                return {'block_count': total_sectors, 'sector_daily_count': 0}
            print(f"  需同步: {needs_sync}/{total_sectors} 个板块")

        print(f"  通达信 pytdx 获取板块指数日线 ({total_sectors}个)")
        tdx_fetched = 0
        tdx_failed = 0

        # 连接通达信服务器
        py_api = __import__('pytdx.hq', fromlist=['TdxHq_API']).TdxHq_API
        tdx_hosts = [('180.153.18.170', 7709),
                     ('119.147.212.81', 7709),
                     ('60.12.136.250', 7709)]
        tdx_conn = None
        for host, port in tdx_hosts:
            try:
                api = py_api()
                if api.connect(host, port, time_out=5):
                    tdx_conn = api
                    print(f"  ✓ 已连接通达信服务器 {host}")
                    break
            except Exception:
                continue

        if not tdx_conn:
            return {'block_count': 0, 'sector_daily_count': 0, 'error': '无法连接通达信服务器'}

        try:
            skipped = 0
            written_total = 0
            for idx, sec in enumerate(existing_sectors):
                sector_code = sec['code']
                tdx_code = sec.get('tdx_code', sector_code)
                sector_name = sec['name']

                # 增量：根据最新数据状态决定同步起始日期
                from .db import get_sector_sync_start_date
                calc_start_date = get_sector_sync_start_date(sector_code)
                is_incremental = False

                if start_date:
                    # 指定了起始日期，检查是否已有数据
                    latest = sector_latest_dates.get(sector_code)
                    if latest and str(latest) >= str(end_date):
                        skipped += 1
                        if progress_callback:
                            progress_callback(idx + 1, total_sectors, f"跳过 {sector_name}(已最新)")
                        continue
                    start_date_str = start_date
                else:
                    start_date_str = calc_start_date or (_dt.now() - timedelta(days=365)).strftime('%Y%m%d')

                if calc_start_date and not start_date:
                    if calc_start_date > end_date:
                        skipped += 1
                        continue
                    start_date_str = calc_start_date
                    is_incremental = True

                if progress_callback:
                    progress_callback(idx + 1, total_sectors, f"[通达信] {sector_name}")

                # 增量更新只获取最近200条K线，全量获取2000条
                max_bars = 200 if is_incremental else 2000
                kline = self.pytdx.get_tdx_index_daily(tdx_code, market=1,
                                                        start_date=start_date_str,
                                                        end_date=end_date,
                                                        max_bars=max_bars)
                if kline is not None and len(kline) > 0:
                    # 过滤掉已存在的日期，只保留新增数据
                    new_dates = set(str(r['trade_date']) for _, r in kline.iterrows())
                    if is_incremental:
                        # 增量同步时，查询已有日期并排除
                        existing_dates = set(d['trade_date'] for d in sector_coll.find(
                            {'stock_code': sector_code,
                             'trade_date': {'$gte': start_date_str}},
                            {'_id': 0, 'trade_date': 1}
                        ))
                        new_dates -= existing_dates

                    # 转成records走统一写入（自动算MA/VOL_MA/涨幅）
                    new_records = []
                    for _, r in kline.iterrows():
                        td = str(r['trade_date'])
                        if td in new_dates:
                            new_records.append({
                                'trade_date': td,
                                'close': float(r['close']),
                                'open': float(r.get('open', 0)),
                                'high': float(r.get('high', 0)),
                                'low': float(r.get('low', 0)),
                                'volume': float(r.get('volume', 0)),
                                'amount': float(r.get('amount', 0)),
                            })
                    if new_records:
                        from app.data.db import bulk_upsert_daily_data
                        bulk_upsert_daily_data(sector_code, new_records, 'tdx_880', 'sector')
                        written_total += len(new_records)
                    tdx_fetched += 1
                else:
                    tdx_failed += 1

                if (idx + 1) % 50 == 0:
                    tm.sleep(0.1)

        finally:
            try:
                tdx_conn.disconnect()
            except Exception:
                pass

        print(f"✓ 板块同步完成: 跳过 {skipped} 个(已最新), 获取 {tdx_fetched} 个, 失败 {tdx_failed} 个, 写入 {written_total} 条")
        return {'block_count': total_sectors, 'sector_daily_count': written_total}

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
            from datetime import datetime as _dt, timedelta
            try:
                max_date = max(dates)
                min_date = (_dt.strptime(max_date, '%Y%m%d') - timedelta(days=300)).strftime('%Y%m%d')
            except:
                min_date = dates[0]

            cursor = coll.find(
                {'trade_date': {'$gte': min_date}, 'close': {'$gt': 0}},
                {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
            )
            import pandas as pd
            df = pd.DataFrame(list(cursor))
            if df.empty:
                result[data_type] = 0
                continue

            df = df.sort_values(['stock_code', 'trade_date']).reset_index(drop=True)
            g = df.groupby('stock_code')

            # 向量化计算
            df['_prev'] = g['close'].shift(1)
            df['chg_pct'] = ((df['close'] - df['_prev']) / df['_prev'] * 100).round(2)
            for p in [5, 10, 20, 50, 120, 250]:
                df[f'chg_{p}d'] = g['close'].transform(lambda x: ((x / x.shift(p)) - 1) * 100).round(2)

            # 只写入目标日期的数据
            target_df = df[df['trade_date'].isin(dates)]
            fields = ['chg_pct'] + [f'chg_{p}d' for p in [5, 10, 20, 50, 120, 250]]

            update_time = __import__('datetime').datetime.utcnow()
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
            print(f"[chg-{data_type}] {dates} {len(ops)} 条, {elapsed:.0f}秒")
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
