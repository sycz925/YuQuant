"""
数据模型定义
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class StockBasic(BaseModel):
    """股票基础信息"""
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    market: str = Field(..., description="市场 SH/SZ")


class DailyBar(BaseModel):
    """日线数据"""
    trade_date: str = Field(..., description="交易日期 YYYYMMDD")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: int = Field(..., description="成交量")
    amount: float = Field(..., description="成交额")
    amplitude: Optional[float] = Field(None, description="振幅")
    change_pct: Optional[float] = Field(None, description="涨跌幅")
    change: Optional[float] = Field(None, description="涨跌额")
    turnover: Optional[float] = Field(None, description="换手率")
    # 均线字段
    ma10: Optional[float] = Field(None, description="10日均线")
    ma20: Optional[float] = Field(None, description="20日均线")
    ma50: Optional[float] = Field(None, description="50日均线")
    ma120: Optional[float] = Field(None, description="120日均线")
    # 成交量均线字段
    vol_ma5: Optional[float] = Field(None, description="5日成交量均线")
    vol_ma10: Optional[float] = Field(None, description="10日成交量均线")
    vol_ma20: Optional[float] = Field(None, description="20日成交量均线")
    vol_ma50: Optional[float] = Field(None, description="50日成交量均线")


class StockListResponse(BaseModel):
    """股票列表响应"""
    total: int = Field(..., description="总数")
    data: List[StockBasic] = Field(..., description="股票列表")


class DailyDataResponse(BaseModel):
    """日线数据响应"""
    code: str = Field(..., description="股票代码")
    total: int = Field(..., description="数据条数")
    data: List[DailyBar] = Field(..., description="日线数据列表")


class CR5FactorData(BaseModel):
    """CR5%因子数据"""
    trade_date: str = Field(..., description="交易日期")
    value: float = Field(..., description="CR5%值")


class CR5FactorResponse(BaseModel):
    """CR5因子响应"""
    total: int = Field(..., description="数据条数")
    data: List[CR5FactorData] = Field(..., description="因子数据列表")
    index_data: Optional[Dict[str, List[Dict[str, Any]]]] = Field(None, description="指数数据")
    index_config: Optional[List[Dict[str, str]]] = Field(None, description="指数配置")


class SyncRequest(BaseModel):
    """数据同步请求"""
    stock_codes: Optional[List[str]] = Field(None, alias="stockCodes", description="股票列表（可选，为空则同步全部）")
    start_date: Optional[str] = Field(None, alias="startDate", description="开始日期（可选）")
    end_date: Optional[str] = Field(None, alias="endDate", description="结束日期（可选）")
    max_workers: Optional[int] = Field(4, alias="maxWorkers", description="最大线程数（默认4）")
    min_days: Optional[int] = Field(None, alias="minDays", description="最小上市天数（可选，过滤不满足条件的股票）")

    class Config:
        populate_by_name = True


class SyncResponse(BaseModel):
    """数据同步响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息")
    success_count: Optional[int] = Field(None, description="成功数量")
    fail_count: Optional[int] = Field(None, description="失败数量")
    used_fallback: Optional[bool] = Field(None, description="是否使用降级策略")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = Field("ok", description="状态")
    timestamp: str = Field(..., description="时间戳")
    version: str = Field(..., description="版本号")
    latest_trade_date: Optional[str] = Field(None, description="最新交易日 YYYYMMDD")
