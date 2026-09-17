# StreamGet 录播台

基于 [streamget](https://github.com/ihmily/streamget) + FFmpeg 的多平台直播录播面板，前后端分离：

- **后端**（本目录）：Python / FastAPI / SQLite，负责开播轮询、流地址解析、FFmpeg 录制、实时推送
- **前端**（[panel/](panel/)）：Next.js（静态导出）+ Ant Design，由后端同进程托管，无需 Node 运行时

支持 streamget 全部 50+ 平台（抖音 / B站 / 虎牙 / 斗鱼 / 快手 / TikTok / Twitch / YouTube 等），另内置 `custom` 平台可直接录制 m3u8 / flv 直链。

## 架构

```
浏览器 (panel/ 静态导出 SPA)
   │  REST + WebSocket
FastAPI 单进程
   ├─ 轮询调度器：每房间独立异步任务，间隔抖动 + 指数退避
   ├─ RecorderManager → Recorder（每路录制）
   │     └─ FFmpeg 子进程（-c copy 不转码，'q' 优雅收尾）
   ├─ 事件总线 → WebSocket 实时推送状态/进度/日志
   └─ SQLite（SQLAlchemy 2.0 async, WAL）房间/录制记录 + JSON 文件（settings.json）运行时设置
streamget 解析流地址 │ FFmpeg 录制 │ Node.js（部分平台签名）
```

### 录制引擎的健壮性设计（核心）

- **地址永不过期**：每个分段结束后重新检测开播状态、重新解析流地址（直播流地址普遍几分钟内失效，绝不复用）
- **断流自动重连**：FFmpeg 异常退出 → 指数退避（上限可配）→ 重新解析 → 续录为新分段，同一直播归入同一录制会话
- **优雅停止**：向 FFmpeg stdin 发送 `q`，保证 MP4 moov box 完整写入；超时才强杀
- **无人值守恢复**：服务重启时自动清理"僵尸录制"状态并恢复轮询
- **防刷接口**：房间级轮询间隔 ±15% 抖动；检测失败指数退避；连续失败超限自动结束会话交还轮询

## 快速开始

### Windows 本机运行

1. 安装 [uv](https://docs.astral.sh/uv/)（Python 环境管理）、[FFmpeg](https://www.gyan.dev/ffmpeg/builds/)（加入 PATH）
2. 双击 `start.bat`，浏览器自动打开 `http://127.0.0.1:8000`

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

## 使用

1. **房间管理** → 添加直播间地址（自动识别平台；YouTube / 淘宝需填 Cookie，个别平台需 Cookie 时界面有提示）；支持批量启停、全部刷新（立即检测所有房间）；每个房间可**编辑**单独设置：清晰度、轮询间隔、Cookie、录制格式、音频格式、拉流协议、分段、单场时长、HTTPS/下载器直连、转 MP4/删原文件、时间字幕、录后脚本等（留空跟随全局，列表显示“覆盖N”标签）
2. 开播后自动录制，**仪表盘** 实时显示时长 / 大小 / 码率
3. **录制文件** → 资源管理器式文件夹浏览（面包屑导航、双击进入、跨目录搜索）、下载、删除
4. **设置** → 检测时间、下播确认延迟、清晰度（OD~LD、仅音频）、录制格式（MP4/FLV）、音频格式（自动/AAC/M4A/MP3）、拉流协议优先级（FLV/HLS）、保存路径模板/保存目录（占位符：platform/platform_name/anchor/title/remark/room_id/session_id/datetime/date/time/year/month/day/hour/minute/second/quality）；**网络与通知**：强制 HTTPS 录制、FLV 源下载器直连、代理、代理录制平台、Webhook 事件通知；**录制限制**：分段录制（开关+秒数）、单场最大时长、磁盘剩余阈值、连续失败上限、录制文件保留天数（自动清理）、全局/平台并发上限；**录制后处理**：转 MP4（可删原文件）、时间字幕文件、录后自定义脚本、FFmpeg 路径与额外参数；末行并排两卡片——**平台登录**（按平台配置 Cookie，房间未配时的兜底）与**关于与令牌**（访问令牌与版本信息）

## 配置

启动期环境变量（或 `recorder/.env`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `RECORDER_HOST` | `127.0.0.1` | 监听地址；Docker 内已设为 `0.0.0.0` |
| `RECORDER_PORT` | `8000` | 监听端口 |
| `RECORDER_DATA_DIR` | `data` | 数据库 / 录制 / 日志根目录 |
| `RECORDER_ACCESS_TOKEN` | 空 | 设置后所有 API 需携带令牌（页面会弹出输入框） |
| `RECORDER_LOG_LEVEL` | `INFO` | 日志级别 |

运行期设置在网页"设置"页修改，存于数据库，即时生效。

## 目录结构

```
recorder/
├── main.py               # FastAPI 入口：生命周期 + 路由 + panel 静态托管
├── app/
│   ├── config.py         # 启动配置（环境变量）
│   ├── db.py / models.py # SQLite + ORM（rooms / recording_sessions / recording_files）
│   ├── settings_service.py # 运行时设置（data/settings.json）
│   ├── platforms.py      # 平台注册表 + URL 自动识别 + custom 直链平台
│   └── api/              # rooms / recordings / settings / system / ws
│   └── core/
│       ├── monitor.py    # streamget 封装（检测 + 解析，含 B 站 live_status 兼容）
│       ├── scheduler.py  # 轮询调度器
│       ├── recorder.py   # FFmpeg 子进程管理 + 断流重连 + 分段
│       ├── manager.py    # 录制注册表 / 并发去重 / 全局停止
│       └── events.py     # 事件总线（WS 推送源）
├── panel/                # Next.js 前端（npx create-next-app 生成，静态导出）
├── scripts/dev_record_test.py
├── Dockerfile / docker-compose.yml / start.bat
└── data/                 # 运行时数据（git 忽略）：数据库、录制文件、日志
```

## 已知边界（v2 预留）

- 弹幕录制、开播/异常消息通知（事件总线已预留，加订阅者即可）
- Web 内实时预览、磁盘自动清理策略
- 已被官方声明停更的平台（千度热播 / WinkTV / 音播 / VV星球 / 飘飘 / 咪咕）可用性不保证
- 部分平台签名依赖 Node.js（Docker 镜像已内置；Windows 若录制抖音/斗鱼报错，运行 `uv run streamget install-node` 或安装 Node.js）
