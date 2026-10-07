# 本地 5 分钟入门

[English](local.md) | 简体中文 · [中文首页](../../README.zh-CN.md) · [文档导航](../README.zh-CN.md)

需要 Git 和带 SQLite 的 Python 3.9+。Windows 用 `python --version` 检查；Linux/macOS
可能使用 `python3`。从源码运行不需要安装包、Docker、账号或 API key。
请使用新 clone 做虚构演示；`--reset` 会替换演示状态，不要在真实工作数据库中运行。

## 获取代码，所有 Shell 通用

```text
git clone https://github.com/markingtang/wxt-contextcanon.git
cd wxt-contextcanon
```

## 在你的 Shell 中运行

只选下面一个完整命令块，从仓库根目录开始执行。PowerShell 需要 `.\` 前缀，CMD 可直接用文件名，
Bash 需要 `./`。Bash 启动器会自动选择可用的 `python3` 或 `python`。

## Windows PowerShell

```powershell
.\contextcanon.cmd doctor
.\contextcanon.cmd demo seed --reset
.\contextcanon.cmd profile get --subject demo:alex-chen --key tooling.editor
.\contextcanon.cmd profile set --subject demo:alex-chen --key demo.score --value 42 --source user-stated
.\contextcanon.cmd profile history --subject demo:alex-chen --key tooling.editor
.\contextcanon.cmd profile as-of --subject demo:alex-chen --days-ago 30
.\contextcanon.cmd registry demo --reset
.\contextcanon.cmd benchmark smoke
.\contextcanon.cmd guard plan
```

## Windows CMD

```cmd
contextcanon.cmd doctor
contextcanon.cmd demo seed --reset
contextcanon.cmd profile get --subject demo:alex-chen --key tooling.editor
contextcanon.cmd profile set --subject demo:alex-chen --key demo.score --value 42 --source user-stated
contextcanon.cmd profile history --subject demo:alex-chen --key tooling.editor
contextcanon.cmd profile as-of --subject demo:alex-chen --days-ago 30
contextcanon.cmd registry demo --reset
contextcanon.cmd benchmark smoke
contextcanon.cmd guard plan
```

## Windows Git Bash

```bash
./contextcanon doctor
./contextcanon demo seed --reset
./contextcanon profile get --subject demo:alex-chen --key tooling.editor
./contextcanon profile set --subject demo:alex-chen --key demo.score --value 42 --source user-stated
./contextcanon profile history --subject demo:alex-chen --key tooling.editor
./contextcanon profile as-of --subject demo:alex-chen --days-ago 30
./contextcanon registry demo --reset
./contextcanon benchmark smoke
./contextcanon guard plan
```

## Linux / macOS

```sh
./contextcanon doctor
./contextcanon demo seed --reset
./contextcanon profile get --subject demo:alex-chen --key tooling.editor
./contextcanon profile set --subject demo:alex-chen --key demo.score --value 42 --source user-stated
./contextcanon profile history --subject demo:alex-chen --key tooling.editor
./contextcanon profile as-of --subject demo:alex-chen --days-ago 30
./contextcanon registry demo --reset
./contextcanon benchmark smoke
./contextcanon guard plan
```

## 预期结果

- Doctor：`ok: true`。
- Seed：创建虚构人物 `demo:alex-chen`，不导入个人资料。
- 当前编辑器：`zed`；历史：先 `vscode`，再 `zed`。
- 写入 `demo.score`：数值 42，并记录来源。
- 30 天前的编辑器：`vscode`。相对日期在以后年份仍可使用。
- Registry：`idempotent: true`，待处理 outbox 为 0；两个设备都是同一数据库内的逻辑 ID。
- Benchmark：ContextCanon 为 7/7，简单 Markdown 基线为 3/7。
- Guard：`outcome: planned`，没有部署、写入基线或创建锁。

默认数据放在相对当前工作目录的 `./data`。现有 `contextcanon.json` 或 `WXT_CONTEXTCANON_*`
环境变量可以改写路径；使用真实数据前先执行 `config show` 检查。源码启动器的写法分别是：
PowerShell `.\contextcanon.cmd config show`、CMD `contextcanon.cmd config show`、Bash `./contextcanon config show`。
事实和审计记录明文保存，敏感度标签不会阻止接入的 Agent 读取数据。

## 可选安装

在虚拟环境中执行 `python -m pip install .`，会安装 `contextcanon` 命令和演示、benchmark、Guard 资源。
开发时可用 `python -m pip install -e .`。不需要第三方运行包，但 pip 会获取构建后端。
前面的源码启动器不需要 pip 或激活虚拟环境。安装后请在新的工作目录使用命令，以选择本地数据的存放位置。

## 接入 Agent

按[MCP 客户端配置](../MCP_TOOLS.zh-CN.md#客户端配置)接入。`mcp` 从 stdin 等待协议消息，
手动启动后看起来没有动静是正常的；它不是交互式命令提示符。
客户端必须明确配置为同一组数据库路径，才能看到刚才写入的演示事实。
不会自动导入 ChatGPT 或其他平台的聊天记录。

## 验证教程

`python tools/check_quickstart.py` 会在隔离的虚构存储中执行英文教程的适用命令块并检查结果。
中文版四个命令块与英文版保持相同；Windows 检查 PowerShell、CMD、Git Bash，Unix 检查 Bash。
Shell 缺失会报告 SKIP，不会冒充 PASS。macOS 未纳入 CI。
