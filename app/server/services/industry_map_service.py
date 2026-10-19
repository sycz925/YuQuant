"""
产业地图服务
调用 DeepSeek 生成产业链上/中/下游生态图谱，结果按 keyword 落库缓存
生成采用「后台任务 + 轮询」模式
"""
import json
import logging
import threading
from datetime import datetime as _dt
from typing import Any, Dict, List, Optional

from app.server.repositories import get_industry_map_repo

logger = logging.getLogger(__name__)

INDUSTRY_MAP_SYSTEM_PROMPT = """你是一位资深的产业链研究专家，精通 A 股各行业的上下游供应链结构。

用户会给你一个产业/行业关键字，请你输出该产业的完整产业链生态图谱，结构为「上游 → 中游 → 下游」。

[严格要求]
1. 输出必须为简体中文，且必须是合法 JSON（不要输出 Markdown 代码块、不要输出任何 JSON 之外的文字）。
2. 产业链结构：上游、中游、下游三大阶段（stage），每个阶段下按大类（categories）组织，大类下再细分垂直分类（subcategories）。
3. 每个垂直分类下列举「国内上市公司」的业务布局分析（companies），每家公司分析必须包含 4 个字段：
   - market_share：市占率描述（尽量量化，如"国内市占率约 X%，全球第 Y"）
   - market_position：市场地位（全球龙头/国内龙头/第二梯队/细分冠军等）
   - key_products：重要产品分析
   - key_partners：重要的大牌合作伙伴（下游客户或上游供应商）
4. 公司名称必须是真实存在的 A 股上市公司名称（或国内知名企业）。每家垂直分类列举 2-5 家代表性公司。
5. [实事求是铁律] 不确定的市占率用定性描述（如"国内领先""细分龙头"），严禁编造精确数字；无法确定的信息宁可省略，不要臆造。

[输出 JSON 结构]
{
  "industry": "产业名称",
  "overview": "一句话产业链概览",
  "chain": [
    {
      "stage": "上游",
      "summary": "上游概述",
      "categories": [
        {
          "name": "大类名称（如 材料）",
          "subcategories": [
            {
              "name": "垂直分类名称（如 光刻胶）",
              "companies": [
                {
                  "name": "上市公司名称",
                  "market_share": "市占率描述",
                  "market_position": "市场地位",
                  "key_products": "重要产品分析",
                  "key_partners": "重要合作伙伴"
                }
              ]
            }
          ]
        }
      ]
    },
    { "stage": "中游", "summary": "…", "categories": [ … ] },
    { "stage": "下游", "summary": "…", "categories": [ … ] }
  ]
}"""


# ========== 查询 / 历史 ==========

def get_cached_industry_map(keyword: str) -> Optional[Dict[str, Any]]:
    """按关键字读取缓存（动态回填个股最新 RPS）"""
    repo = get_industry_map_repo()
    cached = repo.get_by_keyword((keyword or '').strip())
    if cached:
        _attach_stock_rps(cached, repo)
    return cached


def list_history() -> List[Dict[str, Any]]:
    """历史记录列表"""
    return get_industry_map_repo().list_history()


def delete_cached_industry_map(keyword: str) -> int:
    """删除指定关键字的缓存，返回删除数量"""
    return get_industry_map_repo().delete_by_keyword((keyword or '').strip())


# ========== 任务编排 ==========

def start_industry_map_task(keyword: str) -> str:
    """启动后台生成任务，返回 task_id"""
    from app.data.task_manager import get_task_manager

    keyword = (keyword or '').strip()
    if not keyword:
        raise ValueError("产业关键字不能为空")

    tm = get_task_manager()
    steps = [{
        'name': f'生成「{keyword}」产业链图谱',
        'key': 'industry_map',
        'status': 'pending',
        'total_count': 1,
        'completed_count': 0,
        'failed_count': 0,
        'skipped_count': 0,
    }]
    task_id = tm.create_task_with_steps(steps, name='产业地图')
    thread = threading.Thread(target=_run_industry_map_task, args=(task_id, keyword), daemon=True)
    thread.start()
    return task_id


