# 智能会议助手 (Meeting Copilot)

一个生产级的会议助手全栈应用：上传会议录音 → 外部 ASR 服务转写 → LLM 生成会议纪要 → 导出 Word 文档。

> **架构说明**：本项目**不内置 ASR 模型**。后端通过 HTTP 调用外部 ASR 服务（你已有的或第三方），具体接口见下方"ASR 服务契约"一节。

## 技术栈

- **后端**：FastAPI + SQLAlchemy 2.0 (async) + MySQL + MinIO
- **前端**：Vue 3 + Element Plus + Vite
- **ASR**：外部服务（HTTP），兼容 `/transcribe_upload/` 接口
- **LLM**：OpenAI 兼容协议（默认 Qwen3-32B）
- **导出**：pypandoc 转 Word

## 目录结构

```
meeting_copilot/
├── backend/          # FastAPI 后端
├── frontend/         # Vue 3 前端
├── docker/           # Docker 编排与镜像构建
└── meeting_summary_templates.json   # 会议纪要模板
```

## 快速开始

```bash
# 1. 进入 docker 目录
cd docker

# 2. 复制环境变量模板并填入实际值
cp .env.example .env
# 必须修改：DB_PASSWORD / OSS_ACCESS_KEY / OSS_SECRET_KEY / LLM_API_ENDPOINT / ASR_API_URL
# 生成凭据示例：
#   AUTH_SECRET=$(openssl rand -hex 32)
#   DEFAULT_ADMIN_PASSWORD=$(openssl rand -base64 12)

# 3. 启动整个栈（首次构建约 1-2 分钟）
docker compose -p meeting_copilot -f docker-compose-template.yml up -d --build
# （简写：可复制为 docker-compose.yml 后用 docker compose up -d --build）

# 4. 浏览器访问
# 前端：http://localhost:8888
# MinIO 控制台：http://localhost:9001
# API 文档：http://localhost:8000/docs
```

> **为什么固定用 `-p meeting_copilot`**：compose 默认用**目录名**当项目名，本项目目录恰好叫 `docker`，
> 会和同机器上 `/home/ubuntu/VoxAudit/docker` 的项目名撞车 —— 两者共用 `docker_mysql_data` /
> `docker_minio_data` 卷，导致 MySQL 数据目录被另一个项目占用、root 密码对不上而启动失败。
> 显式指定项目名后，卷名变成 `meeting_copilot_mysql_data` 等，与其它项目彻底隔离。
>
> 停栈：`docker compose -p meeting_copilot -f docker-compose-template.yml down`
> （加 `-v` 会连数据卷一起删掉，慎用）

## ASR 服务契约

后端只做 HTTP 客户端，调用外部 ASR 服务。约定的接口格式：

### `POST {ASR_API_URL}/transcribe_upload/`

请求：multipart/form-data，字段名 `upload_file`（与原 `asr_app.py` 完全一致）

响应 JSON：

```json
{
  "status": "success",
  "speaker_cnt": 2,
  "markdown": "# 对话记录\n\n**说话人0** `00:00 - 00:08`\n\n> 你好\n\n**说话人1** `00:08 - 00:15`\n\n> 你好呀",
  "segments": [
    {"speaker": 0, "text": "你好", "start": 0, "end": 8000},
    {"speaker": 1, "text": "你好呀", "start": 8000, "end": 15000}
  ]
}
```

### `GET {ASR_API_URL}/health`

健康检查，返回 `{"status": "ok", "model_loaded": true, ...}`。

### 配置方式

支持两种方式（前端"系统设置 → ASR 配置"在线修改实时生效，env 中只是默认值）：

```bash
# 方式 1：.env 中静态配置（部署期默认值）
ASR_API_URL=http://your-asr-host:6028
ASR_API_KEY=xxx          # 可选，会作为 Bearer Token 发送

# 方式 2：前端系统设置中在线改（写入数据库 system_settings，运行时覆盖 .env）
```

> **优先级**：数据库（前端在线改）优先于 `.env`（部署期默认值）。
> 在线修改后立即生效，无需重启。

### 关键配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_TIMEOUT` | `900` | 单次 LLM 请求超时（秒）。长会议纪要要吐上万 token，超时太短必然失败 |
| `LLM_MAX_RETRIES` | `2` | 单次 LLM 请求内部的失败重试次数（外层任务队列另有 3 次任务重试） |
| `ALLOW_INTERNAL_SERVICE_URLS` | `true` | 是否允许 LLM / ASR 指向内网地址。`true` 允许回环与 RFC1918、fc00::/7（ASR/LLM 常与后端同机同网段）；`false` 完全禁止内网地址。**链路本地（169.254/16，含云元数据）、非 http(s) 协议任何情况下都拒绝** |

> `ALLOW_INTERNAL_SERVICE_URLS` 是环境变量（不是数据库配置），改完需要重启后端。

## 权限说明

| 功能 | 权限 |
| --- | --- |
| 会议上传 / 转写 / 生成纪要 / 导出 Word | 登录用户 |
| 查看系统设置、查看模板列表 | 登录用户 |
| **修改** LLM / ASR 配置、**修改**全局会议纪要模板、测试连接 | **仅管理员** |
| 审计日志查询 / 导出 | **仅管理员** |

默认管理员由 `DEFAULT_ADMIN_USER` / `DEFAULT_ADMIN_PASSWORD` 首次启动自动创建，并强制首次登录改密。
需要把**已有账号**（含 OA 账号）提升为管理员：

