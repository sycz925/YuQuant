"""
Tushare 数据源封装
"""
import os
import time
import pandas as pd
from typing import Optional, Tuple
from dotenv import load_dotenv

load_dotenv()


class TushareSource:
    def __init__(self):
        token = os.getenv('TUSHARE_TOKEN')
        if not token:
            raise ValueError("请在 .env 文件中设置 TUSHARE_TOKEN")
        
        # 先设置环境变量，这样 tushare 会直接从环境变量读取，不会去读/写 tk.csv
        os.environ['TUSHARE_TOKEN'] = token
        
        # 导入 tushare 并直接创建 pro_api 实例，不调用 ts.set_token()，避免写入文件
        import tushare as ts
        self.pro = ts.pro_api(token)

    @staticmethod
    def to_tushare_code(stock_code: str) -> str:
        """转换为 Tushare 格式的代码"""
        if stock_code.startswith('6'):
            return f"{stock_code}.SH"
        else:
            return f"{stock_code}.SZ"

    @staticmethod
    def from_tushare_code(ts_code: str) -> str:
        """从 Tushare 格式转换回标准格式"""
        return ts_code.split('.')[0]

    def get_stock_basics(self) -> Optional[pd.DataFrame]:
        """获取股票基础信息"""
        for attempt in range(2):
            try:
                df = self.pro.stock_basic(
                    exchange='',
                    list_status='L',
                    fields='ts_code,symbol,name,area,industry,list_date'
                )
                if not df.empty:
                    df['stock_code'] = df['symbol']
                    df['stock_name'] = df['name']
                    df['market'] = df['ts_code'].apply(lambda x: 'SH' if x.endswith('.SH') else 'SZ')
                    return df[['stock_code', 'stock_name', 'market', 'list_date']]
            except Exception as e:
                print(f"Tushare 获取股票列表失败 (尝试 {attempt + 1}/2): {e}")
                if attempt < 1:
                    time.sleep(1)
        return None

    def get_daily_data(self, stock_code: str, start_date: str, end_date: str) -> Tuple[Optional[pd.DataFrame], str]:
        """
        获取日线行情数据
        返回: (DataFrame, data_source)
        """
        ts_code = self.to_tushare_code(stock_code)
        for attempt in range(2):
            try:
                df = self.pro.daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
                if not df.empty:
                    # 字段映射
                    result_df = pd.DataFrame()
                    result_df['trade_date'] = df['trade_date']
                    result_df['open'] = df['open']
                    result_df['high'] = df['high']
                    result_df['low'] = df['low']
                    result_df['close'] = df['close']
                    result_df['volume'] = df['vol']
                    result_df['amount'] = df['amount']
                    result_df['change_pct'] = df['pct_chg']
                    result_df['change'] = df['change']
                    return result_df, 'tushare'
            except Exception as e:
                print(f"Tushare 获取数据失败 {stock_code} (尝试 {attempt + 1}/2): {e}")
                if attempt < 1:
                    time.sleep(1)
        return None, ''
