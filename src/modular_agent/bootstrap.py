from __future__ import annotations

from pathlib import Path
import re


DEFAULT_FILES = {
    "knowledge/README.md": """# Global Knowledge Base

这里仅保存跨领域、经验证、可复用的通用知识，而不是操作日志。每个游戏或应用的专门知识保存在 `domains/<domain>/knowledge/`。
""",
    "knowledge/global/system.md": """# 系统原则

1. 先检索知识和调用已验证的 Skill；未知情况才升级给 General Agent。
2. Action 后必须重新 Observe 并 Verify。
3. 无匹配 Skill 或验证失败时，不猜测点击，状态标记为 `unknown` / `failure`。
4. 真实计算机控制需要明确的授权和目标窗口白名单。
""",
    "knowledge/skills/README.md": """# Global Skill Knowledge

这里记录跨领域通用 Skill 的使用条件。领域专用 Skill 的知识应放在 `domains/<domain>/knowledge/`。
""",
    "skills/README.md": """# Global Skills

这里仅存通用 Skill 契约或跨领域实现。专门 Skill 必须位于 `domains/<domain>/skills/`。
每个 Skill 需要 manifest、实现、说明与测试；完整规范在 `docs/usage.md`。
""",
    "domains/README.md": """# Domains

公共引擎、模型/API 配置和通用感知程序保留在项目顶层。每个游戏、应用或垂直任务在 `domains/<domain>/` 中独立保存知识、Skill、视觉模板、小模型和数据。

使用 `python -m modular_agent domain-init --domain game_x` 创建领域。`_template/` 只作结构参考，不存放真实资源。
""",
    "domains/_template/README.md": """# Domain Template

- `knowledge/`：稳定流程、UI 变化与失败经验
- `skills/`：仅适用于该领域的可执行能力
- `vision_library/`：人工维护的 UI 模板与验证统计
- `models/`：专用小模型、版本和评估说明
- `data/`：本地训练或评估数据
""",
    "prompts/general_agent_system.md": """你是模块化 Agent 的 General Agent。

优先使用已验证 Skill 和相关 Knowledge。只能输出符合 `docs/schemas/agent-decision.schema.json` 的 JSON；不输出 Markdown。不确定、风险较高或没有可验证动作时，返回 `decision: escalate`。不得直接输出鼠标坐标或执行系统命令。
""",
}

DOMAIN_FILES = {
    "README.md": """# Domain: {domain}

本目录只存 `{domain}` 的专属资源。通用模型/API 配置位于项目顶层 `config/`，通用 CV 与屏幕捕获代码位于 `src/modular_agent/perception/`。
""",
    "knowledge/README.md": """# Domain Knowledge

保存该领域中可复用且经验证的任务流程、UI 位置、版本变化和异常处理；不保存逐帧操作日志。
""",
    "skills/README.md": """# Domain Skills

这里存放只适用于当前领域的 Skill 实现和 `skill.json` manifest。通用接口说明见项目顶层 `skills/README.md`。
""",
    "vision_library/README.md": """# Domain Vision Library

此领域的人工模板库。通过 `vision-add-template --domain {domain}` 添加 UI 小截图。
""",
    "models/README.md": """# Domain Models

存放专属分类器、检测器或策略模型。每个模型必须有版本、数据来源、评估指标与回滚说明。
""",
    "data/README.md": """# Domain Data

本地训练与评估数据。只保存经授权并脱敏的数据；大文件默认不加入版本控制。
""",
}


def initialize_project(root: Path) -> list[Path]:
    created: list[Path] = []
    for relative, content in DEFAULT_FILES.items():
        path = root / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            created.append(path)
    return created


def initialize_domain(root: Path, domain: str) -> list[Path]:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", domain):
        raise ValueError("domain must be lowercase letters, digits, hyphens, or underscores")
    domain_root = root / "domains" / domain
    created: list[Path] = []
    for relative, template in DOMAIN_FILES.items():
        path = domain_root / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(template.format(domain=domain), encoding="utf-8")
            created.append(path)
    return created