```sql
UPDATE users SET is_admin = 1 WHERE loginid = 'your_account';
```

## 登录方式

### 本地账号（兼底）

`docker/.env` 里 `DEFAULT_ADMIN_USER` / `DEFAULT_ADMIN_PASSWORD` / `DEFAULT_ADMIN_NAME`
指定的管理员账号，走本地密码登录。**OA 出问题时用这个账号进系统**。

这三项是管理员登录信息的**唯一来源**：

| 时机 | 行为 |
| --- | --- |
| 首次启动（users 表为空） | 自动创建管理员，并标记「首次登录强制改密」 |
| 之后每次启动 | 库里的密码与 `.env` 不一致时，**按 `.env` 重置**，并打一条 WARNING 日志 |

所以运维改密码的流程是：**改 `docker/.env` 的 `DEFAULT_ADMIN_PASSWORD` → 重启后端** → 立即生效。

> ⚠️ 因为 `.env` 是权威来源，**管理员在界面上「修改密码」的结果会在下次重启时被 `.env` 覆盖**。
> 这是「凭据统一由部署配置管理」的刻意设计（避免密码只存在于数据库、无法审计与轮换）。
> 如果希望管理员自己掌握密码、且不被重启覆盖，请改用 OA 登录 —— OA 用户不走这条同步逻辑。

```sql
-- 把某个 OA 用户提权为管理员（OA 登录不会覆盖这个设置）
UPDATE users SET is_admin = 1 WHERE loginid = '工号';
```

### OA 账号

在 `docker/.env` 里配置 `OA_BASE_URL` 后启用：

```bash
OA_BASE_URL=http://oa.your-company.com:8000
OA_API_IDENTIFIER=meeting-copilot
OA_TIMEOUT=10
```

启用后的登录规则：

- **本地账号**（`auth_source='local'`）→ 本地 PBKDF2 密码校验
- **其余账号** → 密码转发到 OA `POST {OA_BASE_URL}/api/hrm/login/checkLogin` 校验，
  校验通过后从 `POST {OA_BASE_URL}/api/hrm/resful/getHrmUserInfoWithPage` 拉取员工信息
  （姓名 / 部门 / 岗位 / 分部 / 邮箱），**首次登录自动在本地 `users` 表建档**

设计要点：

- OA 只负责**认证 + 提供员工信息**，账号的本地建档与 `is_admin` 权限仍由本地 `users` 表管理，
  权限模型只有一处真相
- OA 用户**不存密码**（`password_hash` 为空），也不允许在本地改密（提示去 OA 改）
- OA 用户默认 `is_admin=0`；需要提权时由管理员在库里改（见上方 SQL），
  **OA 再次登录不会覆盖手动设置的 `is_admin`**
- `OA_BASE_URL` 留空 = 完全关闭 OA 登录，此时只有本地账号能登录

> 迁移已有账号：OA 首次登录会自动建档，但 `is_admin` 不会自动继承。若老系统里有管理员，
> 需要用上面的 SQL 逐个提权。


## 国内镜像加速（已默认开启）

`Dockerfile.backend` 和 `Dockerfile.frontend` 默认使用以下国内镜像源，无需额外配置：

| 类型 | 镜像 | 默认地址 |
| --- | --- | --- |
| apt | 腾讯云 Debian | `mirrors.cloud.tencent.com` |
| pip | 腾讯云 PyPI | `mirrors.cloud.tencent.com/pypi/simple` |
| HuggingFace | HF 镜像 | `hf-mirror.com` |
| npm | npmmirror | `registry.npmmirror.com` |

如需切换回默认源，在 `docker build` 时传入参数：

```bash
docker build \
  --build-arg APT_MIRROR=mirrors.tuna.tsinghua.edu.cn \
  --build-arg PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple \
  -f docker/Dockerfile.backend \
  -t meeting-copilot-backend:latest .
```

## 构建优化

后端 Dockerfile 做了以下分层缓存（轻量镜像，整体约 600MB）：

1. **apt 依赖**（gcc / libmariadb-dev / pandoc 等）
2. **pip 升级**（pip/setuptools/wheel）
3. **Python 依赖**（fastapi / sqlalchemy / minio / httpx / pypandoc 等）
4. **业务代码**（最频繁改动；位于最后，构建最快）

后续业务代码改动时，前 3 层全部命中缓存，仅重建最后一层（秒级）。

前端容器以**非 root 用户**（nginx，uid 101）运行。nginx 的 pid 文件与各类临时目录通过
`docker/nginx-main.conf` 放到 `/tmp`（官方镜像里这些路径是 root 属主的 `/run` 与
`/var/cache/nginx`，非 root 跑不起来）。宿主机暴露端口由 `FRONTEND_EXTERNAL_PORT` 决定，
容器内部仍监听 80。

## 功能模块

- **数据概览**：会议数量、已生成纪要、说话人统计
- **上传转写**：支持 wav / mp3 / mp4 / m4a / flac / ogg / webm / amr
- **会议管理**：列表 / 详情 / 删除 / 下载 Word
- **系统设置**：LLM 和 ASR 在线配置 + 测试连接

## 开发

后端开发：
```bash
cd backend
pip install -r requirements.txt
# 中国大陆用户追加：-i https://mirrors.cloud.tencent.com/pypi/simple
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

前端开发：
```bash
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
```

## License

Internal use only.