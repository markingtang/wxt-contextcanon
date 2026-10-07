# MCP 工具与客户端接入

[English](MCP_TOOLS.md) | 简体中文 · [中文首页](../README.zh-CN.md) · [中文入门](quickstart/local.zh-CN.md)

项目提供 **8 个工具**。Agent 使用小而稳定的词汇，其余功能放在 CLI。

| 工具 | 用途 |
|---|---|
| `profile_get` | 读取一个当前有效事实 |
| `profile_search` | 按子串搜索当前有效事实的 key 和 value |
| `profile_upsert` | 新建或替换事实，处理取代与冲突 |
| `profile_as_of` | 查询指定有效时间的事实 |
| `profile_history` | 查询一个 key 的全部修订 |
| `profile_audit` | 查询一个 subject 的只追加审计记录 |
| `registry_query` | 读取共享文件状态索引 |
| `registry_event` | 追加文件状态事件并投影到索引 |

## 为什么取代和冲突是参数

Agent 声明事实，通过 `profile_upsert` 的 `on_conflict` 指定策略：

- `supersede`，默认：旧值成为被取代的修订。
- `reject`：新声明保存为 `rejected`，原有可信值不变。
- `keep`：保留原值，记录 conflict-kept 审计事件。

单独增加 `profile_supersede`、`profile_reject` 会把策略判断放进 Agent 提示词。
参数形式使规则留在可测试的服务层。任务的 `begin` / `end` 属于批量操作，只通过 CLI 暴露；
需要时按所在 Shell 调用 `contextcanon registry begin`，源码启动器写法见[入门教程](quickstart/local.zh-CN.md)。

## 协议

通过 stdio 使用 MCP，消息为逐行 JSON-RPC 2.0。

- `initialize`：返回 `protocolVersion`、`capabilities.tools`、`serverInfo`。
- `notifications/initialized`：不返回响应。
- `tools/list`：返回 8 个工具及 JSON schema。
- `tools/call`：返回 `{ content: [{ type: "text", text: "<json>" }], isError: bool }`。
- `ping`：返回 `{}`。

工具参数校验或执行失败返回 `isError: true`。非法 JSON-RPC envelope、未知方法和未知工具名
返回顶层 JSON-RPC 错误。通知没有响应，不能用于调用工具。错误调用不会结束 stdio 会话。

## Schema 示例

以下字段、API 名称和参数保持英文原样。

### `profile_get`

```json
{ "subject": "demo:alex-chen", "key": "timezone", "include_inactive": false }
```

### `profile_search`

```json
{ "subject": "demo:alex-chen", "query": "editor", "limit": 20 }
```

### `profile_upsert`

```json
{
  "subject": "demo:alex-chen",
  "key": "tooling.editor",
  "value": "zed",
  "sensitivity": "personal",
  "durability": "durable",
  "valid_until": null,
  "source": "user-stated",
  "confidence": 1.0,
  "on_conflict": "supersede"
}
```

响应为 `{ action, fact, supersedes, conflicts_with }`，`action` 取值为
`created | superseded | rejected | kept | unchanged`。

### `profile_as_of`

```json
{ "subject": "demo:alex-chen", "timestamp": "<UTC timestamp from 30 days before demo seed>", "include_rejected": false }
```

### `profile_history`

```json
{ "subject": "demo:alex-chen", "key": "tooling.editor" }
```

### `profile_audit`

```json
{ "subject": "demo:alex-chen", "limit": 50 }
```

### `registry_query`

```json
{ "object_key": "notes/a.md", "device_id": "demo-device" }
```

### `registry_event`

```json
{ "kind": "file.upsert", "payload": { "object_key": "notes/a.md", "checksum": "abc123" } }
```

## 协议兼容范围

服务器声明 **2024-11-05**，保留初始化握手，不声明实现 2026-07-28。
[官方版本规则](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)
区分初始化握手客户端与使用逐请求 metadata 的现代客户端。支持两个时代的 stdio 客户端会先探测
`server/discover`；本服务器返回 -32601 后，客户端可以回退到旧版握手。
仅修改版本字符串并不等于实现 discovery 或逐请求 metadata。

已用官方 Inspector **2.9.0** 的 auto 模式、官方 TypeScript client **2.3.1** 的 legacy 和 auto 模式验证：
连接、全部 8 个工具、虚构事实读取、JSON 写入、修订历史、时间查询，以及错误调用后的继续操作。
只支持/强制 2026-07-28 的现代客户端不受支持。Claude Desktop、Codex 和其他 AI 宿主 GUI
尚未逐一验收，不能宣称全部兼容。

## 客户端配置

使用可信、支持旧版协议或自动回退的 stdio 宿主。不要假定客户端支持 `cwd`。
提供解释器、包和数据库的绝对路径。把示例路径全部替换为你自己的路径；Windows JSON 可使用
正斜杠（含自己的盘符），或用双反斜杠转义。

```json
{
  "mcpServers": {
    "wxt-contextcanon": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/wxt-contextcanon/packages",
        "PYTHONIOENCODING": "utf-8",
        "WXT_CONTEXTCANON_PROFILE_DATABASE": "/absolute/path/to/wxt-contextcanon/data/profile.db",
        "WXT_CONTEXTCANON_PROFILE_DATA_DIR": "/absolute/path/to/wxt-contextcanon/data",
        "WXT_CONTEXTCANON_REGISTRY_SHARED_STORE": "/absolute/path/to/wxt-contextcanon/data/registry/shared.db",
        "WXT_CONTEXTCANON_REGISTRY_HOME": "/absolute/path/to/wxt-contextcanon/data/registry"
      }
    }
  }
}
```

把配置保存为公开仓库之外的本地 `mcp-client.json`。不同客户端配置格式可能不同；上述格式已被
Inspector 接受，不保证所有宿主都接受。先完成 Quickstart seed，再让客户端指向同一数据目录。

安装 Node 22.19+ 后，可以在任意 Shell 运行真实 Inspector CLI：

```text
npx --yes @modelcontextprotocol/inspector@2.9.0 --cli --config mcp-client.json --server wxt-contextcanon --protocol-era auto --method tools/list --strict
npx --yes @modelcontextprotocol/inspector@2.9.0 --cli --config mcp-client.json --server wxt-contextcanon --protocol-era auto --method tools/call --tool-name profile_get --tool-arg subject=demo:alex-chen key=tooling.editor
```

预期看到 8 个工具，编辑器值为 `zed`。写入测试请使用 `demo:client` 等**虚构** subject：
调用 `profile_upsert`，再对同一个 key 调用 `profile_get` 和 `profile_history`。
`profile_as_of` 应使用生成的 ISO 时间戳或演示事实的 `valid_from`，不要用固定日历日期
查询相对当前时间生成的演示窗口。Schema 中的时间占位符必须先替换，不能直接当作时间值执行。

CI 使用的完整虚构会话可重现如下：

```text
npm install --prefix .mcp-test --no-audit --no-fund --ignore-scripts @modelcontextprotocol/inspector@2.9.0 @modelcontextprotocol/client@2.3.1
node tools/check_mcp_client.mjs .mcp-test
```

检查会创建隔离临时数据，不使用真实 Profile；SDK 同一连接内会在非法调用后继续 ping 和工具发现。
协议客户端测试证明 Agent 能连接和调用工具，不评测模型的推理质量或是否愿意调用工具。
敏感度标签不提供权限隔离，请只接入可信 Agent。
