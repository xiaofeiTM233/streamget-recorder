# 面板添加登录界面（连接地址：端口 + 令牌，参考 ENAL-rs）

## Context

参照 ENAL-rs：面板打开后先显示**登录/连接界面**，填写「服务端地址（含端口）+ 访问令牌」连接后端，
连接信息存 localStorage，之后所有请求以 `${baseUrl}${path}` 发出。这样面板不再绑死同源托管。

后端已具备条件（CORS `allow_origins=["*"]`、可选 `access_token` 鉴权、`/` 仍托管静态面板），
**后端零改动**，只改 `panel/`。

## 改动清单（全部在 panel/）

### 1. 新建 `src/components/ConnectForm.tsx` — 登录界面（移植 ENAL 同名组件，适配暗色主题）
- 字段：**连接地址**（预填 `window.location.origin`，必填、URL 格式校验，如 `http://127.0.0.1:8000`）、
  **访问令牌**（可选；服务端启用 `RECORDER_ACCESS_TOKEN` 时必填）、记住令牌、自动连接
- 登录校验：GET `${base}/api/summary`，成功进入面板；失败在表单下方显示原因
- 「清除已保存配置」链接

### 2. 新建 `src/lib/connection.tsx` — 连接状态管理（移植 ENAL `connection.tsx` + `storage.ts`）
- localStorage 键 `recorder_panel.connection`：`{baseUrl, token, remember, autoConnect}`；
  `remember=false` 时不持久化 token；首次加载迁移旧 `recorder_token` 键
- `ConnectionProvider` / `useConnection()`：connected / connecting / connect / disconnect / logout
- 监听 api.ts 401 派发的 `recorder:unauthorized` → 自动登出回登录页（保留地址、清空令牌）
- 自动连接：勾选记住+自动连接时，刷新页面静默重连（只尝试一次）

### 3. 修改 `src/lib/api.ts` — 请求跟随连接地址
- 模块级 `apiBase` / `apiToken`（SSR 守卫，初始从 localStorage 同步读）
- 导出 `setApiCredentials()`、`getApiBase()`、`getApiToken()`、`normalizeBaseUrl()`
- `api()` 改为 `fetch(`${apiBase}${path}`)`，401 派发逻辑保留；新增 `validateConnection()`
- 所有 useQuery/useMutation 钩子签名不变

### 4. 修改 `src/lib/events.tsx` — WebSocket 跟随连接地址
- `wsUrl()`：`getApiBase()` 空 → 同源；非空 → `http(s)→ws(s)` 转换 + `/ws`；token 用 `getApiToken()`
- EventProvider 在连接成功后才挂载（登录后才建连，登出即断开）

### 5. 新建 `src/components/ConnectionGate.tsx` — 挂载门卫
- 未连接 → `<ConnectForm />`（自动连接尝试中显示骨架防闪烁）；已连接 → `<AppShell>{children}</AppShell>`
- `src/app/layout.tsx` 里 `<AppShell>` 外包一层

### 6. 修改 `src/components/AppShell.tsx`
- Header 右侧显示当前连接地址 Tag + 「断开」图标按钮（参考 ENAL Panel.tsx）
- 删除原"需要访问令牌" Modal（令牌改由登录界面管理）

### 7. 配套小改
- `src/app/recordings/page.tsx`：下载链接 `${getApiBase()}${row.download_url}${tokenQs}`
- `src/app/settings/page.tsx`：「关于与令牌」卡删除令牌表单（登录界面已统一管理），保留版本信息

## 复用参考
- ENAL-rs：`panel/app/lib/connection.tsx`、`storage.ts`、`components/ConnectForm.tsx`、`Panel.tsx`
- 本项目现有：`api.ts` 401 派发机制、Providers.tsx 包裹顺序不变

## 验证
1. `cd panel && npm run build` 静态导出通过
2. `python main.py` 启动，开 `http://127.0.0.1:8000` → 显示登录页（地址已预填）→ 连接进入面板
3. 错误令牌 → 登录页报错；连接中后端改令牌 → 401 自动回登录页
4. 勾选记住+自动连接 → 刷新自动重连；「断开」→ 回登录页
5. 仪表盘实时状态（WS）、录制文件下载正常；面板部署到其他地址时填后端 `host:port` 可跨源访问
