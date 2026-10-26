# 阶段2反摇正常：首份确定周期样本

用户确认画面清晰、边界确定：2564 → 2641帧。按原始捕获时间戳，周期 **1.321591200秒**，平均 **0.756664圈/秒**；帧编号相差77，不能简单除以名义60 FPS。与人工参考1.32秒一致。

本圈含22帧人工绳形、366个点（含两端）。保留原始点击顺序，同时生成按横坐标排序的数据；不补造遮挡绳段。周期进度是时间比例，不能直接视作几何相位或匀速速率函数。

完整导出保存在 `domains/hololive_dreams/data/jump_rope_template_library/annotations/20261006-115004-094950-rope-points-v1.json`。2655帧及4433帧的额外标点保留在原始导出中，未并入本圈；1338帧空记录也保留。原区间标注版本没有被覆盖。

测量数据：`domains/hololive_dreams/data/jump_rope_template_library/stage_2/normal_reverse/samples/20261006-115004-094950-segment-05/measurements.json`。稀疏绳形数据：`domains/hololive_dreams/data/jump_rope_template_library/stage_2/normal_reverse/samples/20261006-115004-094950-segment-05/generated/human_cycle_2564_2641/shapes.json`。未替换实时模型。下一步可用相邻完整周期核验重复性，再拟合几何相位与圈内变速曲线。

## 第二圈确认

用户确认2641 → 2717帧为下一圈。原始时间戳周期1.331854200秒；与第一圈相差10.263毫秒（0.774%）。两圈平均1.326722700秒。周期在这两圈内一致；第二圈仅2655帧有中间绳形标点，尚未核验整圈形态重复，也未作为独立录像验证。

## 第二圈绳形补充

新增14帧标注；原有标点逐项保持一致。第二圈含16帧、270个标点（包含共用起点2641），末帧2716，下一周期边界2717仍使用用户确认，未补造该帧绳形。新版完整导出：`domains/hololive_dreams/data/jump_rope_template_library/annotations/20261006-115004-094950-rope-points-v2.json`；第二圈数据：`domains/hololive_dreams/data/jump_rope_template_library/stage_2/normal_reverse/samples/20261006-115004-094950-segment-05/generated/human_cycle_2641_2717/shapes.json`。此前第二圈标点不足的记录由本节更新；两圈的几何相位对齐与圈内速率函数尚待拟合，未替换实时模型。

## 两圈离线拟合结果

以第一圈训练单调反摇进度曲线，第二圈仅用于检验；共同起点用旧形态库坐标约0.8247锚定。原始时间比例没有直接作为几何相位。第二圈独立形态匹配与第一圈曲线的平均进度差约0.00676圈。

第一圈人工点纵向RMSE约13.45像素，第二圈约15.43像素，匀速基线约113.75像素（720图高换算；仅评估人工可见标点）。这些值不是完整识别准确率。

约束匹配使用513个进度候选、单调前进与弱时间增量约束，节点间线性插值。旧形态库在交界处存在形状歧义，试验导数出现0速平台及约7.42圈/秒尖峰；这些不能解释为真实速度，不能接入实时控制。抽查2588、2634、2655、2706帧叠图，局部形态偏差仍可见。需要先完善形态坐标与交界分支，再重新拟合。

已生成37个标注帧的原图叠加检阅页：`runtime/jump-rope/frame-review/stage2-normal-reverse-fit/index.html`；绿色人工点，橙色第一圈曲线预测。数据保存在`domains/hololive_dreams/data/jump_rope_template_library/stage_2/normal_reverse/samples/20261006-115004-094950-segment-05/generated/two_cycle_fit/fit.json`，复现工具`tools/jump_rope/fit_human_reverse_cycles.py`。节点单调、端点闭合、有限数值、原图引用与模板库结构校验通过。已有数据可继续形态修正，暂不要求额外补录。
