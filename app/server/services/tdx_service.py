"""
TDX Service - 通达信数据同步服务
职责单一：只同步 TDX 日线数据到数据库
不包含任务管理、进度更新、涨跌幅计算等逻辑
"""
import logging
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# TDX 服务器列表
TDX_SERVERS = [
    ('180.153.18.170', 7709),
    ('180.153.18.171', 7709),
    ('60.12.136.250', 7709),
]


class TdxService:
    """通达信数据同步服务 - 职责单一，只同步 TDX 日线数据"""
    
    def sync_index(self, index_config: Dict, start_date: str, end_date: str) -> Dict:
        """
        同步单个指数的 K 线数据
        :param index_config: 指数配置 {'code': '000001', 'name': '上证指数', 'market': 1, 'tdx_code': '000001'}
        :param start_date: 开始日期 YYYYMMDD
        :param end_date: 结束日期 YYYYMMDD
        :return: {'success': bool, 'records': int, 'message': str}
        """
        from pymongo import UpdateOne
        from app.data.db import get_db
        
        db = get_db()
        records_saved = False
        records_count = 0
        
        for server in TDX_SERVERS:
            try:
                from pytdx.hq import TdxHq_API
                from pytdx.params import TDXParams
                
                api = TdxHq_API()
                if not api.connect(*server):
                    continue
                
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
                        market=index_config['market'],
                        code=index_config['tdx_code'],
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
                                'stock_code': index_config['code'],
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
                        records_count = len(records)
                        records_saved = True
                        logger.info(f"成功同步 {index_config['name']} {records_count} 条数据")
                        break
                
                if records_saved:
                    break
                    
            except Exception as e:
                logger.warning(f"服务器 {server} 获取 {index_config['name']} 失败: {e}")
                continue
        
        if not records_saved:
            # 尝试实时行情获取当天数据
            today_str = datetime.now().strftime('%Y%m%d')
            if end_date >= today_str:
                try:
                    from pytdx.hq import TdxHq_API as TdxRealtime
                    for rt_server in TDX_SERVERS:
                        try:
                            rt_api = TdxRealtime()
                            if rt_server and rt_api.connect(*rt_server):
                                market = index_config.get('market', 1)
                                rt_data = rt_api.get_security_quotes([(market, index_config['tdx_code'])])
                                if rt_data and rt_data[0].get('price', 0) > 0:
                                    d = rt_data[0]
                                    doc = {
                                        'stock_code': index_config['code'],
                                        'trade_date': today_str,
                                        'open': float(d['open']),
                                        'high': float(d['high']),
                                        'low': float(d['low']),
                                        'close': float(d['price']),
                                        'volume': float(d.get('vol', 0)),
                                        'amount': float(d.get('amount', 0)),
                                        'data_type': 'index',
                                        'data_source': 'pytdx_realtime',
                                        'update_time': datetime.utcnow(),
                                    }
                                    db.index_daily.update_one(
                                        {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
                                        {'$set': doc}, upsert=True,
                                    )
                                    records_count = 1
                                    records_saved = True
                                    logger.info(f"[pytdx实时] 成功获取 {index_config['name']} 今日数据")
                                rt_api.disconnect()
                                break
                        except Exception:
                            continue
                except Exception as e:
                    logger.warning(f"[pytdx实时] {index_config['name']} 失败: {e}")
            
            # 尝试 akshare 兜底
            if not records_saved:
                try:
                    import akshare as ak
                    symbol = f"sh{index_config['tdx_code']}" if index_config.get('market', 1) == 1 else f"sz{index_config['tdx_code']}"
                    df = ak.stock_zh_index_daily(symbol=symbol)
                    if df is not None and not df.empty:
                        records = []
                        for _, row in df.iterrows():
                            try:
                                date_str = row['date'].strftime('%Y%m%d') if hasattr(row['date'], 'strftime') else str(row['date']).replace('-', '')
                                if not (start_date <= date_str <= end_date):
                                    continue
                                close_val = float(row['close'])
                                if close_val <= 0 or close_val > 100000:
                                    continue
                                records.append({
                                    'stock_code': index_config['code'],
                                    'trade_date': date_str,
                                    'open': float(row['open']),
                                    'high': float(row['high']),
                                    'low': float(row['low']),
                                    'close': close_val,
                                    'volume': float(row.get('volume', 0)),
                                    'amount': 0,
                                })
                            except Exception:
                                continue
                        if records:
                            ops = []
                            for rec in records:
                                doc = dict(rec)
                                doc['data_type'] = 'index'
                                doc['data_source'] = 'akshare'
                                doc['update_time'] = datetime.utcnow()
                                ops.append(UpdateOne(
                                    {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
                                    {'$set': doc}, upsert=True,
                                ))
                            db.index_daily.bulk_write(ops, ordered=False)
                            records_count = len(records)
                            records_saved = True
                            logger.info(f"[akshare兜底] 成功同步 {index_config['name']} {records_count} 条数据")
                except Exception as e:
                    logger.warning(f"[akshare兜底] {index_config['name']} 失败: {e}")
        
        if records_saved:
            return {'success': True, 'records': records_count, 'message': f'同步完成: {records_count} 条'}
        else:
            return {'success': False, 'records': 0, 'message': f'同步失败: {index_config["name"]}'}


# 全局单例
_tdx_service: Optional[TdxService] = None


def get_tdx_service() -> TdxService:
    """获取 TDX 服务单例"""
    global _tdx_service
    if _tdx_service is None:
        _tdx_service = TdxService()
    return _tdx_service
