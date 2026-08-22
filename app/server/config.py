"""
配置中心 - 统一管理所有配置项
使用 pydantic-settings 从环境变量和 .env 文件读取配置
"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """应用配置"""
    
    # MongoDB 配置
    MONGODB_URI: str = Field(default="mongodb://localhost:27017", description="MongoDB 连接 URI")
    MONGODB_DB_NAME: str = Field(default="yuquant", description="MongoDB 数据库名")
    
    # CORS 配置
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="CORS 允许的来源"
    )
    
    # API 密钥
    LEGULEGU_TOKEN: str = Field(default="", description="乐咕乐股 PE 数据 Token")
    DEEPSEEK_API_KEY: str = Field(default="", description="DeepSeek API Key")
    
    # 同步时间窗口配置
    SYNC_WINDOW_LUNCH_START: int = Field(default=690, description="午盘开始时间（分钟数，11:30=690）")
    SYNC_WINDOW_LUNCH_END: int = Field(default=780, description="午盘结束时间（分钟数，13:00=780）")
    SYNC_WINDOW_AFTER_MARKET_START: int = Field(default=960, description="盘后开始时间（分钟数，16:00=960）")
    
    # 任务配置
    TASK_TIMEOUT_SECONDS: int = Field(default=3600, description="任务超时时间（秒）")
    TASK_MAX_RETRIES: int = Field(default=3, description="任务最大重试次数")
    
    # 日志配置
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    DEBUG: bool = Field(default=False, description="调试模式（异常响应是否回传内部细节）")
    
    # Tushare Token（可选）
    TUSHARE_TOKEN: str = Field(default="", description="Tushare API Token")
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


# 全局设置单例
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取配置单例"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """重新加载配置"""
    global _settings
    _settings = Settings()
    return _settings
