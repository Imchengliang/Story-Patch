# CanonGuard 方法对齐（v0.1）

> **目的修正（2026-10-28）**：本项目的最终目的不是经典 IP 的正典合规/审计，而是“作者卡在某一点时，读取已有故事状态，从语料库（小说/电影剧本等）检索结构上最合适的情节/场景，映射到作者的角色与世界并补全故事”。本文件中的 canon/gap/audit 讨论是前一版理解，保留作为抽取、时序、证据与审计的技术参考；后续以“语料辅助故事补全”为准。

## 0. 结论

**原则：参考这些工作是借设计，不是复现或对标。** 它们与 CanonGuard 的任务目标不同，直接比较指标往往不成立；是否实现某个组件，取决于它是否服务于“缺口诊断 + 受控补全 + 忠实度审计”。

目前有两项工作找到了可核验来源：

- **Andrus et al., AAAI 2022**：*Enhanced Story Comprehension for Large Language Models through Dynamic Document-Based Knowledge Graphs*。
- **NS-ST-GraphRAG**（arXiv:2609.05139）：*Neuro-Symbolic Spatio-Temporal GraphRAG for Literary Knowledge Processing*。

“DeepSeek-R1 从《红楼梦》抽取 20,926 个三元组”暂未找到可核验的论文、代码或数据集。找不到来源就不引用具体数字，也不把它作为必做 baseline。

## 1. 核验状态

| 工作 | 核验状态 | 已核验到的内容 | 对本项目的可用性 |
| --- | --- | --- | --- |
| AAAI 2022 动态文档 KG | 已核验 | 官方论文与 PDF；OpenIE 建动态 KG；Sentence-BERT 检索事实；拼 prompt；LF-SQuAD / LF-QUOREF；故事完成用 PPL | 借“故事内部事实 + KG 条件化 prompt”；不把 PPL 当本项目指标，不要求复现整条管线 |
| NS-ST-GraphRAG | 已核验（arXiv:2609.05139） | 神经符号时空 GraphRAG；双时间坐标（chapter index + narrative-time interval）；空间场景属性；动态子图检索；确定性约束检查；Red-Chamber-QA（104 preliminary + 120 held-out）；机械答案复现 0.733；semantic-judge 0.866；代码/数据录用后开放 | 借 dual temporal / scope retrieval / constraint；不要求复现 QA benchmark 或匹配其分数 |
| 《红楼梦》20,926 三元组 | 未找到可核验公开来源 | 目前只有用户描述：DeepSeek-R1 抽 120 回、跨章关系补全 | 若能找到来源，仅作抽取规模/覆盖率 sanity check；不作为必做 baseline |
| Mahabharata GraphRAG | 可核验为应用 demo | 用 Microsoft GraphRAG 对《摩诃婆罗多》建索引与 global query | 只能借鉴应用模式，不是新研究方法 |
| Humanitext Antiqua | 可核验为产品/系统 | 名古屋大学等开发的古典文本对话系统；RAG + 参考文献出处；新闻提到 22 位作者/约 400 篇文本 | 可借鉴“正典周边知识分层/出处”产品思路；Linked Data 技术细节暂未找到公开论文 |

## 2. 当前实现映射

