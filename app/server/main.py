"""
FastAPI后端主入口
"""
# 加载 .env 环境变量（必须在其他导入之前）
from dotenv import load_dotenv
import os
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_project_root, '.env'))

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.server.config import get_settings
from app.server.models import HealthResponse
from app.server.api import stocks, factors, sync, market_analysis, market_review, screenshot, calendar, search, etf, alert
from app.server.api import one_click_update_v2 as one_click_update
from app.server.api import settings_tasks
from app.server.api import watchlist
from app.server.cache import init_trade_dates, get_latest_trade_date

# 配置日志 - 输出到 logs/ 目录
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'server.log')

# 配置根日志
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# 文件处理器
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
root_logger.addHandler(file_handler)

# 控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

# 全局引用，防止被GC
_alert_scheduler_thread = None


def _start_alert_scheduler():
    """启动ENE预警定时器（每5分钟）"""
    import threading
    import time
    from app.engine.ene_alert import check_latest, backfill_alerts, backfill_cross_alerts

    # 首次启动时回刷历史
    logger.info("[ENE预警] 首次启动，回刷历史数据...")
    try:
        backfill_alerts()
        backfill_cross_alerts(max_dates=10)
    except Exception as e:
        logger.error(f"[ENE预警] 回刷失败: {e}")

    def _loop():
        logger.info("[ENE预警] 定时器已启动，每5分钟检查最新数据")
        while True:
            try:
                now = datetime.now()
                hour = now.hour
                if 9 <= hour <= 15:
                    check_latest(max_dates=5)
                else:
                    logger.debug("[ENE预警] 非交易时间，跳过检查")
            except Exception as e:
                logger.error(f"[ENE预警] 检查失败: {e}")
            time.sleep(300)

    global _alert_scheduler_thread
    _alert_scheduler_thread = threading.Thread(target=_loop, daemon=True)
    _alert_scheduler_thread.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("应用启动中...")
    init_trade_dates()
    _start_alert_scheduler()
    logger.info("应用启动完成")
    yield
    # 关闭时
    logger.info("应用关闭中...")


# 创建FastAPI应用
settings = get_settings()
app = FastAPI(
    title="A股量化系统",
    description="React + FastAPI分离架构的量化系统",
    version="1.0.0",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 参数校验异常处理器
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数校验失败 - 返回 422 与可读的字段错误（不泄露内部信息）"""
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "参数校验失败",
            "detail": exc.errors(),
        }
    )


# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理 - 统一错误响应格式（生产环境不泄露内部细节）"""
    logger.error("未处理的异常", exc_info=True)
    detail = str(exc) if settings.DEBUG else "服务器内部错误"
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "服务器内部错误",
            "detail": detail,
        }
    )


# 注册路由
app.include_router(stocks.router)
app.include_router(factors.router)
app.include_router(sync.router)
app.include_router(market_analysis.router)
app.include_router(market_review.router)
app.include_router(screenshot.router)
app.include_router(calendar.router)
app.include_router(search.router)
app.include_router(one_click_update.router)
app.include_router(settings_tasks.router)
app.include_router(etf.router)
app.include_router(alert.router)
app.include_router(watchlist.router)


@app.get("/health", response_model=HealthResponse)
@app.get("/api/health", response_model=HealthResponse)
def health_check():
    """健康检查"""
    # 直接从内存缓存获取最新交易日
    latest_trade_date = get_latest_trade_date()
    
    return HealthResponse(
        status="ok",
        timestamp=datetime.now().isoformat(),
        version="1.0.0",
        latest_trade_date=latest_trade_date
    )


@app.get("/")
def root():
    """根路由"""
    return {
        "message": "欢迎使用A股量化系统API",
        "docs": "/docs",
        "redoc": "/redoc"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
