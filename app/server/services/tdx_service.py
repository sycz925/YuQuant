"""
TDX Service - 通达信数据同步服务
处理 TDX API 数据同步逻辑
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# TDX 服务器列表
TDX_SERVERS = [
    ('180.153.18.170', 7709),
    ('180.153.18.171', 7709),
    ('60.12.136.250', 7709),
]


class TdxService:
    """通达信数据同步服务"""
    
    def sync_indices(self, task_id: str, sync_cfg: List[Dict],
                     start_date: str, end_date: str, is_external: bool = False):
        """
        同步指数 K 线数据
        :param task_id: 任务ID
        :param sync_cfg: 同步配置列表
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param is_external: 是否为外部任务
        """
        try:
            from pytdx.hq import TdxHq_API
            from pytdx.params import TDXParams
            from pymongo import UpdateOne
            from app.data.db import get_db
            from app.data.task_manager import get_task_manager

            db = get_db()
            tm = get_task_manager()
            success_count = 0
            fail_count = 0
            total = len(sync_cfg)

            tm.update_task_progress(task_id, current_stock="0", current_stock_name="开始同步指数...")

            for i, idx_config in enumerate(sync_cfg):
                if tm.is_cancelled(task_id):
                    logger.info(f"任务 {task_id} 已取消，停止指数同步")
                    return
                try:
                    tm.update_task_progress(
                        task_id, current_stock=str(i),
                        current_stock_name=f"正在同步 {idx_config['name']}...",
                        total_count=total, completed_count=i,
                    )
                    logger.info(f"正在同步 {idx_config['name']}...")

                    records_saved = False
                    for server in TDX_SERVERS:
                        try:
                            api = TdxHq_API()
                            if api.connect(*server):
                                all_data = []
                                offset = 0
                                max_retries = 3
                                retry_count = 0
                                max_iterations = 50

                                for _ in range(max_iterations):
                                    remaining_days = (datetime.strptime(end_date, '%Y%m%d') - datetime.strptime(start_date, '%Y%m%d')).days + 1
                                    fetch_count = min(800, remaining_days + 10)
                                    
                                    data = api.get_index_bars(
                                        category=TDXParams.KLINE_TYPE_DAILY,
                                        market=idx_config['market'],
                                        code=idx_config['tdx_code'],
                                        start=offset, count=fetch_count,
                                    )
                                    if not data or len(data) == 0:
                                        break
                                    valid_data = []
                                    abnormal_count = 0
                                    for item in data:
                                        try:
                                            year = item.get('year', 0)
                                            vol = item.get('vol', 0)
                                            amount = item.get('amount', 0)
                                            if year > 2050 or vol > 1e15 or amount > 1e20:
                                                abnormal_count += 1
                                                continue
                                            if 2000 <= year <= 2050:
                                                valid_data.append(item)
                                        except Exception:
                                            continue
                                    if len(data) > 0 and (abnormal_count / len(data)) > 0.5:
                                        api.disconnect()
                                        import time
                                        time.sleep(1)
                                        if retry_count < max_retries:
                                            retry_count += 1
                                            continue
                                        else:
                                            break
                                    all_data.extend(valid_data)
                                    if len(data) < 800:
                                        break
                                    offset += 800

                                api.disconnect()

                                if all_data and len(all_data) > 0:
                                    records = []
                                    for item in all_data:
                                        try:
                                            if 'year' in item and 'month' in item and 'day' in item:
                                                trade_date = f"{item['year']:04d}{item['month']:02d}{item['day']:02d}"
                                            elif 'datetime' in item:
                                                dt_str = str(item['datetime'])
                                                if ' ' in dt_str:
                                                    dt_str = dt_str.split(' ')[0]
                                                trade_date = dt_str.replace('-', '')
                                            elif 'date' in item:
                                                trade_date = str(item['date']).replace('-', '')
                                            else:
                                                continue
                                            if len(trade_date) != 8:
                                                continue
                                            if not (start_date <= trade_date <= end_date):
                                                continue
                                            open_val = float(item.get('open', 0))
                                            high_val = float(item.get('high', 0))
                                            low_val = float(item.get('low', 0))
                                            close_val = float(item.get('close', 0))
                                            if (open_val <= 0 or open_val > 100000 or
                                                high_val <= 0 or high_val > 100000 or
                                                low_val <= 0 or low_val > 100000 or
                                                close_val <= 0 or close_val > 100000):
                                                continue
                                            records.append({
                                                'stock_code': idx_config['code'],
                                                'trade_date': trade_date,
                                                'open': open_val, 'high': high_val,
                                                'low': low_val, 'close': close_val,
                                                'volume': float(item.get('vol', item.get('volume', 0))),
                                                'amount': float(item.get('amount', 0)),
                                            })
                                        except Exception:
                                            continue

                                    if records:
                                        ops = []
                                        for rec in records:
                                            doc = dict(rec)
                                            doc['data_type'] = 'index'
                                            doc['data_source'] = 'pytdx'
                                            doc['update_time'] = datetime.utcnow()
                                            ops.append(UpdateOne(
                                                {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
                                                {'$set': doc}, upsert=True,
                                            ))
                                        db.index_daily.bulk_write(ops, ordered=False)
                                        success_count += 1
                                        logger.info(f"成功同步 {idx_config['name']} {len(records)} 条数据")
                                        records_saved = True
                                        break
                        except Exception as e:
                            logger.warning(f"服务器 {server} 获取 {idx_config['name']} 失败: {e}")
                            continue

                    if not records_saved:
                        fail_count += 1
                        logger.error(f"所有服务器获取 {idx_config['name']} 都失败")
                except Exception as e:
                    logger.error(f"同步 {idx_config['name']} 失败: {e}")
                    fail_count += 1

            # 同步完成后，计算所有指数的涨跌幅
            try:
                logger.info("[指数同步] 开始计算涨跌幅...")
                enabled_codes = list(db['index_basics'].find(
                    {'is_disable': {'$ne': True}},
                    {'_id': 0, 'code': 1}
                ))
                from pymongo import UpdateOne as Upd
                bulk_ops = []
                for idx_doc in enabled_codes:
                    code = idx_doc['code']
                    cursor = db['index_daily'].find(
                        {'stock_code': code},
                        {'_id': 0, 'trade_date': 1, 'close': 1}
                    ).sort('trade_date', 1)
                    docs = list(cursor)
                    for i, doc in enumerate(docs):
                        if i == 0:
                            chg_pct = 0
                        else:
                            prev_close = docs[i-1].get('close', 0)
                            curr_close = doc.get('close', 0)
                            if prev_close > 0 and curr_close > 0:
                                chg_pct = round((curr_close / prev_close - 1) * 100, 2)
                            else:
                                chg_pct = 0
                        bulk_ops.append(Upd(
                            {'stock_code': code, 'trade_date': doc['trade_date']},
                            {'$set': {'chg_pct': chg_pct}},
                        ))
                if bulk_ops:
                    db['index_daily'].bulk_write(bulk_ops, ordered=False)
                    logger.info(f"[指数同步] 涨跌幅计算完成，更新 {len(bulk_ops)} 条记录")
            except Exception as e:
                logger.warning(f"[指数同步] 涨跌幅计算失败: {e}")

            msg = f"指数数据同步完成，成功 {success_count} 个，失败 {fail_count} 个"
            logger.info(msg)
            if not is_external:
                tm.complete_task(task_id, msg)
            
            # 刷新缓存
            try:
                from app.server.cache import refresh_trade_dates
                refresh_trade_dates()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"指数同步失败: {e}")
            tm = get_task_manager()
            tm.fail_task(task_id, f"失败: {str(e)}")


# 全局单例
_tdx_service: Optional[TdxService] = None


def get_tdx_service() -> TdxService:
    """获取 TDX 服务单例"""
    global _tdx_service
    if _tdx_service is None:
        _tdx_service = TdxService()
    return _tdx_service
