"""
yfinance 数据源封装 - 主要用于获取中国 A 股数据
注意：yfinance 对 A 股支持有限，主要作为备用数据源
"""
import time
import pandas as pd
from typing import Optional, Tuple


class YFinanceSource:
    @staticmethod
    def to_yfinance_code(stock_code: str) -> str:
        """转换为 yfinance 格式的代码
        A 股规则：
        - 沪市（60、688 开头）: .SS 后缀
        - 深市（00、30、002 开头）: .SZ 后缀
        """
        if stock_code.startswith('6') or stock_code.startswith('688'):
            return f"{stock_code}.SS"
        else:
            return f"{stock_code}.SZ"
    
    @staticmethod
    def get_stock_basics() -> Optional[pd.DataFrame]:
        """获取股票基础信息
        yfinance 不支持批量获取股票列表，返回 None
        """
        return None
    
    @staticmethod
    def get_daily_data(stock_code: str, start_date: str, end_date: str) -> Tuple[Optional[pd.DataFrame], str]:
        """
        获取日线行情数据
        返回: (DataFrame, data_source)
        """
        import yfinance as yf
        
        yf_code = YFinanceSource.to_yfinance_code(stock_code)
        
        for attempt in range(2):
            try:
                # 转换日期格式: YYYYMMDD -> YYYY-MM-DD
                s_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if len(start_date) == 8 else start_date
                e_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date
                
                # 获取数据
                ticker = yf.Ticker(yf_code)
                df = ticker.history(start=s_date, end=e_date, auto_adjust=False)
                
                if df is not None and not df.empty:
                    # yfinance 返回的索引是日期
                    df = df.reset_index()
                    
                    # 字段映射
                    result_df = pd.DataFrame()
                    result_df['trade_date'] = df['Date'].dt.strftime('%Y%m%d')
                    result_df['open'] = df['Open']
                    result_df['high'] = df['High']
                    result_df['low'] = df['Low']
                    result_df['close'] = df['Close']
                    result_df['volume'] = df['Volume']
                    
                    # 计算涨跌相关（可选）
                    if 'Close' in df.columns and len(df) > 1:
                        result_df['change'] = df['Close'].diff()
                        result_df['change_pct'] = df['Close'].pct_change() * 100
                    
                    return result_df, 'yfinance'
                    
            except Exception as e:
                print(f"yfinance 获取数据失败 {stock_code} (尝试 {attempt + 1}/2): {e}")
                if attempt < 1:
                    time.sleep(1)
        
        return None, ''