def _run_industry_map_task(task_id: str, keyword: str):
    """后台执行：调 DeepSeek → 归一化 → 代码匹配 → 落库"""
    from app.data.task_manager import get_task_manager

    tm = get_task_manager()
    repo = get_industry_map_repo()
    try:
        tm.start_step(task_id, 0)
        tm.update_task_progress(task_id, current_stock_name=f"调用 DeepSeek 生成「{keyword}」产业链…")

        result = _generate_via_deepseek(keyword)
        result = _normalize(result, keyword)
        _match_stock_codes(result, repo)
        repo.upsert(keyword, result)

        tm.complete_step(task_id, 0, f"「{keyword}」产业链生成完成")
        tm.complete_task(task_id, f"「{keyword}」产业链生成完成")
    except Exception as e:
        logger.error(f"产业地图任务失败: {e}")
        try:
            tm.fail_task(task_id, str(e)[:200])
        except Exception:
            pass


# ========== 外部 JSON 导入 ==========

def import_industry_map(json_text, keyword: Optional[str] = None) -> Dict[str, Any]:
    """导入外部查好的产业链 JSON（跳过 DeepSeek，直接归一化 + 代码匹配 + 落库）

    :param json_text: 产业链 JSON 文本（或已解析的 dict）
    :param keyword: 可选关键字；不传则取 JSON 中的 industry 字段
    :return: 落库后的完整产业链数据
    """
    if isinstance(json_text, dict):
        raw = json_text
    else:
        raw = json.loads((json_text or '').strip())

    if not isinstance(raw, dict):
        raise ValueError("JSON 根节点必须是对象（需含 industry / chain 字段）")

    kw = (keyword or '').strip() or str(raw.get('industry') or '').strip()
    if not kw:
        raise ValueError("无法确定产业关键字：请填写关键字，或在 JSON 中提供 industry 字段")

    chain = raw.get('chain')
    if not isinstance(chain, list) or not chain:
        raise ValueError("JSON 中缺少有效的 chain 数组（上游/中游/下游）")

    repo = get_industry_map_repo()
    result = _normalize(raw, kw)
    if not result.get('chain'):
        raise ValueError("chain 解析后为空，请检查层级结构（stage → categories → subcategories → companies）")

    _match_stock_codes(result, repo)
    repo.upsert(kw, result)
    logger.info(f"[产业地图] 导入「{kw}」成功，共 {len(result['chain'])} 个阶段")
    return result


# ========== DeepSeek 调用 ==========

def _generate_via_deepseek(keyword: str) -> Dict[str, Any]:
    """调用 DeepSeek 生成产业链图谱 JSON"""
    from app.server.api.deepseek_analyst import get_deepseek_analyst

    analyst = get_deepseek_analyst()
    if not analyst.api_key:
        raise ValueError("DEEPSEEK_API_KEY 未配置")

    import openai
    client = openai.OpenAI(api_key=analyst.api_key, base_url=analyst.base_url)
    user_message = f"请分析「{keyword}」的产业链生态图谱（上游/中游/下游，含各环节上市公司的业务布局分析）。"

    content = _chat_complete(analyst, client, user_message)
    if not content:
        raise RuntimeError("DeepSeek 未返回有效内容")

    return json.loads(content)


