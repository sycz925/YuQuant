# 回测引擎功能文档

## 概述

回测引擎（BacktestEngine）模拟真实交易环境，包含 T+1 制度、涨跌停限制、交易费用、滑点和动态风控。

## 核心功能

### 1. 交易费用

- 佣金：万分之 3，最低 5 元
- 过户费：万分之 0.2（仅买入）
- 印花税：千分之 0.5（仅卖出）

```python
from app.backtest_engine import BacktestEngine

engine = BacktestEngine(dm, fe)
engine.set_commission(
    commission_rate=0.0003,
    min_commission=5.0,
    transfer_fee_rate=0.00002,
    stamp_duty_rate=0.0005
)
```

### 2. 风控设置

- 8% 绝对止损
- 8% 移动止盈
- CR5% > 40% 全局风控清仓

```python
engine.set_risk_control(
    stop_loss=0.08,
    take_profit=0.08,
    cr5_stop_threshold=40.0
)
```

### 3. 买入卖出

```python
# 买入（单位：手）
engine.buy("000001", 100, "策略信号")

# 卖出
engine.sell("000001", 100, "止盈")
```

### 4. 运行回测

```python
from app.backtest_engine import Strategy

class MyStrategy(Strategy):
    def on_bar(self, engine, trade_date):
        # 策略逻辑
        pass

engine.set_strategy(MyStrategy())
result = engine.run("20240101", "20241231")

print(f"总收益率: {result.total_return:.2%}")
print(f"最大回撤: {result.max_drawdown:.2%}")
```

### 5. 获取结果

```python
# 交易日志
trade_log = engine.get_trade_log()

# 资金曲线
equity_curve = engine.get_equity_curve()
```

## 交易规则

- T+1 制度：当日买入的股票当日无法卖出
- 涨跌停：涨停无法买入，跌停无法卖出
- 滑点：买入价格上浮，卖出价格下浮
