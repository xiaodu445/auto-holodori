# Windows 操作模块

操作模块独立于感知和决策：不截图、不调用视觉模型或大模型。范围为整个当前用户桌面。输入发送到前台窗口，坐标为虚拟桌面物理像素；负坐标可用于主屏左侧的显示器。

## 已实现

- 键盘：字母、数字、F1–F12、方向键、常用功能键；按下/松开、短按、组合键、限时持续按键。
- 鼠标：绝对位置、相对移动、左/右/中键、滚轮、连续点击、拖拽。
- 游戏动作：按住多个键的同时分步相对移动鼠标，整段动作本地执行。
- 窗口：列出可见窗口、按 handle 切换前台、直接启动可执行程序并传递参数。
- 独立 Python 接口、JSON 批量命令、本地 stdio MCP 服务。

## 使用命令行

在项目根目录：

```powershell
$env:PYTHONPATH = "src"
# 校验动作，模拟执行
.\.conda\python.exe -m modular_agent.computer --file config/computer-actions.example.json
# 只列出当前窗口（真实桌面访问）
.\.conda\python.exe -m modular_agent.computer --live --list-windows
# 真实执行：示例会等待三秒，然后按 W 一秒并移动鼠标
.\.conda\python.exe -m modular_agent.computer --live --file config/computer-actions.example.json
```

默认是模拟模式；显式传入 `--live` 开启真实操作。批次执行完成或失败会释放它按住的输入。输入应当先聚焦目标窗口，或在三秒等待期间手动切到游戏。

## 动作契约

JSON 数组内每项是 `{ "name": "动作名", "arguments": {...} }`。

| 动作 | 参数 |
| --- | --- |
| `key_down` / `key_up` | `key` |
| `press` | `key`，可选 `duration`（默认 0.05 秒） |
| `hotkey` | `keys` 数组，可选 `duration` |
| `hold` | `keys`、`duration`，可选 `dx`、`dy`、`steps`；位移是整个动作的总量 |
| `text` | `text`；Unicode 输入，用于文本框，不适合作为游戏移动键 |
| `move_to` | `x`、`y` |
| `move_relative` | `dx`、`dy`，可选 `duration`、`steps` |
| `mouse_down` / `mouse_up` | 可选 `button`，默认 `left` |
| `click` | 可选 `button`、`count`、`interval`、成对的 `x` / `y` |
| `scroll` | `ticks`，正数向上、负数向下 |
| `drag` | 终点 `x`、`y`，可选 `button`、`duration`、`steps` |
| `wait` | `duration` |
| `windows` / `cursor` | 无 |
| `focus` | `handle`，来自 `windows` 返回结果 |
| `launch` | `executable`，可选字符串数组 `arguments`；不用 shell |
| `release_all` / `stop` | 无 |

时间单位为秒，单次 duration/interval 限制为 0–30 秒。steps 为 1–1000，count 为 1–10。完整参数校验在执行批次前完成。返回的 success 表示输入已发送，业务效果必须由独立感知模块验证。

## Python 接口

```python
from modular_agent.computer import ActionComputer
from modular_agent.core import Action

with ActionComputer(live=True, audit_path="runtime/computer-actions.jsonl") as computer:
    result = computer.perform(Action("hold", arguments={
        "keys": ["w", "shift"], "duration": 1,
        "dx": 80, "dy": 0, "steps": 60,
    }))
```

独立单动作调用允许跨调用持续按住键，调用者必须释放或关闭上下文；批量调用会在批次结束时释放。单动作和批次串行执行。stop 可从其他线程请求停止。

## MCP

项目环境已安装官方 MCP Python SDK 1.30.0。重新部署时可安装 `pip install -e ".[mcp]"`，SDK 限定在 1.x。

```powershell
$env:PYTHONPATH = "src"
.\.conda\python.exe -m modular_agent.computer.mcp_server --live
```

这是 stdio 服务，等待 MCP 客户端连接，不是聊天终端。客户端配置示例见 `config/computer-mcp.example.json`；其中已包含真实操作开关，但尚未自动注册到任何客户端。

暴露四个工具：`execute_action`、`execute_batch`、`list_windows`、`emergency_stop`；资源 `computer://actions` 返回参数契约。工具不传截图，CV/决策树可以直接调用 Python 接口，外部 Agent 可以调用 MCP。

## 停止与日志

- 按 F12 会停止当前 live 会话，并尝试释放该会话按住的所有键和鼠标按钮。恢复需重新创建会话或重启服务。F12 保留给紧急停止。
- 未释放的持续按键/鼠标按钮最长保持约 30 秒，此后停止会话。不要用它执行超过 30 秒的连续持键。
- 操作异常、批次结束、正常退出或 Ctrl+C 都尝试释放输入。进程被强制杀死、系统故障、无法发送释放事件时不能保证释放。
- JSONL 日志记录动作类型、时间、模式和结果，不记录输入文字或程序参数。

## 验证与限制

2026-10-01：19 项测试通过；包括真实 stdio MCP 握手和模拟工具调用。另已在实际 Windows 桌面验证窗口枚举、鼠标相对移动/恢复、Shift 按键发送。点击、文字输入和游戏内控制尚未做真实应用验证。

Windows 适配器遵循微软 SendInput、KEYBDINPUT、MOUSEINPUT 定义：
- https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
- https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput
- https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput

系统权限隔离可能阻止向更高权限程序发送输入；窗口前台切换可能被 Windows 拒绝，会返回 failure。游戏原始输入或防护机制也可能限制模拟输入。hololive Dreams 启动与强欲之牌入口链式操作已由用户确认，完整玩法仍未实现。本模块没有自动识别界面、寻找游戏或恢复状态；这些属于下一步感知与决策模块。


鼠标 `click`、`move_to`、`drag`、`scroll` 可选 `modifiers`（如 `["alt"]`）。执行器按住新加的修饰键，等待 50ms，再移动和点击；结束或异常时释放。已经由本会话按住的键不会被单次操作提前释放，批次完成仍统一释放所有输入。此机制是通用能力，具体游戏规则位于领域 launch.json 的 interaction_policy。
