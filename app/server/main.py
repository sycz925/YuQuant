"""
FastAPI后端主入口
"""
import logging
import os
import sys
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.server.models import HealthResponse
from app.server.api import stocks, factors, backtest, sync, market_analysis, exclusions, market_review
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

# 创建FastAPI应用
app = FastAPI(
    title="A股量化回测系统",
    description="React + FastAPI分离架构的量化回测系统",
    version="1.0.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该配置具体的前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(stocks.router)
app.include_router(factors.router)
app.include_router(backtest.router)
app.include_router(sync.router)
app.include_router(market_analysis.router)
app.include_router(exclusions.router)
app.include_router(market_review.router)


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化缓存"""
    init_trade_dates()


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
        "message": "欢迎使用A股量化回测系统API",
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
