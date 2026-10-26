# 第一阶段架构

```text
User goal → Orchestrator → Observer → structured State
                  ↑              ↓
              Memory retrieval  Skill Router → registered Skill
                                                    ↓
                                          execute → observe → verify
                                                    ↓
                                               Experience → Memory
```

## 已落实的边界

| 模块 | 当前职责 | 后续替换方向 |
| --- | --- | --- |
| `core` | 领域模型和 Protocol 接口 | 保持稳定 |
| `skills` | 注册、元数据、确定性路由 | Jev/小模型 Router |
| `memory` | 可审阅 Markdown 经验库 | SQLite + 向量/混合检索 |
| `perception` | MSS 截图、窗口/UIA、RapidOCR、CV 候选与视觉知识匹配 | OCR、特征匹配、YOLO |
| `computer` | dry-run、独立 Windows 输入/窗口适配器、stdio MCP | 接入感知与游戏状态机；游戏内兼容性验证 |
| `agent` | 一次闭环编排 | Planner、General LLM、状态机 |

## 资源目录边界

```text
config/ + prompts/ + knowledge/global/ + src/modular_agent/  # 通用层
domains/
  _template/                                                  # 仅模板，不存真实数据
  game_x/
    knowledge/ | skills/ | vision_library/ | models/ | data/  # 专用层
```

## 下一步实施顺序

1. 为目标游戏定义 `EnvironmentProfile` 和状态机（不接真实操作）。
2. 通用只读感知已实现：窗口枚举、截图、OCR、按钮候选和模板匹配，支持转换为 `State`；下一步建立目标游戏经验包。
3. 为确认过的界面实现游戏专用 Skill，并使用 dry-run 回放验证。
4. Windows Computer Adapter 和 MCP 已实现，用户已授权整个桌面操作；下一步验证目标游戏，并接入独立感知和决策模块。
5. 增加 General LLM 的未知情况升级通道和人工审核的 Memory/Skill 固化流程。

## 安全约束

- Router 只返回 Skill；Skill 的执行结果必须经重新观察验证。
- 未找到匹配 Skill 时，结果为 `UNKNOWN`，不会自行猜测或点击。
- Memory 只写入标记为可复用且验证通过的 Experience。
- 真实控制必须与 dry-run 实现分离，且不能作为默认配置。

## 当前识别扩展接口（2026-10-02）

识别模块保持原full兼容，新增独立OCR/UIA/CV/模板开关、桌面ROI、指定模板、单次缩放/阈值、find_text/find_templates/wait_for。详见 [识别接口说明](general-vision.md)。本地组件应通过这些接口减少无关计算，并保留未知状态与完整识别兜底；不缓存历史坐标，不同时控制键鼠。当前已实现启动与强欲之牌入口树，尚未实现下注/卡牌策略。