def _chat_complete(analyst, client, user_message: str) -> Optional[str]:
    """thinking 模式生成；content 为空或 JSON 失败时显式关闭 thinking 重试"""

    def _kwargs(use_thinking: bool) -> dict:
        kw = {
            'model': analyst.model,
            'response_format': {'type': 'json_object'},
            'messages': [
                {'role': 'system', 'content': INDUSTRY_MAP_SYSTEM_PROMPT},
                {'role': 'user', 'content': user_message},
            ],
            'max_tokens': 8192,
            'timeout': 300,
        }
        if use_thinking:
            kw['reasoning_effort'] = 'high'
            kw['extra_body'] = {'thinking': {'type': 'enabled'}}
        else:
            kw['temperature'] = analyst.temperature
            kw['extra_body'] = {'thinking': {'type': 'disabled'}}
        return kw

    content = None
    try:
        content = client.chat.completions.create(**_kwargs(True)).choices[0].message.content
    except Exception as e:
        logger.warning(f"[产业地图] thinking 调用失败: {e}")

    if content:
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError as e:
            logger.warning(f"[产业地图] thinking JSON 解析失败: {e}")

    logger.warning("[产业地图] content 为空或 JSON 不完整，显式关闭 thinking 重试")
    try:
        content = client.chat.completions.create(**_kwargs(False)).choices[0].message.content
        if content:
            json.loads(content)
            return content
    except json.JSONDecodeError as e:
        logger.warning(f"[产业地图] 关闭 thinking 后 JSON 仍解析失败: {e}")
    except Exception as e:
        logger.error(f"[产业地图] 关闭 thinking 重试失败: {e}")

    return None


# ========== 归一化 + 代码匹配 ==========

def _normalize(result: Dict[str, Any], keyword: str) -> Dict[str, Any]:
    """把 DeepSeek 返回的 JSON 归一化为稳定结构，缺字段补空、非法层级丢弃"""
    chain = []
    for stage_raw in result.get('chain') if isinstance(result.get('chain'), list) else []:
        if not isinstance(stage_raw, dict):
            continue
        stage = (stage_raw.get('stage') or '').strip()
        if not stage:
            continue

        categories = []
        for cat_raw in stage_raw.get('categories') if isinstance(stage_raw.get('categories'), list) else []:
            if not isinstance(cat_raw, dict):
                continue
            subcategories = []
            for sub_raw in cat_raw.get('subcategories') if isinstance(cat_raw.get('subcategories'), list) else []:
                if not isinstance(sub_raw, dict):
                    continue
                companies = []
                for comp_raw in sub_raw.get('companies') if isinstance(sub_raw.get('companies'), list) else []:
                    if not isinstance(comp_raw, dict):
                        continue
                    companies.append({
                        'name': (comp_raw.get('name') or '').strip(),
                        'stock_code': comp_raw.get('stock_code'),
                        'market': comp_raw.get('market'),
                        'market_share': comp_raw.get('market_share') or '',
                        'market_position': comp_raw.get('market_position') or '',
                        'key_products': comp_raw.get('key_products') or '',
                        'key_partners': comp_raw.get('key_partners') or '',
                    })
                subcategories.append({'name': (sub_raw.get('name') or '').strip(), 'companies': companies})
            categories.append({'name': (cat_raw.get('name') or '').strip(), 'subcategories': subcategories})
        chain.append({'stage': stage, 'summary': stage_raw.get('summary') or '', 'categories': categories})

    return {
        'keyword': keyword,
        'industry': result.get('industry') or keyword,
        'overview': result.get('overview') or '',
        'chain': chain,
        'generated_at': _dt.now().isoformat(),
    }


def _match_stock_codes(result: Dict[str, Any], repo) -> None:
    """遍历所有公司，按名称匹配 stock_basics 回填 stock_code / market"""
    for stage in result.get('chain', []):
        for cat in stage.get('categories', []):
            for sub in cat.get('subcategories', []):
                for comp in sub.get('companies', []):
                    name = (comp.get('name') or '').strip()
                    if not name:
                        continue
                    stock = repo.get_stock_code_by_name(name)
                    if stock:
                        comp['stock_code'] = stock.get('stock_code')
                        comp['market'] = stock.get('market')


