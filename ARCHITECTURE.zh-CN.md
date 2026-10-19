# WXT ContextCanon 架构

[English](ARCHITECTURE.md) | 简体中文 · [中文首页](README.zh-CN.md)

本文说明 0.1.2 已构建的能力，以及尚未实现的边界。

## 1. 定位

WXT ContextCanon 是从干净首发提交建立的独立公开仓库，不是把私人仓库删去名称后公开，
也不是改名 fork。公开文件为本仓库编写，私人系统与内部项目历史不属于发布内容。

设计涉及四个对象：一份个人上下文、一份文件状态账本、多个 Agent、多个设备。

| 设计目标 | 0.1.2 实际交付 |
|---|---|
| 一份个人上下文 | Profile Core，同机多 Agent 共享存储 |
| 一份文件状态账本 | Registry Core，只追加事件，可重建索引 |
| 多个 Agent | 多个 Agent 可读写同一 Profile |
| 多个设备 | 同一本地数据库内模拟第二个逻辑设备；**没有机器间网络传输** |
| 运行时 | **单机**，每个 store 使用本地 SQLite |

## 2. 技术选择

| 选择 | 原因 | 代价 |
|---|---|---|
| Python 3.9+，仅标准库 | 源码可直接运行，无第三方运行依赖 | MCP 协议需自行维护 |
| SQLite | 随 Python 提供，不需数据库服务器，支持单机并发 | 跨机器写入需要后续传输机制 |
| stdio MCP，自行实现 JSON-RPC | 避免新增 SDK 运行依赖 | 要手动跟进规范变化 |
| JSON 配置 | 不需 YAML parser | 手写配置稍不方便 |
| 可选 Docker | 核心数据是本地文件，无需容器 | 容器路径的实跑验证较少 |

0.1.2 不包含向量数据库、图数据库、Redis、PostgreSQL、SaaS、云版本、付费组件、Dashboard、
多租户、权限后端、手机应用、数据采集连接器或运行时 LLM 调用。

## 3. 包结构

```text
packages/
  contextcanon_config/  配置加载，默认本地和虚构值
  profile_core/        model · store · service
  registry_core/       store · service
  mcp_server/          stdio JSON-RPC server，8 个工具
  contextcanon_cli/    context · demo · cli，contextcanon 命令
```

分层原则：业务规则放在 service，store 执行 SQL，MCP/CLI 调用 service。
这种分工为未来新增存储后端提供接口边界；PostgreSQL 仍需新的存储实现与事务集成。

## 4. Profile Core

### 模型

事实是带版本、来源和时间边界的**声明**，不只是字符串；其真实性不会被自动核验。

```text
fact_id · subject · key · value
status        active | superseded | rejected | expired
sensitivity   public | personal | sensitive | restricted
durability    durable | temporary | scheduled
certainty     real
valid_from / valid_until   ISO-8601 UTC, nullable
provenance    { source, ref, method, observed_at, confidence }
revision · supersedes · superseded_by · conflicts_with
created_at / updated_at
```

这里 `certainty` 的 `real` 表示数值类型。标签和来源由调用方填写，不是身份认证。

### 生命周期

```text
write → active → superseded
           ├──→ expired
           └── 新冲突候选 → rejected
```

新修订取代旧修订；有效期到期后可通过 expire sweep 标为 `expired`，不会自动删除。
拒绝的冲突候选也保留。`durability` 表达持久、临时或计划用途，不会自动建立定时任务。

### 冲突策略

`profile_upsert` 的 `on_conflict`：`supersede`，默认；`reject`；`keep`。
选择 `reject` 时，低可信推断不会覆盖已有值，而是成为被拒绝的记录。
系统按调用者提供的策略处理，不会自动判断哪个说法更可信。

### 时间查询

`as_of(subject, T)` 按每个 key 选择满足 `valid_from <= T < valid_until` 的最高 revision。
查询依据有效时间窗口，不依据行创建时间，因此支持回溯生效和计划生效的事实。
空的 `valid_until` 表示无结束时间。

### 审计

`fact_events` 只追加：`fact.created`、`fact.reasserted`、`fact.superseded`、
`fact.rejected`、`fact.expired`、`fact.conflict_kept`。每次写入记录 actor。

## 5. Registry Core

Registry 是**文件状态账本**，记录每个设备对 object key 状态的声明，不读取或保存文件内容。
调用方仍可在 payload 中放任意数据，需要自行避免敏感信息。

| 表 | 用途 |
|---|---|
| `devices` | `device_id`、`role` 设备标识 |
| `events` | 只追加：`seq`、唯一 `event_id`、`device_id`、`stream`、`kind`、`ts`、`payload` |
| `outbox` | 离线工作队列，恢复时重放 |
| `applied` | 已投影事件的幂等记录 |
| `shared_index` | 派生投影：`object_key`、`device_id`、`state`、`version` |
| `manifests` | 设备声明持有的对象及 checksum |
| `checkpoints` | `last_good_rebuild` |

沿用的设计能力包括设备标识、manifest、事件账本、outbox、共享索引重建、幂等、last-good 和离线恢复；
公开代码是独立实现。

