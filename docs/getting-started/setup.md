# 环境配置指南

## 系统要求

- Python 3.8 或更高版本
- 操作系统：Windows / macOS / Linux

## 安装步骤

### 1. 克隆或下载项目

```bash
cd YuQuant
```

### 2. 创建虚拟环境（推荐）

```bash
# 使用 conda
conda create -n yuquant python=3.9
conda activate yuquant

# 或使用 venv
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 运行应用

```bash
streamlit run app/app.py
```

浏览器会自动打开 http://localhost:8501

## 验证安装

访问应用后，点击「🔄 同步最新数据」验证数据获取功能正常工作。

## 常见问题

### 问题1：AkShare 数据获取失败

- 检查网络连接
- 尝试更新 AkShare：`pip install --upgrade akshare`

### 问题2：数据库权限错误

- 确保有 data 目录的写权限
- 手动创建 data/sqlite 和 data/hdf5 目录
