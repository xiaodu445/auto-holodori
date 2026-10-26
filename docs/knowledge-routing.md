# 按目录读取 Skill 与 Knowledge

2026-10-02 更新。屏幕报告仍完整；优化的是知识上下文，字符预算不是准确token数。

## 目录范围

- global：knowledge/，包含顶层共享经验。
- domain：domains/<active_domain>/knowledge/，仅当前领域。
- memory：runtime/memory/中的归档经验，排除task_sessions。
- history：runtime/memory/task_sessions/，只有显式请求才读取。
- auto：全局、当前领域与归档经验，默认不含历史任务日志，也不含其他领域。

不移动原文件，不修改模板注册。directory 和 path 必须是项目相对路径，限制在所选scope；拒绝越界、其他领域路径、配置/密钥文件和目录穿越。

## 模型决策

先列目录，不加载全文：
```json
{"decision":"list_knowledge","scope":"domain","directory":"domains/hololive_dreams/knowledge/minigames","limit":20,"offset":0}
```
按目录搜索：
```json
{"decision":"read_knowledge","scope":"domain","directory":"domains/hololive_dreams/knowledge/minigames","query":"强欲之牌 传送","limit":2}
```
按文件分页：
```json
{"decision":"read_knowledge","scope":"domain","path":"domains/hololive_dreams/knowledge/minigames/greed_cards.md","offset":0,"page_chars":2500}
```
响应document.next_offset非空时可读取下一页。标题索引分页最多40项；目录列表只含当页文件的父目录。正文分页最多6000字符。自动启动知识最多2条、总计3000字符；显式搜索默认单条2500、总计10000；最近执行反馈中的文档正文合计10000，上限外标记context_truncated，原磁盘记录不变。

搜索支持中文短语与有限n-gram辅助匹配，不使用联网检索或embedding。搜索只扫描文件前12000字符，长文档用指定文件分页读取；truncated标记表示当前返回是摘录，不能当完整资料。

## Skill

available_skills只携带当前领域技能的名称、描述与调用条件，不加载Skill正文；领域未确定时列出已配置领域入口。list_skills 可指定domain查看其他领域名称。实际调用仍需 use_skill，启动与本地模型的初始条件不变。本实现不提供任意执行磁盘Skill文件的能力。

## 兼容与限制

旧read_knowledge query/limit仍支持。list_knowledge/list_skills是新增决策，模型需重启会话加载提示词。历史日志保留在磁盘，默认不进入请求，避免把旧坐标误当当前目标。其他领域必须显式指定domain后再读。

Knowledge预算只减少知识部分；完整屏幕、模型提示、人工指示等仍占token。当前没有实际API usage统计。本地决策树运行不发大模型请求。
