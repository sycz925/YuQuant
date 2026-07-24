# 环境配置指南

## 系统要求

- Python 3.8 或更高版本
- Node.js 16+
- **MongoDB 5.0+**
- 操作系统：macOS / Linux / Windows

## 安装步骤

### 1. 克隆项目并进入目录

```bash
cd YuQuant
```

### 2. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows
```

### 3. 安装后端依赖

```bash
pip install -r requirements.txt
```

### 4. 安装前端依赖

```bash
cd app/client && npm install
```

### 5. 环境配置

创建 `.env` 文件（或设置环境变量）：

```
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=yuquant
DEEPSEEK_API_KEY=your-key-here
```

### 6. 启动 MongoDB

```bash
# macOS (Homebrew)
brew services start mongodb-community

# 或使用 Docker
docker run -d -p 27017:27017 --name mongodb-yuquant mongo:latest
```

### 7. 启动应用

```bash
# 一键启动（后端 + 前端）
./start.sh

# 或分别启动
# 后端：uvicorn app.server.main:app --host 0.0.0.0 --port 8000 --reload
# 前端：cd app/client && npm run dev
```

- 后端 API：http://localhost:8000
- 前端页面：http://localhost:5173
- API 文档：http://localhost:8000/docs

## 验证安装

打开前端页面 http://localhost:5173，左侧导航栏出现市场监控、市场分析、个股分析等功能菜单即表示后端连接正常。

## 初始化数据

在 Settings 页面依次点击：
1. 同步指数 → 同步个股 → 同步板块 → 计算RPS → 同步PE → 同步基础数据

## 常见问题

### MongoDB 连接失败

- 确认 MongoDB 已启动：`mongosh` 或 `docker ps`
- 检查 `.env` 中的 MONGODB_URI 配置

### 前端启动失败

- 确认 Node.js >= 16
- 删除 `node_modules` 重新 `npm install`
