# 游戏策略按类别整理（2026-10-26）

最终层级按用户确认：

```text
domains/hololive_dreams/
  launch.json
  daily_tasks_config.json       游戏层日常编排，可调用小游戏
  models/
    fishing/                    钓鱼识别、控制和循环
    greed_cards/                强欲之牌入口及玩法
    jump_rope/                  历史跳绳路线及配置
      experiments/              离线对照实验
    rhythm/                     音游引擎及配置
    README.md
```

共移动 54 个文件。50 个文件字节一致；其余 4 个仅更新资源相对路径、路线文件引用和实验文档链接。日常配置 SHA256 保持 `940502d42cc9dbab138021ce4171db72b286205eb6572139c1f65d4b6e8ec672`，未调整用户选项。

同步更新共享加载器、Agent 文件检查、GUI、根目录启动器、诊断/回放工具、发布源码打包清单、当前文档和测试夹具。历史冻结快照保持原路径及内容，路线索引中的裸文件名相对于新的 `models/jump_rope/`。发布构建目录可在归档后自动重建。

原 `.cmd` 功能入口保留；直接引用旧 `models/<文件名>` 的外部脚本需要改为分类后的路径。未保留重复副本或旧路径转发文件。现有发布 EXE 未重打包，不会自动获得此次源码调整。

人工标注、训练集、原始图像、模型权重、TensorRT 引擎和 Python 环境未移动。当前 YOLO 跳绳基线各文件 SHA256 不变，厨房实现仍在原 `src/`、`learning/` 目录。

## 验证

迁移前同一批相关离线测试为 814 项，5 项失败、2 项报错。迁移后新增 5 项动态加载/配置检查，共 819 项，812 项通过，仍为原有相同 7 个未通过项，没有新增失败：

- `test_claim_tasks.ClaimTests.test_default_unchanged`
- `test_greed_cards_play.GameplayTests.test_hold_fast_path_uses_fresh_boxes_and_skips_rank_matching`
- `test_greed_cards_play.GameplayTests.test_reward_panel_end_confirms_stop_without_duplicate_credit`
- `test_greed_cards_play.GameplayTests.test_template_guess_and_hold_skip_ocr`
- `test_jump_rope_phase.PhaseIntegrationTests.test_route_catalog_links_and_legacy_launchers_exist`
- `test_greed_cards_play.GameplayTests.test_missing_template_midround_budget_and_failure_are_handoffs`
- `test_jump_rope_startup.JumpRopeStartupTests.test_focus_reason_readable_and_launcher_keeps_window`

这些问题在目录调整前已存在，包含缺失的旧启动器和既有行为/测试预期不一致；本次没有改变游戏逻辑来消除它们。逐项日志保存在本机 `models-tests.local.log`，不上传 Git。406 个当前 Python 源文件通过语法解析，新增检查覆盖钓鱼同目录加载、强欲桥接、跳绳阶段资源、音游 GUI 以及游戏层日常配置。没有运行真实游戏或完整 EXE 构建。
