# 模块化自扩展 Agent

当前项目入口与后续计划见 [项目现状](docs/PROJECT_STATUS.md)，文件职责、训练集和归档位置见 [资源目录](docs/ASSET_CATALOG.md)。本仓库保留通用 Agent、游戏领域模块和开发工具；大型模型、标注数据、录像及个人凭据保留本地，克隆后需补齐资产。

这是本地游戏自动化项目：以可测试的统一接口验证 **观察 → 路由 → 执行 → 验证 → Experience → Memory** 闭环。

已增加独立的 Windows 键鼠/窗口操作模块和本地 MCP 服务；默认模拟执行，显式启用 `--live` 才操作真实桌面。操作模块不截图、不调用模型。使用方法见 [docs/computer.md](docs/computer.md)。顶层 Agent 已接入本地感知与真实执行，通过 `start_agent.cmd` 打开交互命令行；顶层模型先观察并选择技能；Steam启动/登录与强欲之牌入口已接入本地决策树，未知状态交回顶层。独立本地入口不需要API。

## 快速运行

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "src"
.\.conda\python.exe -m modular_agent init
.\.conda\python.exe -m modular_agent run --goal "检查每日任务" --provider mock
```

模型由 `config/model.example.json` 配置，也可以临时用 `--model`、`--base-url` 和 `--api-key-env` 覆盖。密钥从环境变量或 Windows 用户绑定的加密凭据读取，配置不包含明文密钥。当前默认已接入 Kimi；通过 /models 和 /model 切换，见 docs/models.md。

## 核心模块

- `core`：共享领域模型与端口（接口）
- `skills`：Skill 契约、注册中心及 Router
- `memory`：可检索的 Markdown 长期记忆与经验归档
- `agent`：计划与行动闭环编排
- `computer`：计算机交互接口、dry-run、Windows 输入适配器及 MCP 服务
- `perception`：屏幕/窗口几何、UIA 按钮、本地中英文 OCR、CV 候选和视觉知识匹配

## 资源分层

- 顶层 `config/`、`prompts/`、`knowledge/global/`、`src/modular_agent/`：通用模型配置、全局规则、总感知与执行引擎。
- `domains/<domain>/`：一个游戏或专用任务的知识、Skill、视觉模板、小模型和数据。

```powershell
python -m modular_agent domain-init --domain game_x
```

使用方式、JSON 契约、Skill 开发要求和知识库结构见 [docs/usage.md](docs/usage.md)。

文档入口：

- [小地图定位与刷新点巡逻框架](docs/patrol.md)：`patrol.cmd` 被动定位预览、路线编辑、标定与影子控制建议；尚未接通实机自动拾取。
- [宝藏点与路线标注](docs/navigation-editor.md)：`navigation_editor.cmd` 标注和绕障规划；自动路线只用W与转镜头，读取完整镜头标定，已验证跳跃用W+Space，F12停止。完整实机路线待验证。
- [W加速与镜头标定](docs/motion-probe.md)：`motion_probe.cmd` 测W按住/松键响应，以及直接移动鼠标转镜头的一圈有效计数；光锥与人物朝向独立，实测参数尚待游戏采样。
- [多地图建图工作台](docs/map-workbench.md)：`mapping_workbench.cmd` 按地图隔离采集、拼图、修复、追踪和标注；标注工具新增绕障规划和路线跟随辅助预览。
- [小地图探索建图](docs/minimap-mapping.md)：无现成全图时，`minimap_scan.cmd` 手动走动拼图，`minimap_explore.cmd` 短步自动探索；实机效果待验证。
- [小地图半自动对齐](docs/minimap-alignment.md)：`minimap_align.cmd` 关键帧叠加、像素微调、人工地标约束和整段轨迹纠偏，离线另存新地图。
- 从零手工拼图：`minimap_manual.cmd` 从空白项目逐张确认加入截图，不采用原自动坐标；可画掩膜并保存进度，详见上述对齐文档。

- [项目交接与顶层模块](docs/PROJECT_CONTEXT.md)
- [使用手册](docs/USER_GUIDE.md)
- [领域模块开发规范](docs/DOMAIN_DEVELOPMENT.md)
- [架构与后续实施顺序](docs/architecture.md)
- [视觉模板库](docs/vision.md)

- [Windows 操作模块与 MCP](docs/computer.md)

- [顶层通用本地感知](docs/general-vision.md)

- [顶层 Agent 命令行与启动测试](docs/agent-console.md)

- [模型配置与切换](docs/models.md)

识别接口已支持独立模块开关、指定文字/模板搜索、桌面物理像素ROI、单次阈值/缩放和可取消等待。默认完整识别保持兼容，详见 [识别接口文档](docs/general-vision.md)。

按目录知识检索已接入：先列目录/标题，再按领域、目录或文件分页读取；历史日志默认排除。Skill只发当前领域调用元数据。详见 [知识与技能上下文说明](docs/knowledge-routing.md)。

## 跳绳开发路线

当前自用入口为 `learning/jump_rope_yolo/run_game_jump_loop.cmd`，说明见[跳绳主线](learning/jump_rope_yolo/README.md)。后续考虑更换模型与调整 GPU 调度，人工标注集必须保留。[旧路线索引](docs/jump-rope/README.md)及其交接文档保留作历史研究，旧实验启动器在 `tools/jump_rope/legacy_launchers/`。
