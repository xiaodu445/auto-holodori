# 当前交接

2026-10-26：运行本体与开发工作区已分离。Game_agent 是 GitHub 运行仓库；Game_agent_dev 是开发目录，包含在研寻路、采样标注、训练、测试、打包和完整历史。完成开发后只提升指定运行文件和依赖，不要整树覆盖本体。详见 WORKSPACE_LAYOUT.md。

最初愿景不变：通用模型理解、规划并处理未知情况；可验证的本地技能执行重复任务。通用输入/等待/重试执行在 src/modular_agent/agent，游戏模板和状态流程在 src/modular_agent/domains/hololive_dreams，小游戏领域入口和模型在 domains/hololive_dreams/models。

后续：钓鱼有精力再重做；跳绳保留标注并评估模型和GPU调度；厨房补数据、训练和打磨逻辑；日常优先完善状态、恢复和完成证据。既有未通过项没有因整理目录而消除。

完整历史文档在 Game_agent_dev/docs，当前运行入口见 ../README.md。

开发交接入口：模型能力、计划和受限自纠正见[CAPABILITY_PLANS.md](CAPABILITY_PLANS.md)；奖励识别的现有回调、未实现部分、同帧证据/多页去重/读取后关闭及到账验证约束见[REWARD_RECOGNITION.md](REWARD_RECOGNITION.md)。奖励内容识别尚未实现，不能把接口预留当成已支持功能。离线验证范围见[WORKSPACE_VALIDATION.md](WORKSPACE_VALIDATION.md)，根因及修复记录见[bug-ledger.md](bug-ledger.md)。
