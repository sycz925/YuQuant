"""
AkShare 数据源封装
"""
import time
import pandas as pd
from typing import Optional, Tuple


class AkShareSource:
    @staticmethod
    def get_stock_basics() -> Optional[pd.DataFrame]:
        """获取股票基础信息"""
        import akshare as ak
        for attempt in range(3):
            try:
                df = ak.stock_info_a_code_name()
                if not df.empty:
                    df.columns = ['stock_code', 'stock_name']
                    df['market'] = df['stock_code'].apply(
                        lambda x: 'SH' if x.startswith('6') else 'SZ'
                    )
                    df['list_date'] = None
                    return df
            except Exception as e:
                print(f"AkShare 获取股票列表失败 (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))  # 指数退避
        return None

    @staticmethod
    def get_daily_data(stock_code: str, start_date: str, end_date: str) -> Tuple[Optional[pd.DataFrame], str]:
        """
        获取日线行情数据
        返回: (DataFrame, data_source)
        """
        import akshare as ak
        for attempt in range(3):
            try:
                df = ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq"
                )
                if not df.empty:
                    # 字段映射
                    result_df = pd.DataFrame()
                    result_df['trade_date'] = df['日期'].astype(str).str.replace('-', '')
                    result_df['open'] = df['开盘']
                    result_df['high'] = df['最高']
                    result_df['low'] = df['最低']
                    result_df['close'] = df['收盘']
                    result_df['volume'] = df['成交量']
                    result_df['amount'] = df['成交额']
                    if '涨跌幅' in df.columns:
                        result_df['change_pct'] = df['涨跌幅']
                    if '涨跌额' in df.columns:
                        result_df['change'] = df['涨跌额']
                    if '振幅' in df.columns:
                        result_df['amplitude'] = df['振幅']
                    if '换手率' in df.columns:
                        result_df['turnover'] = df['换手率']
                    return result_df, 'akshare'
            except Exception as e:
                print(f"AkShare 获取数据失败 {stock_code} (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))  # 指数退避
        return None, ''
