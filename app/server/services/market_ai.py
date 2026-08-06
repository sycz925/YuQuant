"""
AI 分析服务
负责 DeepSeek 调用和 AI 分析结果落库
从 api/market_review.py 迁移而来
"""
import logging
from datetime import datetime as _dt

from app.data.db import get_db

logger = logging.getLogger(__name__)


def call_deepseek(trade_date: str, market_data: dict) -> dict:
    """调用 DeepSeek 并落库"""
    from app.server.api.deepseek_analyst import get_deepseek_analyst

    analyst = get_deepseek_analyst()

    if not analyst.api_key:
        raise ValueError("DEEPSEEK_API_KEY 未配置")

    db = get_db()
    ai_result = analyst.analyze(market_data)
    ai_result['generated_at'] = _dt.now().isoformat()

    # 检查是否是降级结果（API调用失败）
    diagnosis = ai_result.get('market_phase_diagnosis', '')
    is_fallback = (
        diagnosis == '系统分析服务暂时不可用，请稍后重试。' or
        '不可用' in diagnosis or
        '失败' in diagnosis or
        '未配置' in diagnosis or
        not diagnosis
    )
    ai_result['source'] = 'failed' if is_fallback else 'deepseek'

    # 落库
    db['market_daily'].update_one(
        {'trade_date': trade_date},
        {'$set': {'ai_analysis': ai_result}}
    )
    logger.info(f"[AI分析] {trade_date} 来源={ai_result['source']}")
    return ai_result