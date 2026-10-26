# 运行本体与开发工作区

| 目录 | 用途 |
| --- | --- |
| `D:/Code/Codex/Game_agent` | 本运行仓库；使用入口、运行代码、必要模板和当前模型 |
| `D:/Code/Codex/Game_agent_dev` | 独立开发源码、在研寻路、标注/录像/回放/训练工具、测试、打包和原始数据 |
| `D:/Code/Codex/workspace-archive` | 先前的构建缓存与可恢复归档 |

本仓库不再包含 tools、learning、tests、release 或寻路开发入口。`entrypoints/run_multi_live.py` 和 `gui/kitchen_control.py` 原来混放在 tools 中，实际是运行程序，已保留为本体入口。运行日志写入 runtime，凭据和本机 Python 环境继续被 Git 忽略。

## 开发工具在哪里

- 寻路／路线编辑／示教：`../Game_agent_dev/navigation_editor.cmd`。
- 建图：`../Game_agent_dev/mapping_workbench.cmd`，各 `minimap_*.cmd` 保留。
- 标注、录像、回放和训练：`../Game_agent_dev/` 根目录原同名启动器。
- 寻路源码：`../Game_agent_dev/src/modular_agent/realtime/navigation_editor.py` 及 `src/modular_agent/domains/hololive_dreams/` 下的导航模块。
- 当前地图项目：`../Game_agent_dev/runtime/patrol/navigation/20261025-201430-8fd78b/`；所有原地图、路线、标注和运行记录保留。
- 厨房标注与原录像：`../Game_agent_dev/runtime/kitchen/manual-labeling/`、`recordings/`。
- 跳绳训练与标注：`../Game_agent_dev/learning/jump_rope_yolo/`；原始训练 JPEG 与录像在该工作区 runtime/jump-rope。
- 测试在开发工作区 tests，发布构建在 release。使用方法见该工作区 README.md。

原始开发源码先完整复制并校验后才从本体移出；开发副本与本体源码独立。开发工作区的 `.conda` 和跳绳 `.venv` 只共享本体的解释器环境（目录联接），不共享源码或训练数据。导航 JSON 中已嵌入的绝对路径重定位到开发工作区，改动前副本在 path-rebase-originals。

## 运行模型

- 跳绳：`domains/hololive_dreams/models/jump_rope/` 保存当前运行代码、循环模板及当前07模型/引擎。历史合成和ROI裁剪辅助函数从原实现逐字提取，运行时不导入训练脚本。算法参数未调整，输出目录改为 runtime/jump-rope。
- 厨房：`domains/hololive_dreams/models/kitchen/` 保存当前 best-box 权重和匹配的 TensorRT 引擎，`data/kitchen/runtime-profile.json` 已指向运行副本。所有历史权重和实验保留在开发工作区。
- `.vision` 为现有视觉/GPU解释器环境的新本机位置；`.conda` 仍是通用运行环境。

大权重、TensorRT 引擎、解释器和用户配置不上传 GitHub；新机器需按所选运行模块补齐依赖和模型。开发目录的存在并非主程序运行条件，厨房“回放”按钮属于外部工具入口，使用时需要该开发目录。

这次目录分离不代表已修复历史测试失败、完成日常流程打磨或完成寻路。源码仓库保留当前可运行模块及其实际依赖；在研寻路和开发工具在外部继续推进。
