# 系统原则

1. 先检索知识和调用已验证的 Skill；未知情况才升级给 General Agent。
2. Action 后必须重新 Observe 并 Verify。
3. 无匹配 Skill 或验证失败时，不猜测点击，状态标记为 `unknown` / `failure`。
4. 真实计算机控制需要明确的授权和目标窗口白名单。
