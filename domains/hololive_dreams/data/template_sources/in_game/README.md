# 游戏内模板收集

把裁剪图片放在这里，保留原始像素大小，优先 PNG。不要上传整屏作为单个按钮模板，不要缩放、加标记或保留鼠标指针。

- buttons/：可以点击的按钮或图标，如 `quest_button.png`。
- icons/：只用于识别物品、地点或角色的图标，暂不指定点击行为。
- states/：用于判断菜单、加载、弹窗等状态的局部画面。

文件名使用小写英文与下划线。同一图标不同样式可使用不同文件名。建议尽量只裁目标图标，包含少量稳定边缘，避开变化背景和文字数字。

可增加同名 JSON 描述，例如 `buttons/quest_button.json`：

```json
{"notes":"任务入口。仅游戏主界面可点击；按住 Alt 单击，操作后检查任务面板是否出现。","threshold":0.65}
```

JSON 可选字段：name、role、threshold、notes、environments。中文文件名可通过 JSON 中的 name 提供英文标识。role 可为 button/icon/panel/object。environments 默认 hololive_dreams。

详细说明可写入同名 Markdown（如 quest_button.md）：出现在哪个界面、含义、应该做什么、操作后期待看到什么、哪些情况不要点。

放好图片后运行项目根目录 import_game_templates.cmd，或告诉 Agent 已放好。导入会复制图像到 vision_library/images、更新 registry.json、关联 knowledge/templates 下的说明。重复导入不重复注册。导入后重启正在运行的 Agent。

本目录保存原始素材；正式匹配库由导入程序管理，请勿手工移动注册后的图片。JSON 与 Markdown 如有修改，再执行导入；已有知识说明不会被自动覆盖，除非提供同名 Markdown。
