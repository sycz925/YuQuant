# 模块接口规范

## 1. data_manager.py - 数据管理器

### 类定义

```python
class DataManager:
    """
    数据管理器，负责数据获取、缓存、清洗和复权处理
    """
    
    def __init__(self, db_path: str, hdf5_path: str):
        """
        初始化数据管理器
        
        Args:
            db_path: SQLite 数据库文件路径
            hdf5_path: HDF5 数据文件目录路径
        """
    
    def sync_stock_basics(self) -> None:
        """同步股票基础信息到 SQLite"""
    
    def sync_index_basics(self) -> None:
        """同步指数基础信息到 SQLite"""
    
    def sync_daily_data(self, stock_codes: List[str], start_date: str, end_date: str) -> None:
        """
        同步日线数据到 HDF5
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
        """
    
    def sync_stock_universe(self, trade_date: str) -> None:
        """
        同步指定交易日的可用股票池（防幸存者偏差）
        
        Args:
            trade_date: 交易日 (YYYYMMDD)
        """
    
    def get_stock_universe(self, trade_date: str) -> List[str]:
        """
        获取指定交易日的可用股票池
        
        Args:
            trade_date: 交易日 (YYYYMMDD)
            
        Returns:
            可用股票代码列表
        """
    
    def get_daily_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票日线数据（后复权）
        
        Args:
            stock_code: 股票代码
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            
        Returns:
            包含 open, high, low, close, volume, amount 的 DataFrame
        """
    
    def get_adj_close(self, stock_code: str, trade_date: str) -> float:
        """
        获取指定日期的后复权收盘价
        
        Args:
            stock_code: 股票代码
            trade_date: 交易日 (YYYYMMDD)
            
        Returns:
            后复权收盘价
        """
    
    def get_index_data(self, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取指数日线数据"""
```

---

## 2. factor_engine.py - 因子引擎

### 类定义

```python
class FactorEngine:
    """
    因子引擎，负责技术指标和因子计算
    """
    
    def __init__(self, data_manager: DataManager):
        """
        初始化因子引擎
        
        Args:
            data_manager: 数据管理器实例
        """
    
    def calculate_cr5_percent(self, trade_date: str) -> float:
        """
        计算成交额前 5% 拥挤度因子
        
        Args:
            trade_date: 交易日 (YYYYMMDD)
            
        Returns:
            前 5% 股票成交额占比 (0-100)
        """
    
    def calculate_ma(self, stock_code: str, trade_date: str, window: int) -> Optional[float]:
        """
        计算单只股票的移动平均
        
        Args:
            stock_code: 股票代码
            trade_date: 交易日 (YYYYMMDD)
            window: 窗口大小
            
        Returns:
            移动平均值，数据不足返回 None
        """
    
    def batch_calculate_ma(self, stock_codes: List[str], start_date: str, 
                          end_date: str, window: int) -> pd.DataFrame:
        """
        批量计算移动平均
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            window: 窗口大小
            
        Returns:
            MultiIndex DataFrame (date × stock_code)
        """
    
    def calculate_index_ma(self, index_code: str, trade_date: str, window: int) -> Optional[float]:
        """计算指数的移动平均"""
    
    def get_all_cr5_history(self, start_date: str, end_date: str) -> pd.Series:
        """
        获取历史 CR5% 序列
        
        Returns:
            日期索引的 CR5% 序列
        """
```

---

## 3. sentiment_engine.py - 舆情分析引擎

### 类定义

```python
class SentimentEngine:
    """
    舆情分析引擎，负责舆情数据获取和时效对齐
    """
    
    def __init__(self, data_manager: DataManager):
        """
        初始化舆情分析引擎
        
        Args:
            data_manager: 数据管理器实例
        """
    
    def sync_sentiment_data(self, stock_code: str, start_date: str, end_date: str) -> None:
        """
        同步舆情数据
        
        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        """
    
    def get_sentiment_score(self, stock_code: str, trade_date: str) -> Optional[float]:
        """
        获取指定日期的舆情得分（严格时效对齐）
        
        Args:
            stock_code: 股票代码
            trade_date: 交易日 (YYYYMMDD)
            
        Returns:
            舆情得分 (-1 到 1)，无数据返回 None
        """
    
    def get_sentiment_by_date_range(self, stock_code: str, start_date: str, 
                                   end_date: str) -> pd.DataFrame:
        """获取日期范围内的舆情数据"""
```

