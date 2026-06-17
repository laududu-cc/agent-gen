# AgentForge (智戎) — 智能体生成平台

AgentForge 是一个低门槛的 AI 智能体生成平台。用户只需用自然语言描述自己的业务需求，系统即可通过大模型（LLM）自动推断、生成对应的 System Prompt，并搭建出一个专属的 AI 智能体，支持在线测试、对话式反馈与即时调优。

本项目采用 **前后端分离** 的设计架构，以 **Python (FastAPI)** 为核心后端服务。

---

## 📂 项目结构

*   `main.py`: 后端核心逻辑。使用 FastAPI 提供 RESTful API 接口，结合 SQLAlchemy + MySQL (PyMySQL) 管理多用户的智能体与会话数据，并在后端完成 JWT 认证签发及与 Casdoor 身份源密码模式的交互。
*   `requirements.txt`: Python 项目依赖项声明，包含 `fastapi`, `uvicorn`, `pymysql`, `cryptography` 等。
*   `download_libs.py`: 离线依赖下载脚本。可拉取 marked, highlight.js 等常用静态文件到本地，供局域网内网环境下脱离 CDN 运行。
*   `public/`: 前端静态网页资源，包括主页、对话测试页、登录页及智能体管理控制台。
*   `PRD.md`: 项目的原始及已更新的产品需求文档。

---

## ⚙️ 配置说明

后端的 API 和数据库配置可以直接在 `main.py` 中进行指定：

### 1. 大模型 (LLM) 接口配置
后端默认使用 DeepSeek 接口进行文本生成与流式响应：
```python
client = AsyncOpenAI(api_key="YOUR_DEEPSEEK_API_KEY", base_url="https://api.deepseek.com")
```

### 2. MySQL 数据库配置
本项目在虚拟机环境 `192.168.1.135` 上搭建了 MySQL 服务。后端通过如下连接串进行持久化管理：
```python
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://casdoor:casdoor_password@192.168.1.135:3306/casdoor"
```
启动时，SQLAlchemy 会自动检测并进行表结构迁移与字段创建。

### 3. Casdoor 内网极简身份源配置
后端通过与内网部署的 Casdoor 实例进行直接 API 交付来实现无需跳转、极简统一风格的登录和注册：
```python
CASDOOR_ENDPOINT = "http://192.168.1.135:8000"
CLIENT_ID = "be52450276ed83ab1c0e"
CLIENT_SECRET = "YOUR_CLIENT_SECRET" # 对应 app-built-in 的 Client Secret
```

---

## 🚀 启动与运行

项目支持以下两种部署/运行方式：

### 离线部署支持（可选）
如果您需要在完全隔离的纯局域网内网中部署本系统，可先在有网环境下运行下述命令，拉取所有前端第三方库到本地：
```bash
python download_libs.py
```
这将在 `public/lib/` 目录下生成本地依赖。前端页面（`index.html`，`test.html`）会自动从本地加载这些库，避免了加载外部 CDN 导致的超时或白屏。

### 方式 A：单体模式（后端托管静态文件，推荐）

启动 FastAPI 后端服务，后端会自动挂载并代理 `public/` 目录：

```bash
uvicorn main:app --reload
```

启动成功后，在浏览器中打开：
👉 **[http://127.0.0.1:8000/index.html](http://127.0.0.1:8000/index.html)**

### 方式 B：前后端完全分离模式

得益于后端的跨域中间件（CORS）以及前端对 `API_BASE` 的动态适配：
1. 运行后端服务：`uvicorn main:app --reload` (运行在 `http://127.0.0.1:8000`)。
2. 前端可以通过任何静态文件服务单独托管（如 VS Code 的 Live Server 运行在 `http://127.0.0.1:5500`），甚至可以直接在浏览器中**双击打开** `public/index.html`。
3. 前端会自动将 API 请求导向 `http://127.0.0.1:8000`。