def _attach_stock_rps(result: Dict[str, Any], repo) -> None:
    """遍历个股，回填 stock_daily 最新 rps_10/rps_50/rps_120（动态数据，不落库）"""
    codes = []
    for stage in result.get('chain', []):
        for cat in stage.get('categories', []):
            for sub in cat.get('subcategories', []):
                for comp in sub.get('companies', []):
                    code = comp.get('stock_code')
                    if code:
                        codes.append(code)
    if not codes:
        return

    rps_map = repo.get_latest_stock_rps(codes)
    for stage in result.get('chain', []):
        for cat in stage.get('categories', []):
            for sub in cat.get('subcategories', []):
                for comp in sub.get('companies', []):
                    rps = rps_map.get(comp.get('stock_code'))
                    if rps:
                        comp['rps_10'] = rps.get('rps_10')
                        comp['rps_50'] = rps.get('rps_50')
                        comp['rps_120'] = rps.get('rps_120')


def get_industry_intersection(keywords: List[str]) -> List[Dict[str, Any]]:
    """求多个产业的交集个股（stock_code 优先，无 code 按 name 兜底）。

    返回：[{name, stock_code, market, market_share, market_position,
           key_products, key_partners, rps_10, rps_50, rps_120,
           matched_in: [{keyword, stage, category, subcategory}]}]
    """
    repo = get_industry_map_repo()

    # 收集每个产业的 company（按标识去重：有 code 用 code，无 code 用 name）
    industry_data = []
    for kw in keywords:
        kw = (kw or '').strip()
        if not kw:
            continue
        # 用 get_cached_industry_map 读取，确保动态回填个股最新 RPS
        cached = get_cached_industry_map(kw)
        if not cached:
            continue

        companies: Dict[str, Dict[str, Any]] = {}
        for stage in cached.get('chain', []):
            for cat in stage.get('categories', []):
                for sub in cat.get('subcategories', []):
                    for comp in sub.get('companies', []):
                        name = (comp.get('name') or '').strip()
                        code = comp.get('stock_code')
                        identifier = code or name
                        if not identifier or identifier in companies:
                            continue
                        companies[identifier] = {
                            'name': name,
                            'stock_code': code,
                            'market': comp.get('market'),
                            'market_share': comp.get('market_share'),
                            'market_position': comp.get('market_position'),
                            'key_products': comp.get('key_products'),
                            'key_partners': comp.get('key_partners'),
                            'rps_10': comp.get('rps_10'),
                            'rps_50': comp.get('rps_50'),
                            'rps_120': comp.get('rps_120'),
                            'stage': stage.get('stage'),
                            'category': cat.get('name'),
                            'subcategory': sub.get('name'),
                        }
        industry_data.append({'keyword': kw, 'companies': companies})

    if not industry_data:
        return []

    # 求交集：标识需出现在所有产业中
    common_ids = set(industry_data[0]['companies'].keys())
    for d in industry_data[1:]:
        common_ids &= set(d['companies'].keys())

    # 组装结果（保留个股卡片完整数据内容）
    result = []
    for identifier in common_ids:
        first = industry_data[0]['companies'][identifier]
        item = {
            'name': first['name'],
            'stock_code': first['stock_code'],
            'market': first['market'],
            'market_share': first['market_share'],
            'market_position': first['market_position'],
            'key_products': first['key_products'],
            'key_partners': first['key_partners'],
            'rps_10': first['rps_10'],
            'rps_50': first['rps_50'],
            'rps_120': first['rps_120'],
            'matched_in': [],
        }
        for d in industry_data:
            comp = d['companies'][identifier]
            item['matched_in'].append({
                'keyword': d['keyword'],
                'stage': comp['stage'],
                'category': comp['category'],
                'subcategory': comp['subcategory'],
            })
        result.append(item)

    # 有代码的排前面，按代码排序；无代码的按名称
    result.sort(key=lambda x: (x['stock_code'] is None, x['stock_code'] or '', x['name']))
    return result