---

## 4. backtest_engine.py - 回测引擎

### 类定义

```python
@dataclass
class Trade:
    """交易记录"""
    stock_code: str
    stock_name: str
    direction: str  # BUY/SELL
    quantity: int
    signal_price: float
    execute_price: float
    commission: float
    transfer_fee: float
    stamp_duty: float
    reason: str
    signal_time: str
    execute_time: str


@dataclass
class Position:
    """持仓记录"""
    stock_code: str
    stock_name: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    pnl: float


@dataclass
class BacktestResult:
    """回测结果"""
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    equity_curve: pd.Series
    trade_log: pd.DataFrame


class BacktestEngine:
    """
    回测引擎，模拟真实交易环境
    """
    
    def __init__(self, data_manager: DataManager, factor_engine: FactorEngine,
                 sentiment_engine: Optional[SentimentEngine] = None,
                 initial_capital: float = 1000000):
        """
        初始化回测引擎
        
        Args:
            data_manager: 数据管理器
            factor_engine: 因子引擎
            sentiment_engine: 舆情分析引擎（可选）
            initial_capital: 初始资金
        """
    
    def set_commission(self, commission_rate: float = 0.0003, 
                      min_commission: float = 5.0,
                      transfer_fee_rate: float = 0.00002,
                      stamp_duty_rate: float = 0.0005) -> None:
        """设置交易费用"""
    
    def set_risk_control(self, stop_loss: float = 0.08, 
                       take_profit: float = 0.08,
                       cr5_stop_threshold: float = 40.0) -> None:
        """设置风控参数"""
    
    def set_strategy(self, strategy: Strategy) -> None:
        """设置策略"""
    
    def run(self, start_date: str, end_date: str) -> BacktestResult:
        """
        运行回测
        
        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            
        Returns:
            回测结果对象
        """
    
    def get_trade_log(self) -> pd.DataFrame:
        """获取交易日志"""
    
    def get_equity_curve(self) -> pd.Series:
        """获取资金曲线"""


class Strategy(ABC):
    """策略基类"""
    
    @abstractmethod
    def on_bar(self, engine: BacktestEngine, trade_date: str) -> None:
        """
        每个交易日调用
        
        Args:
            engine: 回测引擎实例
            trade_date: 当前交易日
        """
```

---

## 5. app.py - Streamlit 应用

### 应用结构

```python
def main():
    """应用入口"""
    
    # 页面配置
    st.set_page_config(page_title="A 股量化回测系统", layout="wide")
    
    # 侧边栏
    with st.sidebar:
        st.header("控制面板")
        
        # 数据同步按钮
        if st.button("🔄 同步最新数据"):
            sync_data()
        
        # 日期选择
        start_date = st.date_input("开始日期")
        end_date = st.date_input("结束日期")
        
        # 策略参数
        strategy_name = st.selectbox("策略选择", [])
        
        # 运行按钮
        if st.button("🚀 运行回测"):
            run_backtest()
    
    # 主界面
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总收益率", "0%")
    with col2:
        st.metric("年化收益率", "0%")
    with col3:
        st.metric("最大回撤", "0%")
    with col4:
        st.metric("夏普比率", "0")
    
    # CR5% 走势图
    st.subheader("成交额前 5% 拥挤度（CR5%）")
    plot_cr5_chart()
    
    # 回测结果
    st.subheader("回测结果")
    display_backtest_results()
    
    # 交易日志
    st.subheader("交易日志")
    display_trade_log()
```
