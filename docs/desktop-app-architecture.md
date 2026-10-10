# Cline 桌面端前端布局与后端架构

> 基于 `apps/examples/desktop-app` 目录的实际结构整理，覆盖桌面端前端布局、架构分层、依赖与源码位置。

---

## 1. 概览

Cline 是一个开源的 AI 编码 Agent，支持在 **IDE、终端、桌面、SDK** 多个入口运行。它共用一套 **Agent 核心引擎**，桌面端是其中“本地应用”形态的代表。

`apps/examples/desktop-app` 是桌面端的示例实现，采用 **Tauri（Rust 壳）+ Bun sidecar（后端）+ Next.js（Web 视图）** 的三层架构。

---

## 2. 仓库结构

仓库根目录使用 **bun 工作空间单体仓库**：

```text
cline/
├── package.json                    # 根 workspace 配置
├── sdk/
│   └── packages/
│       ├── agents/                 # Agent 循环（无运行时依赖）
│       ├── core/                   # 编排层（ClineCore、RuntimeHost、默认工具）
│       ├── llms/                   # 模型网关 / 提供商目录
│       ├── shared/                 # 共享类型（AgentTool 等）
│       └── ui/                     # UI 组件
└── apps/
    └── examples/
        └── desktop-app/            # 桌面端示例
            ├── src-tauri/          # Rust / Tauri 后端
            ├── sidecar/            # Bun 后端（Agent 引擎宿主）
            ├── webview/            # Next.js 前端
            └── scripts/            # 构建与打包脚本
```

---

## 3. SDK 核心包


---

## 4. 桌面端整体架构

桌面端分三层通信：

```text
┌──────────────────────────────────────────────────────────────┐
│  Next.js UI (webview)                                        │
│  - 聊天、设置、模型、插件、市场、会话面板                     │
│  → desktop-client.ts 调用本地 rpc 接口                        │
└──────────────────────────────┬─────────────────────────────┘
                               │ IPC / loopback
┌──────────────────────────────▼─────────────────────────────┐
│  Tauri / Rust 桌面壳 (src-tauri)                            │
│  - 窗口、托盘、通知、插件、升级、安装器                        │
│  - 桥接 WebView 与 sidecar                                  │
└──────────────────────────────┬─────────────────────────────┘
                               │ local socket / IPC
┌──────────────────────────────▼─────────────────────────────┐
│  Bun sidecar 后端（编译成 code-sidecar-<triple> 单文件二进制）│
│  - 会话管理器、Agent run、工具执行                            │
│  - Web 搜索、connector、Plugin、MCP、插件市场                 │
│  - 依赖 @cline/core 运行业务逻辑                              │
└──────────────────────────────┬─────────────────────────────┘
                               │ SDK
┌──────────────────────────────▼─────────────────────────────┐
│  SDK (sdk/packages)                                         │
│  @cline/core / @cline/agents / @cline/llms / @cline/shared  │
└────────────────────────────────────────────────────────────┘
```

---

## 5. 前端文件结构