```text
offline: queue → outbox
online:  drain_outbox() → append event → project → mark applied
         rebuild_shared_index() → recompute → restore last-good on failure
```

按事件 ID 幂等；同 ID 内容不同会报错。异常事件不能静默丢弃。
索引重建使用事务，失败保留先前索引和应用标记。

变更意图通过 CLI 明确记录：`registry begin --task-id --intent --targets`，完成后 `registry end`。
未结束的任务可作为 Agent 被中断的线索。

## 6. Agent 接口

### MCP：8 个工具

`profile_get`、`profile_search`、`profile_upsert`、`profile_as_of`、
`profile_history`、`profile_audit`、`registry_query`、`registry_event`。

取代与冲突处理是 `profile_upsert` 的参数，不是独立工具；策略保留在可测试的服务层。
`begin` / `end` 属于批量任务，通过 CLI 使用。
协议和已验证客户端见[中文 MCP 指南](docs/MCP_TOOLS.zh-CN.md)。

### CLI

`config`、`demo`、`profile`、`registry`、`benchmark`、`guard`、`mcp`、`doctor`。

### Skill

`skills/contextcanon/SKILL.md` 是刻意保持简短的 Agent 指引：规则、何时读取/更新/声明意图、最小用法。
详细模型、部署与安全规则放在 `docs/` 和代码中。Skill 目前保留英文，入口见[中文导航](docs/README.zh-CN.md)。

## 7. Release Guard

Guard 使用配置与传输适配器：`local-shell | ssh-shell`。目标由配置提供，不内置真实主机或项目常量。

实际执行顺序：

```text
project_guard → mutation_intent → lock → integrity → backup_gate
  → migration_test → deploy → post_health → smoke
```

`fail_closed` 记录失败。备份和迁移验证在部署前运行；任何步骤失败则停止后续步骤，报告失败位置，
尝试释放自身锁。`plan` 是 dry-run，不创建基线或锁；`apply` 需要 `--intent`。
首次 apply 在锁内写入完整性基线，之后输入变化需要显式检查基线。

随仓库提供虚构测试栈：`127.0.0.1` HTTP 服务、虚构备份和可强制失败的迁移测试。
CI 不需要 Docker 或外部网络即可验证守卫，但测试服务会使用本地 loopback 网络。

这里只承诺代码和测试覆盖的步骤；没有生产 canary、journal 模式、direct-vs-journal 比较或多主机部署方案。
Kubernetes、Nomad、Swarm 不在范围内。

## 8. Benchmark

full 为 **9 个确定性虚构案例**，包含真实调用功能和 last-write-wins Markdown 文件基线。
没有 LLM 评分：**ContextCanon 9/9，Markdown 3/9**；Markdown 通过简单回忆、写入读回和同存储双 Agent 读取。

`./contextcanon benchmark smoke` 使用上述案例中的 **7 个**：**ContextCanon 7/7，Markdown 3/7**。
它是快速检查子集，不是独立评测。案例有限，不代表所有系统或所有模型的实际表现。

## 9. 配置

实际配置使用 JSON。下表式代码块仅列出字段结构：

```text
profile:  host · port · database · data_dir
registry: device_id · registry_home · shared_store · device_role
deploy:   project_name · compose_binary · compose_files · services · lock_path
          backup_command · migration_test_command · smoke_command · deploy_command
          health_endpoints · transport · ssh{host_alias,workdir}
server:   name · version
```

示例值为 `127.0.0.1`、`localhost`、`./data`、`demo-device`、`wxt-contextcanon`。
默认不提供 SSH host alias，避免意外运行 SSH 传输。

## 10. 当前未包含的能力

Hindsight、Mem0、Supermemory、Cognee 集成；向量/图数据库；Redis；SaaS 或云版本；商业等级；
复杂 Dashboard；多租户；权限后端；手机应用；自动聊天导入；邮件/日历/健康/财务连接器。

## 11. 扩展方向

| 方向 | 需要的工作 | 可复用的边界 |
|---|---|---|
| 真实跨机器传输 | 基于事件日志和 outbox 的传输，并继续设计和测试 | 现有账本模型 |
| PostgreSQL | 新 store 与事务集成 | service 接口 |
| HTTP API | service 外层接口 | 核心服务 |
| 冲突审核 UI | 消费 `rejected` 事实的界面 | 事实模型 |

以上是扩展思路，不是已经实现的功能或交付承诺。

## 运行边界

时间查询使用有效时间，不是按每个数据入库时刻回放系统认知的完整双时间（bitemporal）模型。
每个 key 在有效窗口内最高 revision 优先。临时覆盖到期后，较早但仍有效的值可重新显示。
被拒绝的声明默认排除，除非明确要求包含。

写入由 SQLite 事务保护，没有分布式复制或自动冲突共识。敏感度标签不限制读取。
Guard 失败会停止后续步骤，但不会自动回滚已完成部署、恢复备份或恢复整个进程树。
健康检查/烟雾检查失败时，已部署服务可能继续运行。强制终止可能留锁，需要操作员检查。
