"""
调试脚本：生成指定日期的 AI 分析数据，打印传给 DeepSeek 的完整报文
"""
import sys
import os
import json

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.db import get_db
from app.server.api.deepseek_analyst import get_deepseek_analyst, SYSTEM_PROMPT

TARGET_DATE = '20260506'


def collect_market_data(trade_date: str) -> dict:
    """收集指定日期的市场数据"""
    db = get_db()

    # 获取 market_daily 数据
    cached = db['market_daily'].find_one({'trade_date': trade_date}, {'_id': 0})
    if not cached:
        print(f"[ERROR] {trade_date} 无 market_daily 数据")
        return None

    market_data = {
        'trade_date': trade_date,
        'overview': cached.get('overview', {}),
        'new_high': cached.get('new_high', {}),
        'low_position_sectors': cached.get('low_position_sectors', []),
    }

    return market_data


def main():
    print(f"=" * 80)
    print(f"生成 {TARGET_DATE} 的 AI 分析报文")
    print(f"=" * 80)
    print()

    # 1. 收集市场数据
    market_data = collect_market_data(TARGET_DATE)
    if not market_data:
        return

    # 2. 获取 DeepSeek Analyst 实例
    analyst = get_deepseek_analyst()

    # 3. 构建用户消息
    user_message = analyst._build_user_message(market_data)

    # 4. 打印完整报文
    print("=" * 80)
    print("【系统指令 (SYSTEM_PROMPT)】")
    print("=" * 80)
    print(SYSTEM_PROMPT)
    print()
    print("=" * 80)
    print("【用户消息 (USER_MESSAGE)】")
    print("=" * 80)
    print(user_message)
    print()

    # 5. 打印完整的 API 请求体
    print("=" * 80)
    print("【完整请求体 JSON】")
    print("=" * 80)
    request_body = {
        "model": analyst.model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": 4096,
    }
    if analyst.enable_thinking:
        request_body["reasoning_effort"] = "high"
        request_body["extra_body"] = {"thinking": {"type": "enabled"}}

    print(json.dumps(request_body, ensure_ascii=False, indent=2))
    print()

    # 6. 如果想实际调用 API，取消下面注释
    # print("=" * 80)
    # print("【调用 DeepSeek API】")
    # print("=" * 80)
    # result = analyst.analyze(market_data)
    # print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