| 环节 | 当前实现 | 与已核验方法的关系 | 判断：借什么 / 不借什么 |
| --- | --- | --- | --- |
| 实体抽取 | Qwen + JSON Schema + evidence quote 校验 | 通用 LLM 抽取；不是 AAAI 的 OpenIE | 借“故事内部事实”思想；OpenIE 不必复刻 |
| 场景 KG 抽取 | 事件/事实/状态/知识状态/约束，本体约束 + 证据 | 概念上接近“文档内部事实”，但 schema 是自建 | 借本体约束 + 证据；dynamic update 是否值得做待判断 |
| 事实检索 | Neo4j 查询 + 实体名过滤 | 不是 Sentence-BERT 相似度检索 | 实体过滤够用；只有召回明显不足时才引入 embedding |
| Prompt 形成 | 已做故事完成 probe | 借 AAAI 的“facts + story segment” | 借结构；不把 PPL 当验收指标 |
| 故事完成评估 | 单例 design probe | AAAI 用 LF-SQuAD/LF-QUOREF + PPL | 只作设计观察；不复现 benchmark、不强行比效率 |
| 时间/状态 | `story_time`、`discourse_time`、`valid_interval`、`KnowledgeState` | 与 NS-ST 的双时间坐标概念对齐 | 借双时间坐标/scope；不要求复现其 QA 指标 |
| 空间/场景 | `Scene` 有段落范围，`Event.location` 有地点字符串 | 与 NS-ST 的 spatial scene attributes 部分对齐 | 借 location/互斥约束；不强制做 Red-Chamber-QA |
| 事实语义审计 | DeepSeek 异模型 verifier | 自研；不是 FActScore 的正式实现 | 借“审计分层”思想；正式 FActScore 非必需 |
| provenance | `textual_canon / paratext / external_context / inference / adaptation_note` | 受 Humanitext 的“正典周边知识”思路启发 | 借分层；RDF/Linked Data 非 MVP 必需 |

## 3. 对齐计划

### P0：来源核验与引用登记

- 为 AAAI 2022 建 citation 与 PDF 链接。
- 继续查找 NS-ST-GraphRAG、20k triples 的论文/代码/数据；找不到就不写成“已实现依据”。
- 把“可核验/待核验/产品参考”写进项目文档，避免后续误引用。

### P1：AAAI 2022 设计借鉴（可选 probe）

目标：只借其“故事内部事实 + KG 条件化提示”的设计，观察它对我们的续写/审计是否有启发；不追求复现 PPL，也不做效率对标。

1. 用当前 Neo4j 中 `semantic_status='keep'` 的事实作为 document KG facts。
2. 给定前 N 段故事，检索相关事实（先用实体名过滤；只有召回不足时才考虑 Sentence-BERT/embedding）。
3. 形成两个 prompt：
   - baseline：只给故事上下文；
   - KG-augmented：故事上下文 + 相关事实。
4. 用 Qwen 生成后续段落。
5. 用 DeepSeek 做一致性 judge，比较两个续写哪个更符合上下文与事实。
6. 明确标注：这是 **design probe / LLM judge 适配版**；论文用的是 PPL，不是同一指标，也不作为我们的验收基线。

### P2：NS-ST 设计借鉴（已核验 arXiv:2609.05139）

按论文的核心设计挑选可迁移部分；不要求复现 Red-Chamber-QA 或匹配 0.733/0.866。

1. **双时间坐标**：`chapter index`（话语顺序）+ `narrative-time interval`（故事时间）。当前我们已有 `chapter_no` / `scene_index` / `story_time_hint`，但故事时间未规范化；下一步把 `story_time_hint` 归一为可比较的区间，并保留不确定性。
2. **空间场景属性**：给 `Scene` 增加结构化 `location`，并把事件/状态的地点链接到 `Place`；检查同一角色在重叠区间不能出现在两个地点。
3. **动态子图检索**：给定 `chapter range + scene range + story-time interval`，只取在该 scope 内有效的 `Fact/Event/State/KnowledgeState`，而不是整章静态图。
4. **确定性约束检查**：用 z3 对时间区间、地点互斥、知识状态做一致性检查；不可满足时返回 unsat core，而不是让 LLM 猜。
5. **Red-Chamber-QA（可选参考）**：只有当论文数据可用、且问题类型与我们的缺口诊断相关时，才做 adapter；不伪造数字，不强行同口径比较。
6. **Snapshot-plus-delta**：论文把 snapshot+delta 存储列为 limitation；我们当前也是无 snapshot 的章节级事实。是否实现取决于缺口诊断是否需要按时间点解析状态，不为了“对齐”而做。

