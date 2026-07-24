"""
Data Service - 数据同步服务
职责：从多种数据源获取日线数据，支持优先级 fallback
数据源优先级：pytdx → akshare → baostock → yfinance
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

# 数据源优先级
DATA_SOURCE_PRIORITY = ['pytdx', 'akshare', 'baostock', 'yfinance']


class DataService:
    """数据同步服务 - 支持多数据源 fallback"""
    
    def sync_index(self, index_config: Dict, start_date: str, end_date: str) -> Dict:
        """
        同步单个指数的 K 线数据（多数据源 fallback）
        :param index_config: 指数配置
        :param start_date: 开始日期
        :param end_date: 结束日期
        :return: {'success': bool, 'records': int, 'source': str, 'message': str}
        """
        # 尝试 pytdx
        result = self._sync_index_pytdx(index_config, start_date, end_date)
        if result['success']:
            return result
        
        # 尝试 akshare
        result = self._sync_index_akshare(index_config, start_date, end_date)
        if result['success']:
            return result
        
        # 尝试 baostock
        result = self._sync_index_baostock(index_config, start_date, end_date)
        if result['success']:
            return result
        
        return {'success': False, 'records': 0, 'source': 'none', 'message': f'所有数据源同步失败: {index_config["name"]}'}
    
    def _sync_index_pytdx(self, index_config: Dict, start_date: str, end_date: str) -> Dict:
        """使用 pytdx 同步指数数据"""
        try:
            from pytdx.hq import TdxHq_API
            from pytdx.params import TDXParams
            from pymongo import UpdateOne
            from app.data.db import get_db
            
            db = get_db()
            
            for server in TDX_SERVERS:
                try:
                    api = TdxHq_API()
                    if not api.connect(*server):
                        continue
                    
                    all_data = []
                    offset = 0
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
                        for item in data:
                            try:
                                year = item.get('year', 0)
                                if 2000 <= year <= 2050:
                                    valid_data.append(item)
                            except Exception:
                                continue
                        
                        all_data.extend(valid_data)
                        if len(data) < 800:
                            break
                        offset += 800
                    
                    api.disconnect()
                    
                    if all_data and len(all_data) > 0:
                        records = self._parse_index_records(index_config, all_data, start_date, end_date)
                        if records:
                            self._save_records(db, 'index_daily', records, 'pytdx')
                            # 更新历史数据的 is_final
                            self._update_index_is_final(db['index_daily'])
                            logger.info(f"[pytdx] 成功同步 {index_config['name']} {len(records)} 条数据")
                            return {'success': True, 'records': len(records), 'source': 'pytdx', 'message': '同步完成'}
                    
                    break
                except Exception as e:
                    logger.warning(f"[pytdx] 服务器 {server} 获取 {index_config['name']} 失败: {e}")
                    continue
            
            return {'success': False, 'records': 0, 'source': 'pytdx', 'message': 'pytdx 同步失败'}
        except Exception as e:
            logger.warning(f"[pytdx] {index_config['name']} 失败: {e}")
            return {'success': False, 'records': 0, 'source': 'pytdx', 'message': str(e)}
    
    def _sync_index_akshare(self, index_config: Dict, start_date: str, end_date: str) -> Dict:
        """使用 akshare 同步指数数据"""
        try:
            import akshare as ak
            from pymongo import UpdateOne
            from app.data.db import get_db
            
            db = get_db()
            symbol = f"sh{index_config['tdx_code']}" if index_config.get('market', 1) == 1 else f"sz{index_config['tdx_code']}"
            
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty:
                return {'success': False, 'records': 0, 'source': 'akshare', 'message': 'akshare 无数据'}
            
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
                self._save_records(db, 'index_daily', records, 'akshare')
                # 更新历史数据的 is_final
                self._update_index_is_final(db['index_daily'])
                logger.info(f"[akshare] 成功同步 {index_config['name']} {len(records)} 条数据")
                return {'success': True, 'records': len(records), 'source': 'akshare', 'message': '同步完成'}
            
            return {'success': False, 'records': 0, 'source': 'akshare', 'message': 'akshare 无有效数据'}
        except Exception as e:
            logger.warning(f"[akshare] {index_config['name']} 失败: {e}")
            return {'success': False, 'records': 0, 'source': 'akshare', 'message': str(e)}
    
    def _sync_index_baostock(self, index_config: Dict, start_date: str, end_date: str) -> Dict:
        """使用 baostock 同步指数数据"""
        try:
            import baostock as bs
            from pymongo import UpdateOne
            from app.data.db import get_db
            
            db = get_db()
            bs.login()
            
            # baostock 指数代码格式
            bs_code = f"sh.{index_config['tdx_code']}" if index_config.get('market', 1) == 1 else f"sz.{index_config['tdx_code']}"
            
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}",
                end_date=f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}",
                frequency="d"
            )
            
            records = []
            while rs.next():
                row = rs.get_row_data()
                try:
                    date_str = row[0].replace('-', '')
                    close_val = float(row[4])
                    if close_val <= 0 or close_val > 100000:
                        continue
                    records.append({
                        'stock_code': index_config['code'],
                        'trade_date': date_str,
                        'open': float(row[1]),
                        'high': float(row[2]),
                        'low': float(row[3]),
                        'close': close_val,
                        'volume': float(row[5]) if row[5] else 0,
                        'amount': float(row[6]) if row[6] else 0,
                    })
                except Exception:
                    continue
            
            bs.logout()
            
            if records:
                self._save_records(db, 'index_daily', records, 'baostock')
                # 更新历史数据的 is_final
                self._update_index_is_final(db['index_daily'])
                logger.info(f"[baostock] 成功同步 {index_config['name']} {len(records)} 条数据")
                return {'success': True, 'records': len(records), 'source': 'baostock', 'message': '同步完成'}
            
            return {'success': False, 'records': 0, 'source': 'baostock', 'message': 'baostock 无有效数据'}
        except Exception as e:
            logger.warning(f"[baostock] {index_config['name']} 失败: {e}")
            return {'success': False, 'records': 0, 'source': 'baostock', 'message': str(e)}
    
    def _parse_index_records(self, index_config: Dict, data: List[Dict], 
                             start_date: str, end_date: str) -> List[Dict]:
        """解析指数数据为记录格式"""
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        today_str = now.strftime('%Y%m%d')
        is_market_closed = now.hour > 15 or (now.hour == 15 and now.minute >= 30)
        
        records = []
        for item in data:
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
                
                # 设置 is_final 字段
                # 历史日期：is_final=True
                # 今天：盘后(15:30+)为True，盘中为False
                if trade_date < today_str:
                    is_final = True
                elif trade_date == today_str:
                    is_final = is_market_closed
                else:
                    is_final = False
                
                records.append({
                    'stock_code': index_config['code'],
                    'trade_date': trade_date,
                    'open': open_val, 'high': high_val,
                    'low': low_val, 'close': close_val,
                    'volume': float(item.get('vol', item.get('volume', 0))),
                    'amount': float(item.get('amount', 0)),
                    'is_final': is_final,
                })
            except Exception:
                continue
        return records
    
    @staticmethod
    def _update_index_is_final(index_coll):
        """更新 index_daily 的 is_final 字段
        规则：只把今天之前的日期标为 is_final=True
        今天的 is_final 由 _parse_index_records 在写入时设置（盘后后=True）
        """
        try:
            from zoneinfo import ZoneInfo
            today_str = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
            # 只更新今天之前的日期
            index_coll.update_many(
                {'trade_date': {'$lt': today_str}, 'is_final': {'$ne': True}},
                {'$set': {'is_final': True}}
            )
            # 今天的 is_final 保持不变（由同步时设置）
        except Exception as e:
            logger.error(f"更新index is_final失败: {e}")
    
    def _save_records(self, db, collection_name: str, records: List[Dict], source: str):
        """保存记录到数据库"""
        from pymongo import UpdateOne
        
        ops = []
        for rec in records:
            doc = dict(rec)
            doc['data_type'] = 'index'
            doc['data_source'] = source
            doc['update_time'] = datetime.utcnow()
            ops.append(UpdateOne(
                {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
                {'$set': doc}, upsert=True,
            ))
        
        if ops:
            db[collection_name].bulk_write(ops, ordered=False)


# 全局单例
_data_service: Optional[DataService] = None


def get_data_service() -> DataService:
    """获取数据服务单例"""
    global _data_service
    if _data_service is None:
        _data_service = DataService()
    return _data_service
