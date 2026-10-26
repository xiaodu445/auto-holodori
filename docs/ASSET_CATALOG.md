# 资源与工具目录

## 本体与开发工具

| 目录 | 职责 | 管理方式 |
| --- | --- | --- |
| `src/`、`gui/` | 通用引擎、GUI | 源码进入 Git |
| `domains/hololive_dreams/` | 游戏逻辑、知识、视觉模板、配置 | 源码及运行小模板进入 Git，原始样本留本地 |
| `config/`、`prompts/`、`knowledge/`、`skills/` | 通用设置、提示、经验和技能定义 | 示例配置进入 Git，个人模型配置除外 |
| `tools/` | 标注、回放、审核、性能诊断、迁移工具 | 保留，按文件名前缀区分模块 |
| `learning/jump_rope_yolo/` | 跳绳运行主线与训练工具 | 源码进入 Git，数据/结果/权重本地保留 |
| `learning/kitchen_yolo/`、`learning/kitchen_points/` | 厨房训练与对照实验 | 保留代码及所有本地数据 |
| `tests/` | 自动回归 | 保留；部分测试需要本地样本 |
| `release/` | 发布构建源码及当前输出 | 构建源码进入 Git，EXE 和构建缓存不上传 |
| `docs/` | 使用说明、设计、历史研究与证据 | 当前入口见 PROJECT_STATUS.md；历史报告不删除 |

根目录启动器按用途保留：`run_*` 为功能入口；`record_*` 为采样；`kitchen_*label*` 为标注；`minimap_*`、`mapping_workbench`、`navigation_editor` 为地图工作台；`analyze_*`、`diagnose_*`、`*review*` 为审核诊断。保留原路径是为了兼容已有快捷方式和脚本。

## 必须保留的训练资料

| 资料 | 路径 | 说明 |
| --- | --- | --- |
| 跳绳标注与切分 | `learning/jump_rope_yolo/datasets/temporal-trial-07/` | 包括 MANIFEST 和 annotations-source-07.json；不可删除 |
| 跳绳原始训练/历史帧 | `runtime/jump-rope/frame-review/` | 原始 JPEG 不以重新解码录像替换 |
| 跳绳标注网页及评估 | `learning/jump_rope_yolo/results/` | 包含人工审阅、失败片段和成绩 |
| 跳绳原录像 | `runtime/jump-rope/recordings/` | 与时间戳一同保留 |
| 跳绳当前权重/引擎 | `learning/jump_rope_yolo/runs/`、`engines/` | 当前为 history-07-late；引擎需按 GPU 重新导出 |
| 跳绳循环模板 | `learning/jump_rope_yolo/loop_assets/` | 当前运行依赖，不是可丢缓存 |
| 厨房人工标注 | `runtime/kitchen/manual-labeling/` | 原始人工标签，含框/关键点等审核结果 |
| 厨房原始录像 | `runtime/kitchen/recordings/` | 后续补标和新类别回溯来源 |
| 厨房导出集与权重 | `learning/kitchen_yolo/datasets/`、`runs/`、`weights/`、`engines/` | 保留快照、实验和对照结果 |
| 厨房运行资源 | `data/kitchen/` | 类别、模板、UI、小样本回归和当前配置；不能整体移走 |
| 其他玩法样本 | `domains/hololive_dreams/data/`、`runtime/rhythm/` 等 | 本地保留，按玩法区分 |

完整个人配置、训练数据、模型和录像须另做外部备份；本次归档与 Git 推送不替代备份。不要直接使用早期迁移脚本备份当前全项目：它只选择当时的跳绳07资产。

## 2026-10-26 可恢复归档

主工程 `release/build/`、`release/verification-cache/`、`release/部署验证 中文 空格 */` 和 `release/中文 空格验证/` 移到同盘 `../workspace-archive/2026-10-26/Game_agent/release/`。保留 `release/output/` 全部现有发布包，未移动任何训练、录像、用户配置和 Python 环境。

本机记录在 `docs/maintenance/`：`archive-moves.local.json` 记录逐目录来源/目标/大小，恢复时将目标目录移回原位置（原位置若已重新构建，先另存新内容）。`protected-assets.local.json` 保存重点标注、图片、模板和数据的 SHA256；`inventory.local.json` 为按目录的体积统计。这些机器专属清单不上传 Git。

运行 `python tools/organize_workspace.py` 可重新生成清单；带 `--archive-release-caches` 时才会移动上述限定的发布缓存。不会删除文件或自动清理数据。
