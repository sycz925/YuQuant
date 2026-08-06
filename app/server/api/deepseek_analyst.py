"""
DeepSeek AI 分析服务 - API 层薄包装
所有业务逻辑已迁移至 app.server.services.deepseek_analyst
此文件保留向后兼容的导入路径
"""
from app.server.services.deepseek_analyst import (
    DeepSeekAnalyst,
    SYSTEM_PROMPT,
    get_deepseek_analyst,
    is_deepseek_available,
    is_market_open,
)

__all__ = [
    'DeepSeekAnalyst',
    'SYSTEM_PROMPT',
    'get_deepseek_analyst',
    'is_deepseek_available',
    'is_market_open',
]