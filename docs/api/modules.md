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

## 4. FastAPI 后端路由

### API 路由模块

```python
# app/server/api/stocks.py - 股票数据 API
- GET /api/stocks - 获取股票列表
- GET /api/stocks/search - 搜索股票
- GET /api/stocks/{code} - 获取股票详情
- GET /api/stocks/{code}/daily - 获取日线数据

# app/server/api/factors.py - 因子 API
- GET /api/factors/cr5 - 获取 CR5 因子数据
- POST /api/factors/sync-indices - 同步指数数据
- POST /api/factors/sync-sectors - 同步板块数据
- POST /api/factors/rps/calculate - 计算 RPS
- GET /api/factors/rps/{code} - 获取个股 RPS

# app/server/api/sync.py - 数据同步 API
- POST /api/sync/basics - 同步股票基础信息
- POST /api/sync/daily - 同步日线数据
- GET /api/sync/task/{task_id} - 查询任务状态

# app/server/api/market_analysis.py - 市场分析 API
- GET /api/market_analysis - 获取市场分析
- GET /api/market_analysis/bubble - 获取气泡图数据
- GET /api/market_analysis/active_pool - 获取活跃池
```
