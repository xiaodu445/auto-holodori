# 每日任务模板提供说明

本目录被现有vision-import递归导入；配套JSON显式指定role，避免子目录分类不明确。每日调度程序尚未实现，放入并登记模板不等于流程已接通。

## 图片格式

优先PNG；从实际运行游戏窗口原始截图裁剪，保存原始像素，不缩放、不拉伸、不转JPEG。当前目标外框1280×764，外框不等于客户区。裁剪以实际这个窗口尺寸为准；其他尺寸的旧截图只能作为参考样本，不能假定严格原尺寸匹配有效。
裁核心文字/图形并留少量边缘；少带动态背景、动画光效、奖励数量、角色头像及粉色感叹号。通知可裁整条稳定白底文字块，排除右上感叹号。按钮保留可识别的边框/图案；“决定”必须是推荐设置后可用状态。不能修改图片颜色或加字。
不要将PNG文件和JSON不同名。例：buttons/daily_work_claim_all.png 对应已准备的daily_work_claim_all.json。默认阈值0.85为初始配置，实际须用样本验证。

## 首批按钮和条目

- `daily_notice_holowork.png`：通知清单：有些Holowork已经完成啦！。
- `daily_notice_holo_home.png`：通知清单：可以在holo之家领取礼物了。。
- `daily_notice_the_cell.png`：通知清单：可以在The Cell再临领取礼物了。。
- `daily_notice_kaogan.png`：通知清单：可以在颜岩山领取礼物了。。
- `daily_notice_wheel.png`：通知清单：可以游玩恰玛红心大转盘了。。
- `daily_work_claim_all.png`：完成工作页面右下：全部领取。
- `daily_work_claim_summary.png`：工作奖励汇总页右下：领取。
- `daily_work_setup_all.png`：新工作列表右下：统一设置。
- `daily_work_recommend.png`：成员设置页：推荐设置。
- `daily_work_decide.png`：推荐填充后的可用决定按钮；不能用灰暗不可用状态。
- `daily_back.png`：Holowork页面右上蓝色返回箭头，非原生窗口关闭按钮。
- `daily_gift_interact.png`：靠近礼物地点后出现的粉色礼物交互按钮，尽量只裁文字和礼物图案。
- `daily_wheel_interact.png`：转盘现场可按E交互的提示；需要明确区别其他E交互目标。

## 直接复用

attention入口及menu/stage/task自由主界面模板已有，强欲之牌入口和玩法也已有自己的模板，不重复截取。收尾点击任意位置不需要GET!或每种奖励图案模板。

## 后补状态样本

成员推荐填入后、决定可用的整张页面；决定后的工作进行中页面；各地点传送后、礼物/转盘交互前、奖励遮挡与关闭后的整张画面。用于确认状态和防止HUD透过弹窗被误认自由界面。整张样本放data/daily_tasks/samples，不能作为点击目标导入。

原图目标不全时先放已具备部分，无需一次收齐。之后双击项目根目录import_game_templates.cmd导入。通知/交互规则不明时需要用户说明，不凭图片推断完整功能。
