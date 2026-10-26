# Skills

一个 Skill 是可独立调用、可验证的能力。新 Skill 必须同时提供：

1. `skill.json`：机器可读 manifest，满足 `docs/schemas/skill-manifest.schema.json`。
2. `implementation.py`：实现 `can_handle`、`execute`、`verify`。
3. `README.md`：人工说明、适用界面、失败模式和验证步骤。
4. 测试：至少覆盖可处理、执行成功、验证失败三个分支。
