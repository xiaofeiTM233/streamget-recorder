# StreamGet Recorder | 录播台

多平台直播录播面板，提供开播自动录制、断流重连、文件管理与网页面板，开箱即用，支持全部 50+ 平台（抖音 / B站 / 虎牙 / 斗鱼 / 快手 / TikTok / Twitch / YouTube 等），另内置 `custom` 平台可直接录制 m3u8 / flv 直链。前后端分离：

- **后端**（本目录）：基于 [Python](https://www.python.org/) / [FastAPI](https://fastapi.tiangolo.com/) / [streamget](https://github.com/ihmily/streamget) / [FFmpeg](https://ffmpeg.org/) 打造，负责开播轮询、流地址解析、录制与断流重连、WebSocket 实时推送；JSON 文件存储，零数据库依赖
- **前端**（[panel/](panel/)）：基于 [Next.js](https://nextjs.org/)（静态导出）/ [Ant Design](https://ant.design/) 打造的四页面面板，由后端同进程托管，无需 Node 运行时

## ✨ 核心特性

- 📡 **多平台监控**：粘贴直播间地址自动识别平台，轮询检测带 ±15% 抖动与指数退避防刷接口；下播确认延迟防瞬时断流误收场，手动检测与轮询行为完全一致
- 🔴 **开播自动录制**：FFmpeg `-c copy` 直拉不转码，CPU 占用极低；每分段结束后重新解析流地址绝不复用，向 stdin 发 `q` 优雅收尾保证文件完整可播
- 🔄 **断流自动重连**：异常退出 → 指数退避（上限可配）→ 重新解析 → 续录为新分段，同一直播归入同一录制会话；服务重启自动清理僵尸状态恢复轮询
- ✂️ **灵活录制控制**：分段时长、单场最大时长、清晰度（原画~仅音频）、录制格式（MP4/FLV）、音频格式（自动/AAC/M4A/MP3）、拉流协议（FLV/HLS）
- 🗂️ **房间级覆盖**：13 项设置可按房间单独覆盖（格式 / 分段 / 后处理等），留空跟随全局，列表显示"覆盖N"标签；支持批量启停与全部检测
- 📂 **文件管理**：录制历史直接扫描磁盘生成，资源管理器式浏览（面包屑 / 跨目录搜索）、下载、删除移入系统回收站；正在录制的文件受保护，保留天数自动清理
- 🎞️ **录制后处理**：FLV 录完自动转 MP4（可删原文件）、生成每秒一条的时间字幕（SRT）、录后自定义脚本（占位符 `{file}` `{filename}` `{title}` 等，600 秒超时保护）
- 🌐 **网络控制**：全局代理用于检测/解析，按平台单独开启拉流代理；强制 HTTPS 录制；FLV 源可切换下载器直连（httpx 低延迟）
- 🔒 **并发与限制**：全局 / 平台级并发上限（满员标记"等待空位"自动重试）、磁盘剩余阈值暂停录制、连续失败上限
- 🔔 **事件通知**：录制会话开始 / 结束时 Webhook POST JSON 回调
- 🔐 **安全鉴权**：可选访问令牌覆盖 REST + WebSocket（面板登录界面填写）；文件接口防路径遍历
- 💻 **开箱即用**：JSON 文件存储零数据库依赖，面板由后端同进程托管，支持 Windows 双击运行 / 单文件 exe / Docker 部署

## 🛠️ 技术栈

- **语言**: [Python](https://www.python.org/) / TypeScript
- **后端**: [FastAPI](https://fastapi.tiangolo.com/) + [streamget](https://github.com/ihmily/streamget) + [FFmpeg](https://ffmpeg.org/)（部分平台签名需 Node.js）
- **前端**: Next.js（静态导出）+ [Ant Design](https://ant.design/)，由后端同进程托管
- **存储**: JSON 文件存储（`store.json` 仅存房间、`settings.json` 存设置，临时文件 + 原子替换）
- **实时**: WebSocket 事件总线推送状态 / 进度 / 日志
- **打包**: PyInstaller 单文件 exe / Docker

## ⚙️ 使用说明

- **仪表盘**：实时查看每路录制的时长 / 大小 / 码率，磁盘占用与文件数统计
- **房间管理**：添加直播间地址 → 批量启停、立即检测；每个房间可编辑覆盖设置、单独填 Cookie
- **录制文件**：文件夹式浏览、双击进入、跨目录搜索，支持下载与删除（移入回收站）
- **设置**：分组卡片布局——常规录制 / 网络与通知 / 录制限制 / 录制后处理 / 平台登录 / 关于与令牌；开关下拉即时保存，文本数字失焦保存

## 🚀 快速开始

### Windows 本机运行

1. 安装 [uv](https://docs.astral.sh/uv/)、[FFmpeg](https://www.gyan.dev/ffmpeg/builds/)（加入 PATH）
2. 双击 `start.bat`，浏览器自动打开 `http://127.0.0.1:8000`

### 单文件 exe

```bat
build_exe.bat
```

生成 `dist\StreamGetRecorder.exe`，双击即用（前端已内嵌）。数据目录锚定在 exe 同级 `data/`，换电脑只需带走 exe 和 `data/`；Node.js 可装系统版或放 exe 同目录 `node/` 文件夹。

### Docker（服务器 / NAS）

```bash
docker compose up -d
# 浏览器访问 http://<主机IP>:8000
```

### 开发模式

```bash
# 后端（recorder/ 目录）
uv sync
uv run python main.py            # http://127.0.0.1:8000

# 前端热更新（panel/ 目录，代理 /api 到 8000）
npm install
npm run dev                      # http://localhost:3000

# 前端改动后重新构建静态产物
npm run build                    # 产物输出到 panel/out，由 FastAPI 托管
```

### 验证录制引擎（无需真实直播间）

```bash
uv run python scripts/dev_record_test.py   # 用公开测试流完整跑一遍录制/停止/落库
```

## ⚙️ 配置

### 启动期环境变量（或 `recorder/.env`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `RECORDER_HOST` | `127.0.0.1` | 监听地址；Docker 内已设为 `0.0.0.0` |
| `RECORDER_PORT` | `8000` | 监听端口 |
| `RECORDER_DATA_DIR` | `data` | 数据文件 / 录制 / 日志根目录 |
| `RECORDER_LOG_LEVEL` | `INFO` | 日志级别 |

### 运行期设置

在网页"设置"页修改，存于 `data/settings.json`，即时生效。按功能分组，完整键值见 [app/settings_service.py](app/settings_service.py) 的 `DEFAULTS`：

- **常规录制**：检测时间、下播确认延迟、清晰度、录制 / 音频格式、拉流协议、保存路径模板（17 个占位符：`platform` `platform_name` `anchor` `title` `remark` `room_id` `session_id` `datetime` `date` `time` `year`~`second` `quality`，时间为本地时间）与保存目录
- **网络与通知**：全局代理、代理录制平台、强制 HTTPS、FLV 下载器直连、Webhook 地址
- **录制限制**：分段（开关 + 秒数）、单场时长、磁盘阈值、连续失败上限、保留天数、并发上限
- **录制后处理**：转 MP4 与删原文件、时间字幕、录后脚本、FFmpeg 路径与额外参数
- **平台登录**：按平台配置兜底 Cookie（输入新值更新、留空保持、可删除）
- **关于与令牌**：访问令牌（留空不启用鉴权）与版本信息

## 📚 说明

本 README 文档由 AI 辅助生成。如有问题，请提交 Issue 或[与我联系](https://github.com/xiaofeiTM233)！