论文报告的 0.733 机械答案复现 / 0.866 semantic-judge 只作为其 setting 下的参考，不作为我们的验收目标。

### P3：20k triples（可选）

- 只有来源可得且对抽取有帮助时才做；不要求复现 20,926。
- 若做，只看抽取规模、实体覆盖、关系类型、证据质量；不做效率对标。

### P4：Humanitext 正典周边知识层

- 把 `paratext / external_context / adaptation_note` 从普通事实中分离，单独存储与检索。
- 后续可评估是否值得引入 RDF/Linked Data；MVP 先用属性图 + provenance。

## 4. 不做什么

- 不把未核验的 20k triples 写成“已参考”。
- 不把 Mahabharata GraphRAG demo 当成新方法。
- 不把“LLM judge 一致性”冒充论文的 PPL 故事完成指标。
- 不为了“对齐”而实现用不上的模块，也不把不同任务的指标强行对比。
- 不以复现基线为前置条件；schema 和关键设计判断稳定后即可扩 31–35 回。

## 5. P1 design probe（2026-10-28）

已实现并跑通一个单例 design probe（不是 baseline）：

- 章节：第 30 回；上下文：前 8 段；目标：第 9 段。
- 事实：Neo4j 中 18 条 `semantic_status='keep'` 的事实。
- 对比：
  - baseline：只给故事上下文；
  - KG-augmented：上下文 + 18 条事实。
- 生成：Qwen；判定：DeepSeek（异模型 judge）。
- 结果：KG 版胜出，judge confidence 0.88。judge 指出 baseline 有一个内部矛盾（先说“不曾见袭人”，紧接着“袭人见他回来”），KG 版正确使用了怡红院、袭人、宝官/玉官、金钏儿等事实。
- `gold_overlap`：baseline 0.0587，KG 0.0774；两者都低，因为续写是创作而非复述原文。

**这不是 benchmark 结论。** 目前只有一个上下文切分、一个 judge、一个随机顺序；存在位置偏置和单例偶然性。它只作为一个设计信号，不据此声称“KG 增强普遍优于 baseline”。除非后续确实需要判断这个设计是否值得保留，才做多 split、顺序交换或多 judge；不强制扩展成效率对比。

## 6. P2 设计借鉴已落地（2026-10-28）

已实现 NS-ST 的三块可用设计借鉴：

- **双时间坐标**：`TemporalScope` 支持 chapter/scene + `story_order` 范围；`query_scope` 已能在“scene 1–2 + story 30100–30110”下只返回 scene 1 的节点。
- **故事时间归一化**：`normalize_time_hint` 以 chapter/scene/paragraph 为话语基座，叠加“次日 / 夜间 / 午后 / 五月”等显式提示，并为同段事件加顺序偏移；Neo4j 节点写入 `story_order_start/end`、`story_time_label`。
- **结构化 Scene location**：`scenes.location` 已加列并回填（第 30 回：scene 2 = 王夫人上房，scene 3 = 薔薇花架），同时写入 Event 的 `scene_location`。
- **确定性约束检查**：z3 检查区间合法性 + 同一参与者重叠区间的地点互斥；已接到第 30 回 39 个真实事件，最终 `satisfiable=true`。
- **误报修正**：z3 最初报了两个冲突，排查后分别是“大觀園 vs 薔薇花架”的嵌套地点误报、以及同段事件“先提醒齡官、再跑回怡紅院”被压成同一时间点；已分别用 `place_hierarchy` 和同段事件顺序偏移修正。
- **测试**：67 tests 通过；ruff/mypy 通过；`alembic check` 干净。

仍未完成：

- `story_order` 是**叙事顺序代理**，不是真实历法时间；跨回/跨月的精确时间仍需要更强的时间锚定。
- Red-Chamber-QA 数据“录用后开放”，当前只作为可选参考，不要求 adapter，也没有伪造 benchmark 数字。
- snapshot-plus-delta 存储尚未实现；当前仍是章节级事实，不是按叙事时间点解析的状态快照。