```text
webview/
├── app/
│   ├── layout.tsx          # 根布局：html/body、Bootstrap 脚本、NativeShell、Toaster
│   ├── page.tsx            # 主页面：聊天壳 + 各视图动态加载
│   └── api/
│       ├── changelog/route.ts
│       └── marketplace/catalog/route.ts
├── components/
│   ├── views/
│   │   ├── chat/           # 聊天界面
│   │   ├── sessions/       # 会话历史
│   │   ├── settings/       # 设置
│   │   ├── onboarding/     # 新手引导
│   │   └── marketplace/    # MCP/插件市场
│   ├── agent-sidebar.tsx           # 左侧会话侧边栏
│   ├── agent-header.tsx            # 顶部 Header
│   ├── session-command-bar.tsx     # 底部命令栏
│   ├── native-shell.tsx            # 原生壳集成
│   ├── window-title-bar.tsx        # 窗口标题栏
│   ├── desktop-error-telemetry.tsx
│   └── ui/                         # shadcn/ui 组件
├── contexts/           # 全局上下文（Account、Workspace）
├── hooks/              # 业务钩子
│   ├── use-chat-session.ts         # 核心：会话全生命周期
│   ├── use-session-history.ts
│   ├── use-session-agents.ts
│   ├── use-prompt-draft.ts


---

## 6. 主页面布局（app/page.tsx）

`app/page.tsx` 是核心聊天壳，采用 **左右侧边栏 + 顶部 Header + 底部命令栏** 的结构。

### 6.1 关键组件

```tsx
import {
  AgentHeader,
  AgentSidebar,
  SessionCommandBar,
  WindowTitleBar,
  WindowTitleBarContent,
  WindowTitleBarProvider,
  Sidebar,
  SidebarInset,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { ChatInputBar } from "@/components/views/chat/chat-input-bar";
import { ChatMessages } from "@/components/views/chat/chat-messages";
import { EnvironmentSelector } from "@/components/views/chat/environment-selector";
import { RemoteDirectoryPicker } from "@/components/views/chat/remote-directory-picker";
import { WelcomeScreen } from "@/components/views/chat/welcome-chat";
```

### 6.2 布局骨架

```tsx
<WorkspaceProvider value={...}>
  <AttachmentDropZone className="grid h-full min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto]">
    {!isWelcomeState ? (
      <WindowTitleBarContent>
        <AgentHeader />                    {/* 顶部标题栏 */}
        <SidebarProvider>
          <Sidebar>
            <AgentSidebar />               {/* 左侧侧边栏 */}
          </Sidebar>
          <SidebarInset>
            <div className="flex h-full flex-col">
              <SessionCommandBar />        {/* 底部命令栏 */}
              <ChatMessages />             {/* 消息区（滚动区域） */}
            </div>
          </SidebarInset>
        </SidebarProvider>
      </WindowTitleBarContent>
    ) : (
      <WelcomeScreen />                  {/* 新手引导页 */}
    )}
  </AttachmentDropZone>
</WorkspaceProvider>
```

### 6.3 视图

| 视图 | 文件 | 职责 |
|---|---|---|
| 聊天 | `components/views/chat/` | 消息列表、输入栏、Diff 视图、环境选择、远程目录选择、欢迎页 |
| 会话历史 | `components/views/sessions/` | 历史会话列表、切换、删除、重命名、导出 |
| 设置 | `components/views/settings/` | General/Providers/Voice/Channels/Schedules/Import/Remote/Account/About/Customize 系列 |
| 启动引导 | `components/views/onboarding/` | 登录、工作区选择、模型选择、提供商设置 |
| 市场 | `components/views/marketplace/` | MCP/插件市场浏览 |

---

## 7. 核心组件职责

### 7.1 `NativeShell`

桌面端与 Tauri 的“桥头”：

- 与 Tauri 桌面壳通信
- 管理原生标题栏、窗口最小化/最大化/关闭
- 处理系统托盘、通知等
- 让 Next.js 应用跑在 Tauri 的 WebView 里

### 7.2 `WindowTitleBar` / `WindowTitleBarContent` / `WindowTitleBarProvider`

- `WindowTitleBar`：标题栏容器
- `WindowTitleBarContent`：标题栏内容包装
- `WindowTitleBarProvider`：提供标题栏状态/行为上下文

> 页面注释说明：Tauri 窗口需要 `dragDropEnabled: false`，避免原生壳拦截 OS 文件拖拽。

### 7.3 `AgentHeader`

顶部标题栏：

- Logo / 左上角
- 会话标题、状态
- 操作按钮（保存、恢复检查点、分支、模型、模式切换等）

### 7.4 `AgentSidebar`



---

## 8. 后端文件结构

### 8.1 `src-tauri`（Rust / Tauri）

```text
src-tauri/
├── Cargo.toml                         # Rust 依赖（tauri 2.x、通知插件等）
├── tauri.conf.json                    # Tauri 配置
├── capabilities/
│   └── default.json
└── src/
    ├── main.rs                        # 应用入口、主窗口、插件
    ├── linux_webview.rs
    └── macos_notification.rs
```

主要依赖：

```toml
[dependencies]
tauri = { version = "2.11.1", features = ["image-png", "tray-icon"] }
tauri-plugin-notification = "2"
tauri-plugin-single-instance = "2"
tauri-plugin-updater = "2"
rfd = { version = "0.15", features = ["gtk3"] }
```

### 8.2 `sidecar`（Bun 后端）

桌面端真正“跑 Agent”的地方。

```text
sidecar/
├── index.ts                          # 入口：启动服务器、初始化会话管理器
├── server.ts                         # 暴露本地 API
├── chat-session.ts                   # 会话/会话状态
├── client-context.ts
├── connectors.ts / marketplace.ts
├── plugins.ts
├── observability.ts
├── telemetry-selfcheck.ts
├── types.ts
└── session-data/                     # 会话数据相关
```

入口 `main()` 流程简述：

1. 校验运行环境（只能用 Bun 运行）
2. 解析工作区根路径
3. 配置连接器、可观测性
4. 创建 sidecar 上下文
5. 启动服务，等待客户端请求

### 8.3 `scripts`（构建与打包）

| 脚本 | 作用 |
|---|---|
| `build-sidecar-bin.ts` | 交叉编译 sidecar 二进制，支持多目标平台 |
| `package-desktop.ts` | 打包桌面应用 |
| `dev-headless.ts` | 开发头部模式 |
| `generate-update-manifest.ts` | 生成更新清单 |
| `windows-installer.test.ts` | 窗口安装器测试 |

---

## 9. 桌面端构建链路

```text
bun run build:sdk                      # 先构建 SDK 包
bun run build:sidecar:bin              # 编译 sidecar 二进制
bun run build:web                      # 构建 Next.js webview
bun run build                          # bun.mts：先建 sidecar 再建 web
bun run dev                            # tauri dev（开发模式）
bun run build:binary                   # tauri build（发布二进制）
bun run package:desktop:<os>           # 打包安装文件
```

---

## 10. 前后端通信

### 10.1 前端调用后端

`lib/desktop-client.ts` 是 UI 到桌面后端的 **IPC/本地 RPC 客户端**。

它负责：

- 发送命令：发送消息、切换模型、切换模式、获取会话列表、更新设置等
- 接收后端推送：消息流、工具审批、会话状态变化、通知、托盘状态
- 窗口标题、通知、系统托盘状态同步

### 10.2 后端调用引擎

`sidecar/index.ts` 通过 `@cline/core` 调用 Agent 引擎：

- `createClineTelemetryServiceConfig`
- `ensureLoginShellPath`
- `createSidecarContext`
- `initializeSessionManager`
- `startServer`
- `buildTelemetrySelfcheckReport`

---

## 11. 状态管理

| 位置 | 作用 |
|---|---|
| `contexts/account-context.tsx` | 账号/登录状态 |
| `contexts/workspace-context.tsx` | 工作区上下文 |
| `lib/desktop-app-state.ts` | 桌面端全局状态 reducer（`createDesktopAppState` / `desktopAppReducer`） |
| `hooks/use-chat-session.ts` | 核心会话状态：连接、模型、工具审批、消息流、模式切换 |
| `lib/desktop-client.ts` | 外部与桌面后端通信的客户端层 |

---

## 12. 依赖说明

### 12.1 桌面端依赖的外部内容

| 依赖 | 说明 |
|---|---|
| `@cline/core` / `@cline/llms` / `@cline/shared` / `@cline/ui` | `workspace:*`，指向根 SDK 包，必须先 `bun run build:sdk` |
| `@tauri-apps/api` / `tauri-plugin-*` | Rust 桌面壳所需 |
| `next` / `react` / `react-dom` | 前端 UI 框架 |
| Bun | 运行 sidecar、编译 sidecar binary |
| Rust toolchain | 编译 `src-tauri` |
| Node.js | 配合 TypeScript / 工具链 |

### 12.2 不闭环

`apps/examples/desktop-app` **不是孤立闭环**。它需要：

1. SDK 包（必须先构建）；
2. Tauri/Rust 工具链；
3. Bun；
4. Next.js。

它是一个 **“UI 壳 + Rust 宿主 + Bun sidecar + SDK 引擎”** 的完整链条。

---

## 13. 前端布局总结

桌面端前端的典型布局是一条垂直线，和三条横向区域：

```text
┌──────────────────────────────────────────────────────────────┐
│ WindowTitleBar（原生标题栏/窗口控件）                         │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ AgentHeader（会话标题、状态、操作按钮）                    │ │
│ │ ┌──────────────────────────────────────────────────────┐ │ │
│ │ │ AgentSidebar（会话列表 / 计划任务 / 市场 / 设置）     │ │ │
│ │ │                              ┌─────────────────────┼─┤ │ │
│ │ │                              │ 内容区              │ │ │
│ │ │                              │ 聊天/会话/设置内容   │ │ │
│ │ │                              └─────────────────────┼─┤ │ │
│ │ │  SessionCommandBar（附件、模型、模式、发送按钮）      │ │ │
│ │ └──────────────────────────────────────────────────────┘ │ │
│ └──────────────────────────────────────────────────────────┘ │
│ <ChatInputBar />（提交输入框）                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 14. 参考路径

| 资源 | 路径 |
|---|---|
| 桌面端示例 | `apps/examples/desktop-app/` |
| 前端主页面 | `apps/examples/desktop-app/webview/app/page.tsx` |
| 根布局 | `apps/examples/desktop-app/webview/app/layout.tsx` |
| 桌面壳 | `apps/examples/desktop-app/src-tauri/` |
| Bun sidecar | `apps/examples/desktop-app/sidecar/` |
| 构建脚本 | `apps/examples/desktop-app/scripts/` |
| SDK 核心包 | `sdk/packages/` |

---

## 15. 进一步阅读建议

- 想看会话侧边栏的展开/折叠逻辑：`components/agent-sidebar.tsx`
- 想看消息流如何接入：`components/views/chat/chat-messages.tsx`
- 想看启动与会话生命周期：`sidecar/index.ts`、`hooks/use-chat-session.ts`
- 想看 SDK 编排层：`sdk/packages/core/`
- 想看壳层：`src-tauri/src/main.rs`

左侧侧边栏，包含：

| 区域 | 内容 |
|---|---|
| 会话列表 | 历史会话、当前会话、运行中会话 |
| 计划任务 | 调度会话 |
| 市场 | MCP 市场、插件市场 |
| 设置导航 | General / Providers / Voice / Channels / Schedules / Import / Remote / Account / About / Customize / Marketplace |

有 **展开/折叠** 态；折叠后仍保留可点击行，保持可达性。

### 7.5 `SessionCommandBar`

底部命令栏：

- 输入框（`ChatInputBar`）
- 附件（图片、文件、Git 分支）
- 模型、执行目标（本地/云）
- 模式切换（Plan/Act）
- 发送按钮
- 队列、审批中提示

### 7.6 `ChatMessages`

消息内容区：

- 系统消息（assistant、user、tool 输出）
- 图片附件
- Diff 视图
- 检查点、分叉会话
- 云端会话专用控件

│   ├── use-app-update.ts
│   └── ...
└── lib/                # 工具库
    ├── desktop-client.ts             # ↔ 桌面后端 IPC 客户端
    ├── desktop-app-state.ts          # 全局状态 reducer
    ├── theme.ts / workspace-paths.ts
    └── ...
```


桌面端依赖仓库里的 SDK 包（`workspace:*`），必须先构建：

```bash
bun run build:sdk
```

| 包 | 职责 |
|---|---|
| `@cline/agents` | 运行时无关的 Agent 循环：`Agent`/`AgentRuntime`、`createAgent`、生命周期钩子、事件流、插件 |
| `@cline/llms` | 模型提供商网关与模型目录：`createGateway()`、`AgentModel` 构建 |
| `@cline/core` | 状态化编排层：`ClineCore.create()`、`createRuntimeHost()`、`LocalRuntimeHost`/`HubRuntimeHost`/`RemoteRuntimeHost`、默认工具、会话/团队/定时任务/钩子/MCP |
| `@cline/shared` | 共享类型：`AgentTool`、`AgentMessage`、`AgentRuntimeEvent` 等 |
| `@cline/ui` | UI 组件（桌面端复用） |
