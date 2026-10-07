# 贡献指南

[English](CONTRIBUTING.md) | 简体中文 · [中文首页](README.zh-CN.md)

以下规则用于保持公开仓库可安全发布。

## 开始前

从仓库根目录运行：

```bash
python tests/run_all.py
python tools/scan_secrets.py
python tools/prove_isolation.py
mkdir synthetic-watch
python tools/accept_clean_home.py --watch synthetic-watch
python tools/check_quickstart.py
python tools/check_install.py
```

完整测试应通过，扫描应报告 `GATE: PASS`。隔离检查只是静态配置门禁。

## 必须遵守

1. **不提交私人数据**：不提交真实私人姓名、设备、主机、IP、手机号、私人绝对路径、token、key、
   内部项目代号或客户资料。需要例子时编造数据并标记 `SYNTHETIC`。
2. **不提交真实配置**：示例主机使用 `localhost` 或 `127.0.0.1`；路径使用相对路径或 `./data`；
   device ID 使用 `demo-device` 这样的演示值。
3. **新增运行时依赖需充分理由**：当前只依赖 Python 标准库和 SQLite，便于陌生开发者直接运行。
4. **不隐瞒第三方源码来源**：引用其他项目片段时，先在 `docs/THIRD_PARTY_NOTICES.md` 声明来源与许可。
   未声明的复制代码会阻止发布。
5. **新增 MCP 工具先讨论**：当前接口有意保持 8 个工具，更多逻辑优先放在 CLI 或服务层。
6. **测试行为**：变更业务规则时，在 `tests/` 增加案例；用户可见的能力变化还应在
   `benchmark/cases/cases.json` 增加合适案例。

## 代码风格

- 兼容 Python 3.9+，采用常规格式，新增公共函数提供类型提示。
- 优先使用服务层的小型纯函数，避免难以理解的 SQL 技巧。
- 注释解释原因。

## Benchmark 贡献

案例必须：

- 使用虚构数据，不使用真实资料。
- 确定性运行，期望值不依赖随机数或当前时钟。
- 默认精确匹配，不用 LLM 评分。
- 如实报告；Markdown 基线通过也是有效结果，不能隐藏。

## Pull request

每个 PR 做一个逻辑变更。说明改了什么、原因和验证方式。
涉及存储或事件日志时，说明现有数据会受到什么影响。

## 许可

项目使用 **Apache-2.0**，见 [LICENSE](LICENSE)。提交 PR 表示你同意以 Apache-2.0
许可贡献，并拥有相应授权权利。此中文段落是非权威解释，正式法律条件以原始 LICENSE 为准。

- 新增运行依赖时，在 `docs/THIRD_PARTY_NOTICES.md` 记录依赖、许可与再分发条件。
  Apache-2.0 §4 包含第三方声明义务；目前没有第三方运行依赖。
- 避免复制其他项目代码；确需引用时，合并前在同一文件声明上游许可。

代码许可不转让项目名称，名称使用规则见 [TRADEMARKS.md](TRADEMARKS.md)。

## 命名

公开命名由 `tests/test_brand_consistency.py` 检查：

| 项目 | 值 |
|---|---|
| 项目名 | `WXT ContextCanon` |
| 仓库 slug | `wxt-contextcanon` |
| CLI 命令 | `contextcanon` |
| MCP server 名 | `wxt-contextcanon` |
| Skill 名 | `wxt-contextcanon` |
| 环境变量前缀 | `WXT_CONTEXTCANON_` |

涉及这些名称时应检查对应测试。改名需要明确讨论，不能顺手修改。

本页 Shell 示例从仓库根目录在 Bash 中运行。PowerShell 的源码启动器使用 `.\contextcanon.cmd`，
CMD 使用 `contextcanon.cmd`；完整跨平台步骤见[中文入门](docs/quickstart/local.zh-CN.md)。

CI 在实际带 origin 的 checkout 上检查 Windows/Linux、Python 3.9/3.13。
工作区扫描与完整历史扫描分开运行。MCP 使用固定版本的可选测试客户端，详见
[中文接入指南](docs/MCP_TOOLS.zh-CN.md)。CI 不部署，也不需要私人密钥。
首发历史保留，正常分支、远端和合并都允许；测试实际输出是权威数量，不应依赖冻结的文案数字。

watch 比较仅覆盖指定目录。CI 使用虚构 fixtures，不能据此证明真实生产系统被观察过或没有变化。

## 维护中英文文档

中文文档以 `.zh-CN.md` 命名，保留英文原文。修改功能说明时同步更新两种语言；
命令、API、路径、参数和版本保持一致。新增双向导航时检查相对路径及标题锚点。
功能尚未实现或客户端未验证时，两种语言都要明确标注。
