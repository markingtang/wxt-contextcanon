# 安全与隐私政策

[English](SECURITY.md) | 简体中文 · [中文首页](README.zh-CN.md)

## 范围

WXT ContextCanon 的 `packages/`、CLI、MCP server、Release Guard 和 benchmark runner。

## 支持版本

当前补丁版本为 `0.1.1`，原 `0.1.0` 历史保留。目前尚无支持版本矩阵。
公开仓库为 https://github.com/markingtang/wxt-contextcanon。

## 报告问题

提交 issue 时**不要包含任何个人资料**。请描述：

1. 做了什么。
2. 预期结果。
3. 实际结果。
4. 是否涉及你认为私密的数据。

不能分享的数据，用机制描述替代；不要把私密值、凭证或真实数据库附在公开 issue 中。

## 安全模型

项目已做的事情：

- 默认本地保存数据，SQLite 文件位于工作目录。
- 为事实记录来源、敏感度和修订历史。
- 不隐式删除事实；过期、被取代、被拒绝的事实仍可审计。
- Release Guard 失败即停止后续步骤，并释放自身锁。
- 提供 `tools/scan_secrets.py`：`python tools/scan_secrets.py` 扫描工作区；
  加 `--history` 扫描每个 Git ref 可达的对象，可发现曾提交后又删除的敏感内容。
  扫描要求零发现通过，不依靠豁免结果。静态扫描有识别边界，不能代替人工核查。

项目尚不提供的保护：

- **数据库静态加密**。需要时使用全盘加密或支持加密的数据库。
- **身份认证**。0.1.1 没有账号、常驻网络 API；MCP 通过 stdio 与以你的身份运行的客户端通信。
  Release Guard 的虚构测试栈可临时启动 loopback HTTP 服务。
- **Agent 沙箱或权限隔离**。能调用 `profile_upsert` 的 Agent 可写任意 subject 的事实。
  应把 MCP 访问视作与 shell 访问同等信任级别。
- **抵御已被入侵的主机**。以你的用户身份运行的程序可读取 `./data`。

## 敏感事实的处理

- 不希望出现在日志或摘要中的内容，可标记 `sensitivity: restricted`。
- **`restricted` 是标签，不是访问控制，当前没有强制执行机制**。
- 不要在事实中存凭证；保存指向秘密管理器的引用，不保存秘密值。
  演示的 `secrets.policy` 事实展示了这个建议。

## 不在处理范围内

- 针对本地 SQLite 文件的拒绝服务攻击。
- 攻击者已经能在宿主机执行任意代码的场景。
- 虚构人物 `demo:alex-chen` 的演示资料，它本来就是 synthetic 数据。

## 输出与保留边界

CLI/MCP 成功响应与审计事件包含请求的事实值，包括 `restricted` 值，不要将它们发送到公开日志。
MCP 内部错误不回显原始异常文本，但自定义 Guard 命令的 stderr 可能包含敏感信息，请本地检查。

Registry 不读取文件内容，但调用方可以在事件 payload 中放任意数据；服务无法阻止调用方保存凭证。
`sensitivity`、`actor`、`source`、device ID 都是调用方提供的元数据，不构成认证或授权。

隔离检查器提供静态配置检查和可选目录元数据比较；它不是沙箱、网络监控，也不能证明配置中的
命令无法访问生产。虚构 watch 检查只说明被观察的虚构目录。
