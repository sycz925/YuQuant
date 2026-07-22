"""
工厂基类 - 定义通用数据类和接口
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, List


@dataclass
class SyncResult:
    """同步结果"""
    success: bool = True
    message: str = ''
    total: int = 0
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComputeResult:
    """计算结果"""
    success: bool = True
    message: str = ''
    skipped: bool = False
    skip_reason: str = ''
    computed: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """流水线结果"""
    success: bool = True
    steps: Dict[str, Any] = field(default_factory=dict)
    
    def add_step(self, name: str, result: Any) -> None:
        """添加步骤结果"""
        self.steps[name] = result
        if hasattr(result, 'success') and not result.success:
            self.success = False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'success': self.success,
            'steps': {k: v.__dict__ if hasattr(v, '__dict__') else v for k, v in self.steps.items()}
        }


class ProgressCallback:
    """进度回调封装"""
    
    def __init__(self, callback: Optional[Callable] = None):
        self._callback = callback
        self._total = 0
    
    def __call__(self, current: int, total: int, message: str = '') -> None:
        if self._callback:
            self._callback(current, total, message)
        if total > 0:
            self._total = total
    
    def update(self, current: int, total: int, message: str = '') -> None:
        """更新进度"""
        self(current, total, message)
    
    def complete(self, message: str = '完成') -> None:
        """标记完成"""
        total = self._total if self._total > 0 else 1
        self(total, total, message)