工程注意：Alembic autogenerate 曾把 LangGraph 的 checkpoint 表误判为多余表；迁移已修正，`alembic/env.py` 现在忽略 `checkpoint*` 表，checkpoint 表已通过 `PostgresSaver.setup()` 恢复。

下一步：schema 已相对稳定，可以扩 31–35 回；是否补 snapshot-plus-delta 取决于缺口诊断是否真的需要按时间点解析状态。

## 7. 6 回 KG 结果（2026-10-28）

第 30–35 回全部跑通“实体 → 场景 KG → Neo4j → 场景地点 → 事实审计 → 时间/地点检查”。

图谱规模：

| 节点/关系 | 数量 |
| --- | --- |
| Entity | 151（全局注册表 135 个规范实体 + 未知引用） |
| Event | 237 |
| Fact | 173 |
| State | 119 |
| KnowledgeState | 98 |
| Constraint | 30 |
| SpanRef | 71 |
| Evidence 关系 | 662 |

事实审计：

| 章节 | keep | drop | total |
| --- | --- | --- | --- |
| 30 | 18 | 4 | 22 |
| 31 | 20 | 3 | 23 |
| 32 | 18 | 11 | 29 |
| 33 | 20 | 5 | 25 |
| 34 | 22 | 10 | 32 |
| 35 | 22 | 20 | 42 |
| 合计 | 120 | 53 | 173 |

- 跨章实体已合并：`寶玉 → 賈寶玉`、`鳳姐 → 王熙鳳`、`寶釵 → 薛寶釵`；賈寶玉参与的事件覆盖 30–35 回。
- 6 回 z3 时间/地点检查均为 `satisfiable=true`。
- 高 drop 章节是 32（11/29）和 35（20/42）；审计偏保守，下一步应对这两章做人工抽检，校准阈值，而不是直接放宽。

工程上新增：
- [run_chapter_pipeline.sh](file:///Users/imchengliang/Downloads/PhD%20work/Code/Story-Pitch/apps/api/scripts/run_chapter_pipeline.sh)：单章全流程。
- [build_entity_registry.py](file:///Users/imchengliang/Downloads/PhD%20work/Code/Story-Pitch/apps/api/scripts/build_entity_registry.py)：跨章实体注册表。
- [reload_all_chapters.sh](file:///Users/imchengliang/Downloads/PhD%20work/Code/Story-Pitch/apps/api/scripts/reload_all_chapters.sh)：统一实体后重建全部章节，并在 load 后重新应用审计状态。

注意：`load_neo4j` 会删除并重建章节节点，因此**每次 reload 后必须重新 apply 事实审计**；`reload_all_chapters.sh` 已处理这一点。

## 8. Sources

- NS-ST-GraphRAG arXiv abs: https://arxiv.org/abs/2609.05139
- NS-ST-GraphRAG arXiv HTML: https://arxiv.org/html/2609.05139
- AAAI 2022 official page: https://ojs.aaai.org/index.php/AAAI/article/view/21286
- AAAI 2022 PDF: https://ojs.aaai.org/index.php/AAAI/article/view/21286/21035
- AAAI 2022 中文笔记（二手）: https://blog.csdn.net/TgqDT3gGaMdkHasLZv/article/details/140058066
- 53AI 方法摘要（二手）: https://www.53ai.com/news/LargeLanguageModel/2024062881675.html
- Humanitext Antiqua 报道: http://japan.people.com.cn/BIG5/n1/2024/0709/c35421-40274458.html
- Mahabharata GraphRAG 应用 demo: https://techcommunity.microsoft.com/blog/aiplatformblog/the-future-of-ai-graphrag-%E2%80%93-a-better-way-to-query-interlinked-documents/4287182
