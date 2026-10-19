"""
持仓风控 API

路由层保持薄：只做参数解析 + 调用 PositionService + 组装响应。
业务异常 PositionError 统一转换为 HTTP 状态码（AGENTS.md §7）。
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.server.services import position_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["positions"])


# ==================== 请求模型 ====================

class AccountCreateRequest(BaseModel):
    account_name: str = Field(..., description="账户名称")
    initial_capital: float = Field(..., description="初始资金")
    risk_ratio_per_trade: Optional[float] = Field(None, description="单笔风险比例，默认 0.005")


class AccountUpdateRequest(BaseModel):
    account_name: Optional[str] = Field(None, description="账户名称")
    risk_ratio_per_trade: Optional[float] = Field(None, description="单笔风险比例")
    capital_delta: Optional[float] = Field(None, description="出入金金额（正=入金，负=出金）")
    is_disable: Optional[bool] = Field(None, description="是否禁用（禁用后不产生预警、不参与批量刷新）")
    is_primary: Optional[bool] = Field(None, description="是否设为主账户（全局唯一，进入持仓页默认展示）")


class EntryPreviewRequest(BaseModel):
    account_id: str = Field(..., description="账户 ID")
    stock_code: str = Field(..., description="代码（个股/ETF）")
    buy_date: str = Field(..., description="买入日期 YYYYMMDD")
    buy_price: float = Field(..., gt=0, description="买入价")
    buy_shares: int = Field(..., gt=0, description="买入股数（100 的整数倍）")

    model_config = {"populate_by_name": True}


class PositionCreateRequest(EntryPreviewRequest):
    force: bool = Field(False, description="风险超标时是否仍按原股数建仓")
    note: Optional[str] = Field(None, description="备注")


class PositionCloseRequest(BaseModel):
    sell_date: str = Field(..., description="卖出日期")
    sell_price: float = Field(..., gt=0, description="卖出价")
    note: Optional[str] = Field(None, description="备注")


class PositionSellRequest(BaseModel):
    sell_date: str = Field(..., description="卖出日期")
    sell_price: float = Field(..., gt=0, description="卖出价")
    shares: Optional[int] = Field(None, description="卖出股数，留空=卖出全部剩余")
    reason: str = Field("manual", description="卖出理由：take_profit / stop_loss / manual")
    note: Optional[str] = Field(None, description="备注")


class ParamsUpdateRequest(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict, description="风控参数")


# ==================== 异常包装 ====================

def _raise(e: svc.PositionError):
    detail: Any = e.message
    if e.payload:
        detail = {'message': e.message, 'preview': e.payload}
    raise HTTPException(status_code=e.status_code, detail=detail)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.PositionError as e:
        _raise(e)


# ==================== 参数设置 ====================

@router.get("/settings")
def get_settings():
    """读取风控参数（含默认值与可调区间）"""
    return _call(svc.get_settings)


@router.put("/settings")
def update_settings(req: ParamsUpdateRequest):
    """保存风控参数"""
    return _call(svc.save_settings, req.params)


# ==================== 账户 ====================

@router.post("/accounts", status_code=201)
def create_account(req: AccountCreateRequest):
    """创建账户"""
    return _call(svc.create_account, req.account_name, req.initial_capital,
                 req.risk_ratio_per_trade)


@router.get("/accounts")
def list_accounts():
    """账户列表（含实时权益）"""
    return _call(svc.list_accounts)


@router.get("/accounts/{account_id}")
def get_account(account_id: str):
    """账户详情（含实时权益）"""
    return _call(svc.get_account, account_id)


@router.put("/accounts/{account_id}")
def update_account(account_id: str, req: AccountUpdateRequest):
    """修改账户 / 出入金"""
    return _call(svc.update_account, account_id, req.account_name,
                 req.risk_ratio_per_trade, req.capital_delta, req.is_disable, req.is_primary)


@router.delete("/accounts/{account_id}")
def delete_account(account_id: str,
                   force: bool = Query(False, description="True 时级联删除该账户下全部持仓")):
    """删除账户；force=true 时连同该账户全部持仓（含已平仓）一并删除"""
    _call(svc.delete_account, account_id, force)
    return {'success': True, 'account_id': account_id, 'force': force}


@router.get("/accounts/{account_id}/dashboard")
def get_dashboard(account_id: str):
    """账户级风控看板"""
    return _call(svc.get_dashboard, account_id)


# ==================== 建仓 / 平仓 ====================

@router.get("/bar")
def get_bar_info(
    code: str = Query(..., description="代码（个股/ETF）"),
    date: str = Query(..., description="日期 YYYYMMDD"),
):
    """查指定标的在某交易日的 OHLC（弹窗自动填充收盘价）"""
    return _call(svc.get_bar_info, code, date)


@router.post("/preview")
def preview_entry(req: EntryPreviewRequest):
    """建仓预览（不落库，实时返回 ATR/止损止盈/建议股数/风险校验）"""
    return _call(svc.preview_entry, req.account_id, req.stock_code, req.buy_date,
                 req.buy_price, req.buy_shares)


@router.post("", status_code=201)
def create_position(req: PositionCreateRequest):
    """建仓"""
    return _call(svc.create_position, req.account_id, req.stock_code, req.buy_date,
                 req.buy_price, req.buy_shares, req.force, req.note)


# ==================== 持仓 ====================

@router.get("")
def list_positions(
    account_id: Optional[str] = Query(None, description="账户 ID"),
    status: Optional[str] = Query(None, description="OPEN / CLOSED"),
    keyword: Optional[str] = Query(None, description="代码或名称关键词"),
):
    """持仓列表（含实时止损/盈亏/动作建议）"""
    return _call(svc.list_positions, account_id, status, keyword)


@router.post("/refresh")
def refresh_all(account_id: Optional[str] = Query(None, description="账户 ID，空=全部")):
    """重算持仓快照（手动刷新监控）"""
    return _call(svc.refresh_all, account_id)


@router.get("/alerts")
def get_alerts(account_id: Optional[str] = Query(None, description="账户 ID")):
    """持仓风控预警（止损触发 / 跳空止损 / 达到止盈参考）"""
    return _call(svc.get_risk_alerts, account_id)


@router.get("/{position_id}")
def get_position(position_id: str):
    """持仓详情（含 K 线标注数据）"""
    return _call(svc.get_position_detail, position_id)


@router.get("/{position_id}/trajectory")
def get_trajectory(position_id: str):
    """每日风控轨迹"""
    return _call(svc.get_trajectory, position_id)


@router.post("/{position_id}/sells/{sell_id}/revoke")
def revoke_sell(position_id: str, sell_id: str):
    """撤回一笔卖出记录（现金回滚、持仓恢复）"""
    return _call(svc.revoke_sell, position_id, sell_id)


@router.post("/{position_id}/close")
def close_position(position_id: str, req: PositionCloseRequest):
    """全平（把剩余股数一次性卖出）"""
    return _call(svc.close_position, position_id, req.sell_date, req.sell_price, req.note)


@router.post("/{position_id}/sell")
def sell_position(position_id: str, req: PositionSellRequest):
    """卖出（支持分批）：shares 留空表示全部卖出"""
    return _call(svc.sell_position, position_id, req.sell_date, req.sell_price,
                 req.shares, req.reason, req.note)


@router.post("/{position_id}/refresh")
def refresh_position(position_id: str):
    """重算单笔持仓快照"""
    return _call(svc.refresh_position, position_id)


@router.delete("/{position_id}")
def delete_position(position_id: str):
    """删除已平仓记录"""
    _call(svc.delete_position, position_id)
    return {'success': True, 'position_id': position_id}
