# 杂粮育种科学家系统详细说明

> 文档用途：项目汇报、系统设计说明、导师/专家评审材料
>
> 当前系统：六智能体杂粮育种科学家
>
> 文档日期：2026-08-06

## 一、系统概述

### 1.1 系统定位

本系统是一套面向杂粮作物育种科研的 AI 科学家系统。它不是简单的文献问答工具，也不是只负责生成若干段文字的聊天机器人，而是围绕一个具体的育种目标，自动完成以下工作：

1. 理解育种目标和约束条件。
2. 从本地知识库、种质资源库、知识图谱、RAG 证据库和育种资料库中组织证据。
3. 生成多个可比较的育种假设。
4. 将每个假设转成材料、表型、标记、田间试验和杂交验证方案。
5. 识别证据缺口、反证、环境互作风险和材料可得性风险。
6. 通过迭代决策、配对校准和综合评分对路线进行排序。
7. 根据证据缺口自动安排补证、修订、扩展、验证和再评审任务。
8. 输出完整的育种路线、证据链、风险说明和最终育种综述。

系统的核心目标是把“用户提出的育种问题”转化成：

```text
自然语言目标
    -> 结构化育种目标
    -> 证据网络
    -> 多条育种假设
    -> 验证计划
    -> 风险与证据评审
    -> 迭代决策
    -> 路线排序
    -> 可执行育种方案
```

### 1.2 适用对象

系统面向以下类型的杂粮育种问题：

- 谷子、高粱、燕麦、荞麦、黍类、杂豆及其他特色杂粮作物的改良。
- 抗旱、耐盐、耐高温、抗倒伏、早熟、抗病、提高产量和改善品质等目标性状。
- 亲本选择、供体材料筛选、标记辅助选择、QTL 利用、基因型验证和多环境试验设计。
- 需要同时考虑目标性状、产量、环境适应性、材料可得性和育种周期的综合性任务。

系统不是专门针对某一种作物设计的。谷子可以作为典型测试作物，但系统的知识边界、数据接入方式和智能体流程均按“杂粮育种”设计。

### 1.3 当前系统状态

当前版本已经形成以下能力：

- 六个公开智能体角色已经统一。
- 旧系统中的 Generation、Reflection、Ranking、Evolution 等内部名称不再作为对外主角色展示。
- 使用 SQLite 持久化任务队列。
- 支持本地知识库、知识图谱、RAG 和结构化育种资料接入。
- 支持知识批次预检、去重、待审核、激活、版本归档和回滚。
- 每个 Session 绑定知识快照，保证运行过程可追溯。
- 每个智能体的结构化输出可以在网页中查看。
- 每个输出可以进行专家审核，并在“需修改”或“不通过”时自动生成补任务。
- 支持证据图谱和路线修订图谱可视化。
- 假设具备生命周期、证据评审、配对校准、综合排序和终止判断。
- 当前全量自动化测试为 `359 passed`。

当前更准确的定位是：

> 核心功能已经稳定，系统进入页面优化、真实 Session 打磨和科研流程验证阶段。

## 二、总体架构

### 2.1 系统组成

系统由以下几个层次组成：

```text
┌──────────────────────────────────────────────────────────────┐
│                         网页交互层                            │
│ Session 首页、六智能体成果、假设详情、证据图谱、知识管理页面 │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                         Session 控制层                         │
│ Supervisor、任务队列、并发执行、暂停/恢复、终止和最终综述     │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                         六智能体层                             │
│ 目标解析、证据整理、育种设计、验证规划、风险评审、迭代编排     │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                         科学知识层                             │
│ 种质资源、作物 KG、RAG、标记/QTL、表型协议、田间试验、文献    │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                         持久化层                               │
│ SQLite、JSON/Markdown 证据文件、FAISS 向量索引、事件和日志     │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 六智能体不是六次固定顺序调用

六个智能体是系统的六个公开科学角色，但内部执行采用任务队列驱动。

第一轮存在明显的依赖关系：

```text
Goal Interpreter
        │
        ▼
Evidence Curator
        │
        ▼
Breeding Designer
        │
        ├──────────────► Risk Reviewer
        │                       │
        ▼                       ▼
Validation Planner ─────► Iteration Orchestrator
```

第一轮之后不是简单地从第一个智能体走到第六个智能体，而是根据任务结果动态回补：

- 证据不足：重新调用 Evidence Curator。
- 验证计划不完整：重新调用 Validation Planner。
- 风险过高：重新调用 Risk Reviewer 或 Evidence Review 阶段。
- 路线需要修订：重新调用 Breeding Designer。
- 路线需要扩展：生成新的候选假设。
- 排序不稳定：继续进行配对校准。
- 进入终止条件：停止新增任务并生成最终综述。

因此，系统结构是：

```text
初始依赖链 + 并行任务 + 条件回补 + 迭代闭环
```

### 2.3 公开角色和内部执行阶段

| 对外智能体 | 主要内部阶段 |
| --- | --- |
| Goal Interpreter | Goal parsing |
| Evidence Curator | Evidence graph curation |
| Breeding Designer | Hypothesis design、route revision |
| Validation Planner | Validation planning |
| Risk Reviewer | Risk review、evidence review |
| Iteration Orchestrator | Queue decision、pairwise calibration、system feedback、final synthesis |

这样设计的好处是：

- 页面上保持六个清晰的科学角色。
- 内部可以把配对校准、证据复核、路线修订等复杂步骤拆成任务。
- 不会把内部技术阶段误认为新的智能体。
- 后续可以继续优化内部算法，而不破坏公开的六智能体架构。

## 三、六大智能体详解

## 3.1 Goal Interpreter：目标解析智能体

### 角色定位

Goal Interpreter 负责把用户的自然语言育种要求转换成结构化的 `ResearchPlan`。它是一个边界定义智能体，决定后续所有证据检索、假设设计和验证工作的范围。

### 主要输入

- 用户的自然语言育种目标。
- 用户偏好，例如优先考虑田间可验证、标记可操作或本地材料。
- 初始假设数量。
- 最大假设数量。
- 经费预算。
- Session 最大运行时间。

### 解析维度

| 维度 | 说明 |
| --- | --- |
| crop | 作物，例如谷子、高粱、燕麦或荞麦 |
| target_traits | 目标性状，例如抗旱、抗倒伏、产量或品质 |
| target_environments | 目标环境，例如旱地、盐碱地、高温区或多生态区 |
| material_constraints | 材料限制，例如只能使用本地种质资源 |
| preferred_breeding_strategies | 偏好的育种策略 |
| validation_constraints | 验证限制，例如只能进行田间试验或有限分子检测 |
| success_criteria | 成功标准，例如抗性提高且产量不显著下降 |
| initial_hypothesis_count | 初始生成多少条假设 |
| max_hypothesis_count | Session 最多允许多少条假设 |
| local_first | 是否优先使用本地知识和材料 |
| domain_hint | 作物育种领域提示 |

### 主要输出

结构化 `ResearchPlan` 会写入 Session。典型结果如下：

```text
目标作物：谷子
目标性状：抗旱，同时保持产量
目标环境：旱地、少雨区
材料约束：优先使用本地可获得种质
初始假设数：3
最大假设数：8
成功标准：抗旱指标提高，产量损失不超过预设阈值
```

用户在网页或 CLI 中输入的 `initial_hypothesis_count` 和 `max_hypothesis_count` 会覆盖模型的保守推断，但系统会保证初始假设数不超过最大假设数，且并发设计任务会预留名额，避免超过上限。

### 价值

它避免系统一开始就自由发挥。没有目标解析，后续的材料检索、知识图谱搜索和假设设计可能会偏离实际育种问题。

## 3.2 Evidence Curator：证据整理智能体

### 角色定位

Evidence Curator 是系统的证据中枢。它不是简单返回检索文本，而是围绕目标性状建立可追溯的 `Breeding Evidence Graph`，并生成结构化证据包。

### 主要职责

1. 统一调用本地种质资源、作物知识图谱、本地 RAG 和育种资料库。
2. 进行广度探索，扩大候选材料、基因/QTL、标记和环境空间。
3. 对已有路线进行深度证据追踪。
4. 将结果转成证据节点和关系。
5. 标注证据等级、来源、置信度和验证状态。
6. 识别冲突证据和证据缺口。
7. 将证据包写入 Session 目录，供后续智能体使用。

### BFRS：广度证据搜索

第一轮使用 BFRS，即 Breadth-First Route Search。它围绕目标尽量扩大候选空间：

```text
目标性状
  ├── 候选种质材料
  ├── 候选基因/QTL
  ├── 候选分子标记
  ├── 候选目标环境
  ├── 候选表型协议
  ├── 候选田间试验记录
  └── 相关文献或本地 RAG 资料
```

BFRS 的目的是避免一开始锁死在一条路线，保证系统能够生成多个机制不同、材料不同或验证路径不同的候选假设。

### DFRS：深度证据搜索

在某一条路线需要补证时，使用 DFRS，即 Depth-First Route Search。典型追踪路径如下：

```text
育种材料
  -> 目标性状
  -> 基因/QTL
  -> 标记
  -> 文献或本地证据
  -> 本地验证记录
  -> 环境稳定性
  -> 具体风险
```

DFRS 的目标是回答：

> 这条具体育种路线是否已经具备足够完整的证据链，哪些环节还不能直接用于育种决策？

### 当前接入的知识来源

| 来源 | 作用 |
| --- | --- |
| Germplasm CSV | 查询材料、来源、性状线索、可用性和风险 |
| Crop KG pack | 查询作物、材料、性状、基因/QTL、标记和环境关系 |
| Local RAG | 查询论文笔记、实验记录、项目资料和结构化知识卡 |
| Marker/QTL library | 查询标记、QTL、关联性和验证记录 |
| Phenotype protocol library | 查询表型指标、测量方式和协议 |
| Field trial records | 查询环境、重复、试验地点和田间验证信息 |
| External literature tools | 当前主要由工具注册系统提供，Evidence Curator V1 仍然是本地优先 |

当前 Evidence Curator 的 V1 实现是 local-first。它会把外部文献作为证据来源边界写入证据包，但不会在每次本地证据整理时自动完成完整外部文献爬取。外部文献搜索工具可以被具备工具权限的后续智能体调用，这与“Evidence Curator 自动完成全部文献检索”是两个不同层次。

### 证据等级

| 证据等级 | 说明 |
| --- | --- |
| local experiment | 本地实验记录，通常最强 |
| local RAG | 本地论文笔记、实验记录或专家确认资料 |
| local KG | 本地知识图谱中的高置信关系 |
| same-crop literature | 同一作物公开文献 |
| related-crop literature | 近缘作物或类比证据 |
| model inference | 模型推断，必须进入待验证状态 |

### 证据包内容

每次证据整理会生成 JSON 证据包，主要包括：

```text
version
agent
mode
search_strategy
session_id
target_hypothesis_id
knowledge_snapshot_id
knowledge_batch_id
research_goal
queries
local_germplasm
local_crop_kg
local_rag
local_marker_qtl
local_phenotype_protocols
local_field_trials
external_literature
evidence_gaps
breeding_evidence_graph_delta
breeding_evidence_graph_path
downstream_guidance
```

### 证据图节点和关系

典型节点包括育种假设、种质材料、性状、基因/QTL、标记、环境、表型协议、田间试验、RAG 证据块、文献、风险和验证计划。

典型关系包括：

```text
has_trait
carries_gene_or_qtl
has_marker
adapted_to
supported_by
contradicted_by
requires_validation
has_risk
alternative_to
used_in_scheme
```

### 缺口和冲突识别

系统会主动寻找以下问题：

- 材料只有公开记录，但本地库存不可确认。
- 标记在文献中可用，但目标亲本没有本地验证。
- QTL 来自不同遗传背景，不能直接迁移。
- 表型只在单一环境下观察。
- 目标性状提高，但可能牺牲产量或品质。
- 标记和目标性状只有相关关系，没有因果证据。
- 缺少表型协议、田间重复或多环境试验记录。
- 存在反证或对立路线。

## 3.3 Breeding Designer：育种设计智能体

### 角色定位

Breeding Designer 把证据整理成可比较、可验证、可迭代的育种假设，而不是只生成一个标题或一段摘要。

### 主要输入

- 结构化育种目标。
- Evidence Curator 输出的证据包。
- Breeding Evidence Graph。
- 目标作物和环境。
- 材料约束。
- 用户设定的假设数量边界。
- Iteration Orchestrator 给出的修订方向。
- 专家审核产生的修改意见。

### 假设的基本结构

| 字段 | 说明 |
| --- | --- |
| id | 稳定的假设 ID |
| title | 假设标题 |
| summary | 简要机制和育种意义 |
| full_text | 面向科研人员的完整设计卡 |
| strategy | literature、combine、simplify、out_of_box 等 |
| parent_ids | 父路线，用于表示迭代继承 |
| citations | 相关文献和来源 |
| artifact_path | 对应 JSON 产物路径 |
| state | 当前生命周期状态 |
| calibration_score | 配对校准分 |
| pairwise_calibrations_played | 已参与配对次数 |
| dedup_cluster | 去重或近重复聚类标识 |

### 育种设计卡

完整设计卡通常包括：

1. 目标性状和目标环境。
2. 预期机制。
3. 候选亲本或供体材料。
4. 候选基因、QTL 或标记。
5. 杂交、回交或选择策略。
6. 早代选择方法。
7. 表型鉴定指标。
8. 多环境试验方案。
9. 预期遗传增益。
10. 潜在连锁累赘、产量代价和 GxE 风险。
11. 失败后的替代路线。
12. 需要补充的证据。

### 假设数量和迭代扩展

用户可以输入初始假设数量和最大假设数量：

```text
初始假设数量 = N0
最大假设数量 = Nmax
```

第一轮通常生成 `N0` 条路线。后续只有在以下情况下才会生成新路线：

- 迭代决策为 `expand`。
- 现有路线的证据缺口无法通过小修复解决。
- Risk Reviewer 认为需要另一种机制或材料路线。
- 专家审核要求生成替代路线。
- 当前假设数量还没有达到 `Nmax`。

因此，系统可以从初始两条假设迭代到三条或更多，但扩展受 `max_hypothesis_count` 约束，不会无限生成。

### 生成时去重

去重采用两层机制：

1. **确定性 ID 去重**：对 Session、生成来源和核心陈述做规范化后生成稳定 ID。同样的核心假设重复执行时，数据库层面不会重复插入。
2. **语义近重复去重**：将假设摘要向量化后，通过 FAISS 近邻搜索判断和已有路线是否过于相似。相似度超过配置阈值时，认为是近重复路线。

只有成功写入新假设后，才会把它的向量写入 FAISS 和 `embeddings_meta`，保证数据库和向量索引不发生不一致。

## 3.4 Validation Planner：验证规划智能体

### 角色定位

Validation Planner 负责回答：

> 这条育种假设具体要如何验证，使用什么材料、测什么指标、在哪些环境中测、成功标准是什么？

### 主要规划内容

- 亲本和供体材料。
- 杂交组合和回交路径。
- 目标群体或分离群体。
- 标记检测或基因分型方式。
- 表型指标和测量协议。
- 单点或多点田间试验。
- 重复数、环境数和调查时期。
- GxE 评估方式。
- 产量、品质和目标性状之间的联合判定。
- 失败判定和替代路线。

### 验证计划与证据关系

Validation Planner 优先读取对应证据包、Evidence Graph 中的材料和标记关系、本地表型协议、本地田间试验记录，以及 Risk Reviewer 指出的缺口。

如果本地没有对应材料或协议，验证计划会明确标注“待确认”或“待补证”，而不是假装材料已经可用。

### 典型输出

```text
验证假设：某候选标记可以辅助筛选抗旱且不牺牲产量的材料

材料：本地可获得亲本 A、供体 B，以及 BC1F1/BC2F1 群体
标记：候选 CAPS 或 SNP 标记，先做亲本多态性验证
表型：叶片相对含水量、SPAD、产量构成、倒伏和成熟期
环境：正常水、轻度干旱、重度干旱
成功标准：抗旱指标提高，产量下降不超过阈值，标记与表型关联稳定
主要缺口：目标亲本的标记状态和多环境效果尚未确认
```

## 3.5 Risk Reviewer：风险评审智能体

### 角色定位

Risk Reviewer 不是简单判断“好”或“坏”，而是对每条育种路线进行证据强度、可行性、可测试性和部署风险评估。

### 评审维度

#### 科学和证据维度

- 新颖性。
- 正确性或证据吻合度。
- 可测试性。
- 可行性。
- 证据是否来自同一作物。
- 证据是否来自相近遗传背景。
- 是否存在反证。

#### 育种实施维度

- 遗传增益潜力。
- 选择可操作性。
- 田间试验可行性。
- GxE 风险。
- 表型成本。
- 育种周期时间。
- 部署风险。
- 材料可得性。
- 标记或基因型验证难度。

### 评审结论

| 结论 | 含义 |
| --- | --- |
| already_explained | 现有证据已经能够解释该路线 |
| other_more_likely | 另一条路线更有可能 |
| missing_piece | 关键证据缺失，需要补证或修订 |
| neutral | 当前证据不足以明确判断 |
| disproved | 证据或反证不支持继续推进 |

Risk Reviewer 会写入结构化评审记录和评审 Markdown/JSON 产物，包含评审类型、评审结论、各维度分数、支持证据、不确定前提、反证、风险列表、缺口列表和下一步建议。

## 3.6 Iteration Orchestrator：迭代编排智能体

### 角色定位

Iteration Orchestrator 是闭环控制中心。它不只是“最后排序”，还负责根据当前证据和评审状态决定下一步工作。

### 主要职责

1. 汇总 Risk Reviewer、Validation Planner 和 Evidence Curator 的结果。
2. 对路线形成 `keep / revise / expand / pause / reject` 决策。
3. 判断是否需要补证、重做验证计划或生成后继路线。
4. 安排配对校准。
5. 生成系统反馈。
6. 检查是否满足终止条件。
7. 生成最终育种综述。

### 迭代决策示例

```text
评审发现：候选标记只在文献中出现，目标亲本没有验证

动作：revise
父路线：保留原有抗旱机制
修订方向：加入本地亲本多态性验证和多环境表型验证
不能重复：不能只重复引用同一篇标记文献
下一步：Evidence Curator DFRS -> Validation Planner -> Risk Reviewer
```

### 新假设生成判断

Iteration Orchestrator 不会直接凭空决定增加假设数量。它依据以下信息判断：

- 当前路线的证据缺口类型。
- 当前路线是否还有可修复空间。
- 是否存在明显的替代材料或替代机制。
- 当前假设数量是否低于最大数量。
- 当前路线是否已经存在子路线。
- 当前排序池是否需要增加多样性。

如果只是一个标记验证缺口，通常选择 `revise`；如果当前机制或材料路线无法继续验证，才更可能选择 `expand` 并生成新路线。

## 四、知识库和证据基础设施

### 4.1 三类核心知识

系统核心知识库可以概括为三类：

```text
结构化种质资源表
        + 作物知识图谱
        + 本地 RAG 资料库
```

系统同时支持三类育种专项资料库：

- 标记/QTL 库。
- 表型协议库。
- 田间试验记录库。

### 结构化种质资源表

种质表用于回答：

- 这个材料叫什么。
- 是否有 Accession ID。
- 来自哪里。
- 有什么性状线索。
- 能否作为亲本、供体或验证材料。
- 是否存在可得性、环境依赖或材料身份风险。

### 作物知识图谱

作物 KG pack 以节点和边描述作物领域关系，常见节点包括：

- germplasm。
- trait。
- gene/QTL。
- marker。
- environment。
- phenotype protocol。
- field trial。
- literature/evidence。

图谱文件会进行节点 ID、边 ID、端点、类型、证据置信度和作物范围校验。

### 本地 RAG

本地 RAG 主要存储：

- 论文摘要和阅读笔记。
- 本地实验记录。
- 项目资料。
- 专家确认资料。
- 历史育种方案。
- 验证结果。
- 预检和审计资料。

RAG 处理流程为：

```text
资料文件
  -> 文本解析
  -> 文档去重
  -> 分块
  -> 生成 evidence_index
  -> 按目标、作物和性状检索
  -> 返回带 local-rag URI 的证据块
```

RAG 返回的证据块会保留来源文件和行号范围，便于追溯。

## 4.2 知识批次导入流程

系统支持通过网页上传知识批次 ZIP，也支持文件夹监控。

一个知识批次通常包含：

```text
batch.zip
├── manifest.json
├── germplasm_resources.csv
├── marker_qtl_library.csv
├── phenotype_protocol_library.csv
├── field_trial_records.csv
├── kg/
│   └── crop_key.json
└── rag/
    ├── paper_notes.md
    ├── experiment_record.md
    └── project_record.txt
```

`manifest.json` 描述 batch_id、schema_version、crop_scope、每类数据源的相对路径、RAG 资料目录和 KG pack 列表。

### 批次处理阶段

```text
上传 ZIP
   -> 解压
   -> 检查目录和路径
   -> 校验 manifest
   -> 校验 CSV 字段和记录
   -> 校验 KG 节点/边
   -> 建立或更新 RAG 索引
   -> 与已有数据按稳定 ID 合并去重
   -> 生成预检报告
   -> pending_review
   -> 专家/审核人确认
   -> 激活
```

### 预检和去重

系统在替换活动知识库前会检查：

- 文件是否存在。
- 路径是否越界。
- manifest 是否完整。
- CSV 是否包含必需字段。
- Accession ID、marker ID、QTL ID 等是否重复或冲突。
- KG 节点和边是否引用不存在的端点。
- RAG 文件是否可读取。
- RAG 文档是否与已有资料重复。
- 数据是否符合目标作物范围。

失败时批次进入隔离或错误状态，不会替换当前活动知识库。

### 新旧知识如何共存

新批次激活后，不是把旧知识删除。系统通常先将新批次与已有活动数据合并，并保留历史版本：

```text
旧活动知识 + 新批次
       -> 合并、去重、校验
       -> 新的活动知识边界
       -> 旧版本归档
```

因此，新 Session 默认可以同时看到旧知识和新增知识；旧 Session 仍然使用它创建时绑定的知识快照。

## 4.3 知识版本和 Session 快照

### 为什么需要快照

如果 Session 运行过程中直接读取不断变化的活动知识库，会出现以下问题：

- 同一个 Session 前后检索结果不一致。
- 无法解释某条假设当时使用了什么数据。
- 新批次可能中途改变路线排序。
- 复盘和专家评审无法重现。

### 当前机制

Session 创建时会记录 snapshot_id、活动批次 ID、运行时 catalog 路径、种质表路径、KG pack 路径、RAG 索引路径和其他知识源路径。

后续 Evidence Curator 和相关智能体通过 Session 快照访问知识，而不是简单地读取当前目录。

### 版本关系

```text
Version A：旧数据
Version B：旧数据 + 新批次
Version C：Version B + 后续批次

旧 Session -> 固定使用创建时的版本
新 Session -> 使用当前活动版本
```

这样既保证新知识能被后续 Session 使用，也保留了旧 Session 的可复现性。

## 五、任务队列和运行机制

### 5.1 SQLite 持久化队列

系统不是把任务只存在内存中，而是将任务写入 SQLite `tasks` 表。一个任务包含：

- task ID。
- session ID。
- agent。
- action。
- target ID。
- payload。
- priority。
- status。
- created_at、started_at 和 finished_at。
- attempts、lease owner 和 lease expiration。
- last error。
- idempotency key。

### 任务状态

```text
pending
  -> leased
  -> in_progress
  -> done
```

异常状态包括：

- failed：本次任务失败，可能重试。
- dead：超过重试次数，进入死信状态。
- cancelled：Session 暂停、终止或达到终止条件后取消未执行任务。

### 并发执行

Supervisor 使用有界并发 worker pool：

- worker 从 SQLite 中原子领取最高优先级的 pending 任务。
- 使用 lease 防止任务被多个 worker 同时执行。
- 使用 heartbeat 延长长任务租约。
- 默认并发数由配置决定，当前默认值为 4。
- 任务执行结果写回数据库并触发 follow-up 规则。

### 幂等性

系统大量使用 `idempotency_key`，例如：

```text
session_id::evidence_curator::initial
hypothesis_id::risk_reviewer::evidence_review::full
hypothesis_id::validation_planner::review
session_id::mentor_review::output_key::needs_revision
```

这样即使服务重启或任务重试，也不会无限重复创建相同任务。

### 5.2 第一轮任务流程

典型第一轮执行如下：

```text
1. 创建 Session
2. 捕获知识快照
3. Goal Interpreter 解析目标
4. 写入 ResearchPlan
5. 入队 Evidence Curator / BFRS
6. Evidence Curator 生成证据包和证据图谱
7. 根据 N0 入队 N 个 Breeding Designer 任务
8. 生成假设并进行确定性/语义去重
9. 每条新假设进入 Risk Reviewer
10. 进入 Validation Planner
11. 进行证据补充和验证资料整理
12. Risk Reviewer 形成育种风险评审
13. Iteration Orchestrator 形成路线决策
14. keep 路线进入配对校准
15. revise/expand 路线进入修订或扩展
```

### 5.3 任务结果驱动的回补

| 任务结果 | 典型后续任务 |
| --- | --- |
| evidence_curated | 初始设计或 DFRS 验证规划 |
| hypothesis_created | Evidence Review |
| evidence_review_completed | Validation Planner |
| validation_planned | DFRS Evidence Curator 或 post-validation Risk Review |
| risk_reviewed | Iteration Orchestrator |
| iteration_decision/keep | QueuePairwiseCalibration |
| iteration_decision/revise | Breeding Designer 修订路线 |
| iteration_decision/expand | Breeding Designer 扩展候选空间 |
| pairwise_calibration_complete | 更新排序和稳定性快照 |
| queue idle | 触发空闲细化、路线修订或系统反馈 |
| stop condition | 取消 pending 任务并生成最终综述 |

## 六、假设生命周期、排序和闭环

### 6.1 假设生命周期

假设可能经历以下状态：

```text
draft
  -> reviewed
  -> calibration_pool
  -> pinned
```

异常或终止状态包括：

- rejected：不支持继续推进。
- quarantined：证据或风险阻断。
- retired：路线被后继路线替代或归档。

### 6.2 正式入榜条件

一个假设不是生成后立即进入最终排名。当前正式入榜通常需要同时满足：

1. 已经完成证据评审。
2. 迭代决策不是待处理状态。
3. 迭代闸门允许进入排序。
4. 没有处于 rejected、quarantined 或 retired 状态。
5. 达到要求的配对校准次数。
6. 具备有效的校准分。

如果不满足，网页会显示待证据评审、待补证/修订、待配对校准、已暂停、已拒绝或已阻断。

### 6.3 配对校准机制

原来的 Elo 思路没有完全消失，但它不再单独决定育种路线最终价值。

系统仍然使用类似 Elo 的配对校准：

```text
假设 A vs 假设 B
        -> 校准模型判断哪条路线更值得优先
        -> 根据期望胜率和 K 因子更新双方分数
        -> 写入 pairwise_calibration_matches
        -> 更新 hypotheses.calibration_score
```

当前机制具有以下特点：

- 新路线使用较大的 K 因子，允许快速进入排序。
- 成熟路线使用较小的 K 因子，减少分数剧烈波动。
- 新路线、分数接近路线和随机路线混合抽样。
- 可以结合语义相似度和多样性选择对手。
- 每个假设要求达到一定配对次数后，才允许正式入榜。
- 排名稳定性判断会检查连续快照中的 Top-K 顺序和分数变化。

配对校准的作用是帮助比较路线、减少单次绝对评分偏差、让新路线有机会挑战成熟路线，并作为正式排名的稳定性和成熟度条件。

### 6.4 综合育种排序机制

最终排序由综合分数完成，而不是只看 Elo/配对分。

当前综合分数的核心结构是：

```text
raw_score =
    0.35 * evidence_support
  + 0.25 * validation_actionability
  + 0.20 * review_strength
  + 0.20 * risk_control

final_score = raw_score * action_multiplier
              - action_penalty
              - design_card_penalty
```

四个核心维度分别是：

| 维度 | 权重 | 含义 |
| --- | ---: | --- |
| evidence_support | 0.35 | 证据是否充分、直接、可追溯 |
| validation_actionability | 0.25 | 是否能转成实际验证和选择动作 |
| review_strength | 0.20 | 风险评审和证据评审是否支持 |
| risk_control | 0.20 | GxE、材料、成本、部署和失败风险是否可控 |

此外还会考虑当前迭代动作的乘数或惩罚、设计卡完整度、关键字段缺失数量、设计卡惩罚和配对校准成熟度。

这意味着一条配对分高、但证据不完整或验证不可执行的路线，仍然可能无法进入正式优先路线。

### 6.5 两个假设锦标赛是否还需要

当前系统仍然保留配对比较，但其角色已经发生变化：

- 不是唯一排序机制。
- 不是原系统式的独立锦标赛终点。
- 是综合排序的校准、比较和稳定性基础。
- 最终决策还要结合证据、验证、风险和迭代状态。

因此，系统同时具备：

```text
证据科学性 + 育种可执行性 + 风险控制 + 配对相对比较
```

## 七、专家审核机制

### 7.1 页面定位

六智能体成果页面展示每个智能体的结构化输出。每个输出都可以单独提交专家审核：通过、需修改或不通过。

当前专家审核不是 Session 的硬阻塞闸门。未审核时，系统仍可以继续运行；审核主要用于记录专家意见和触发有针对性的补任务。

### 7.2 审核记录

每条审核记录包含：

- review ID。
- Session ID。
- 智能体名称。
- output key。
- artifact path。
- target hypothesis ID。
- 审核状态。
- 审核人。
- 审核意见。
- 创建时间。

最新审核状态会显示在对应输出卡片上，历史审核记录保存在 `agent_output_reviews` 表中。

### 7.3 审核后的自动动作

| 审核结果 | 系统动作 |
| --- | --- |
| 通过 | 保存审核记录，不改变正常队列 |
| 需修改 | 写入 directive feedback，并根据智能体生成补任务 |
| 不通过 | 写入 rejection feedback，并根据智能体生成补任务 |

补任务映射如下：

| 被审核智能体 | 自动补任务 |
| --- | --- |
| Evidence Curator | DFRS 证据整理 |
| Breeding Designer | 以当前路线为父路线重新设计 |
| Validation Planner | 重新规划验证方案 |
| Risk Reviewer | 重新进行完整证据评审 |
| Iteration Orchestrator | 重新形成迭代决策 |
| Goal Interpreter | 记录意见，当前不自动生成目标解析任务 |

### 7.4 人工反馈入口的调整

系统已经移除了网页上的独立“人工反馈”表单，避免 Session 页面、假设详情页和专家审核页出现三套反馈入口。

后端 `SystemFeedback` 机制仍然保留，用于专家审核产生的 directive/rejection、Iteration Orchestrator 产生的系统反馈，以及历史 API 和内部流程兼容。

当前页面交互统一为：

```text
查看六智能体输出
    -> 对具体输出进行专家审核
    -> 需要时自动进入补任务队列
```

## 八、Session 生命周期

### 8.1 创建 Session

创建 Session 时系统会：

1. 创建唯一 Session ID。
2. 保存用户目标和预算。
3. 捕获知识快照。
4. 创建 Session artifact 目录。
5. 调用 Goal Interpreter。
6. 将结构化 ResearchPlan 写回数据库。
7. 入队初始 Evidence Curator 任务。

### 8.2 运行中

运行中系统持续维护：

- 当前 Session 状态。
- 已使用 token 和费用。
- 任务数量和状态。
- 假设数量。
- 评审数量。
- 配对校准次数。
- 最新迭代决策。
- 最新知识快照。
- 实时事件流。

网页通过 SSE 实时接收任务开始、任务完成、假设创建、评审完成和 Session 状态变化。

### 8.3 暂停、恢复和终止

Session 支持 pause、resume 和 abort：

- pause：暂停后续调度。
- resume：继续运行，并回收过期租约。
- abort：外部终止，取消待执行工作。

恢复旧 Session 时必须存在有效的知识快照。没有快照的旧 Session 不会被强行恢复，以免出现知识边界不一致。

## 九、终止条件

系统终止不是只有一个条件，而是多种条件的组合。

### 9.1 资源类终止

- token budget 用尽。
- USD 预算用尽。
- wall clock 时间到期。

### 9.2 排序稳定类终止

当满足以下条件时，可判定优先路线稳定：

- 最近若干次 Top-K 快照的顺序一致。
- 分数变化小于稳定性阈值。
- 已完成最低配对校准次数。
- Top-K 路线的每条假设达到最低配对次数。

### 9.3 育种业务类终止

系统还会检查：

- 是否至少有两条高质量 `keep` 路线达到成功阈值。
- 假设数量是否达到最大上限。
- 是否大部分路线都被暂停或拒绝，说明证据整体受阻。
- 多次迭代后最高综合分仍然偏低，说明继续运行没有明显收益。

### 9.4 终止后的最终综述

达到终止条件后，Supervisor 会取消尚未执行的 pending 任务，保留已完成任务和失败记录，生成最终育种综述，并写入正式路线、证据边界、验证计划、风险和终止原因。

## 十、网页功能结构

### 10.1 Session 列表

展示 Session ID、状态、育种目标、假设数量、预算使用情况和最近更新时间。

### 10.2 新建 Session

用户可以输入：

- 育种目标。
- 偏好。
- 预算。
- 初始假设数量。
- 最大假设数量。
- 最大运行时间。

### 10.3 Session 首页

Session 首页展示：

- 当前 Session 状态。
- 目标解析结果。
- 六智能体执行状态。
- 各智能体输出数量和摘要。
- 假设数量边界。
- 路线排名和待处理路线。
- 配对校准。
- 迭代决策。
- 终止摘要。
- 种质资源表。
- 证据图谱入口。
- 路线修订图谱入口。
- 最终综述入口。
- 实时事件流。

### 10.4 六智能体成果页

该页面是当前系统的重要展示页，展示：

1. 六个智能体的成果链。
2. 每个智能体的目的和输出数量。
3. 结构化字段。
4. 原始 JSON 或 Markdown 产物链接。
5. 每个输出的专家审核状态。
6. 专家审核表单。
7. 补任务触发结果。

### 10.5 假设详情页

展示单条假设的标题和摘要、完整设计卡、亲本和材料、证据来源、评审记录、验证计划、迭代决策、排序和配对校准信息、证据子图以及路线修订关系。

### 10.6 证据图谱页

展示节点和边数量、节点类型筛选、材料/性状/基因-QTL/标记/环境/证据节点、证据关系、关键路径和证据子图。

### 10.7 知识管理页

包括 ZIP 批次上传、预检结果、批次状态、结构化数据统计、RAG 文档统计、KG 节点和边统计、审核人信息、批次激活、历史版本、回滚和文件夹监控状态。

## 十一、数据和文件持久化

### 11.1 SQLite 核心表

当前核心数据表包括：

- `sessions`：Session 和研究计划。
- `hypotheses`：育种假设。
- `reviews`：Risk Reviewer 评审。
- `pairwise_calibration_matches`：假设配对记录。
- `pairwise_calibration_journal`：配对分变更日志。
- `tasks`：持久化任务队列。
- `transcripts`：模型调用和任务过程记录。
- `system_feedback`：系统和专家反馈。
- `agent_output_reviews`：六智能体输出的专家审核。
- `embeddings_meta`：假设向量索引元数据。
- `spans`：运行追踪和耗时信息。
- `events`：Session 事件流。
- `schema_migrations`：数据库迁移记录。
- benchmark 相关表：离线评测和模型比较。

### 11.2 Artifact 文件

每个 Session 都有独立的产物目录：

```text
data/artifacts/<session_id>/
├── meta/
│   └── knowledge_snapshot.json
├── evidence/
│   ├── package_<task_id>.json
│   └── breeding_evidence_graph.json
├── hypotheses/
│   └── <hypothesis_id>.json
├── validation/
│   └── plan_<hypothesis_id>.json
├── risk/
│   └── review_<hypothesis_id>.json
├── iteration/
│   └── decision_<...>.json
└── final/
    └── overview.md
```

数据库保存索引和状态，JSON/Markdown 保存科研产物原文，两者结合实现结构化查询和科研复盘。

## 十二、一次完整 Session 的示例

以“提高谷子旱地抗旱性，同时保持产量”为例：

### 第一步：目标解析

Goal Interpreter 识别：

- 作物：谷子。
- 目标性状：抗旱。
- 保持约束：产量不能显著下降。
- 环境：旱地和少雨区。
- 材料：优先本地种质。
- 初始假设数：例如 3。
- 最大假设数：例如 8。

### 第二步：广度证据探索

Evidence Curator 查询本地耐旱材料、抗旱相关基因/QTL、可用标记、本地田间试验记录、适合旱地的表型协议和 RAG 中的谷子抗旱资料。

它可能发现三类候选路线：

```text
路线 A：利用本地耐旱种质作为供体
路线 B：利用候选 QTL 和标记进行辅助选择
路线 C：通过根系表型和多环境选择提高稳定性
```

### 第三步：假设设计

Breeding Designer 将候选证据组织成三条设计卡，并分别记录候选亲本、目标机制、选择方法、标记或表型方案、产量风险、GxE 风险和需要验证的关键前提。

### 第四步：验证规划

Validation Planner 为每条路线建立亲本和群体、标记多态性、干旱处理等级、田间环境、表型指标、产量构成和成功标准。

### 第五步：风险评审

Risk Reviewer 可能发现：

- 标记在文献中有效，但本地亲本状态未知。
- 抗旱证据来自单一环境。
- 根系性状表型成本较高。
- 产量与抗旱存在潜在权衡。

### 第六步：迭代决策

Iteration Orchestrator 可能给出：

```text
路线 A：keep，进入配对校准
路线 B：revise，先验证亲本标记多态性
路线 C：expand，寻找成本更低的表型替代方案
```

### 第七步：补证和再设计

系统自动安排：

```text
路线 B -> DFRS -> 亲本标记验证 -> 新验证计划 -> 风险复评
路线 C -> 新候选路线设计 -> 去重 -> 重新评审
```

### 第八步：排序和终止

当路线的证据、验证、风险和配对校准达到要求后，系统形成正式排序，并在达到稳定或育种成功条件时生成最终综述。

## 十三、系统的可追溯性

系统的每一条最终路线都可以追溯到：

```text
用户目标
  -> ResearchPlan
  -> Knowledge Snapshot
  -> Evidence Curator Task
  -> Evidence Package
  -> Evidence Graph
  -> Hypothesis Artifact
  -> Validation Plan
  -> Risk Review
  -> Iteration Decision
  -> Pairwise Calibration
  -> Composite Rank
  -> Final Overview
```

每个环节都有对应的 Session ID、Task ID、Hypothesis ID、Artifact path、Knowledge snapshot ID、Evidence source、创建时间、Event record，以及失败和重试信息。

这使系统可以回答：

- 这条假设为什么产生？
- 使用了哪个知识版本？
- 证据来自哪里？
- 哪些证据是本地数据，哪些是公开资料？
- 哪个智能体做了什么？
- 哪个评审导致了路线修订？
- 为什么某条路线排在前面？
- 为什么某条路线没有进入正式排名？
- Session 为什么结束？

## 十四、当前系统优势

### 14.1 从文本生成转向育种科研流程

系统不把“生成假设”作为终点，而是把假设接入证据、验证、风险和迭代。

### 14.2 证据图谱和 RAG 不是孤立组件

种质、KG、RAG、标记、表型和田间记录会被 Evidence Curator 统一整理，并成为后续假设设计和验证计划的输入。

### 14.3 新旧知识可以共存且可追溯

批次激活不会简单删除旧数据，Session 快照保证历史运行可复现。

### 14.4 假设可以迭代增加

系统不是固定生成两条或三条假设，而是根据证据和迭代决策生成修订路线或扩展路线，并受最大假设数量控制。

### 14.5 排序不再依赖单一 Elo

系统将证据支持、验证可操作性、评审强度、风险控制、设计卡完整度和配对校准结合起来，更符合育种决策逻辑。

### 14.6 结果可解释、可审阅

每个智能体输出都能在网页上查看，专家可以对具体输出进行审核，修改意见可以反向驱动任务队列。

### 14.7 任务执行具有工程可靠性

SQLite 队列、任务租约、重试、死信、暂停、恢复、幂等键和事件流共同构成了稳定的运行基础。

## 十五、当前边界和后续优化方向

### 15.1 外部文献检索仍需继续增强

当前 Evidence Curator V1 是本地优先实现。后续可以将 PubMed、Europe PMC、OpenAlex、Crossref 或其他专业文献 API 统一纳入 Evidence Curator 的证据图谱，而不是只让后续工具调用阶段使用。

### 15.2 真实 Session 压力验证仍需增加

当前单元和 Web 测试较完整，但还需要持续验证中等规模和大规模 Session、长时间运行、多个 Session 并行、外部模型超时和限流，以及大批量知识 ZIP 导入。

### 15.3 专家审核暂时不是硬闸门

当前专家审核用于记录意见和触发补任务，不会强制阻塞整个 Session。未来如果项目需要严格科研审批，可以把最终综述发布或正式路线入榜设置为审核相关闸门，但这不属于当前版本的运行规则。

### 15.4 权限和身份体系仍可加强

当前审核人主要通过表单填写。后续可以增加登录身份、专家角色、审核权限、多人会签、审核版本锁定和不可篡改审计。

### 15.5 页面仍可继续优化

下一阶段适合优先打磨：

1. 六智能体成果页的信息密度和布局。
2. Session 首页的重点信息层级。
3. 假设详情页的设计卡展示。
4. 证据图谱的节点筛选和路径高亮。
5. 知识批次审核页面的状态展示。
6. 中文化和旧系统残留文案清理。

## 十六、汇报时可以使用的总结

### 一句话介绍

> 本系统是一套面向杂粮育种的六智能体 AI 科学家系统，它通过知识快照、种质资源、知识图谱、本地 RAG 和结构化育种资料建立可追溯证据网络，再通过育种假设设计、验证规划、风险评审、迭代编排和综合排序，形成可以进入真实育种流程的候选路线。

### 强调系统亮点

1. **六智能体角色清晰**：每个角色有明确职责和结构化输出。
2. **Evidence Curator 是核心亮点**：不是检索文本，而是构建 Breeding Evidence Graph。
3. **知识可持续接入**：ZIP 批次自动预检、去重、RAG 建索引、KG 校验和版本激活。
4. **新旧知识共存**：新 Session 使用合并后的活动知识，旧 Session 使用自己的知识快照。
5. **闭环迭代**：证据缺口会触发补证，评审会触发修订，排序不稳定会继续配对校准。
6. **不是固定顺序执行**：第一轮有依赖顺序，后续由任务队列动态调度。
7. **排序符合育种逻辑**：综合考虑证据、验证、风险、设计完整度和配对比较。
8. **结果可追溯**：从最终路线可以追溯到目标、知识版本、证据、任务和评审。
9. **专家可以介入**：专家审核具体智能体输出，意见可以转化为补任务。
10. **具备工程化基础**：持久化队列、租约、重试、恢复、事件流和数据库迁移保证系统可持续运行。

### 系统最终形态

```text
杂粮育种目标
    -> 目标解析
    -> 证据图谱构建
    -> 多假设设计
    -> 结构化验证
    -> 风险与证据评审
    -> 配对校准与综合排序
    -> 专家审核与补任务
    -> 迭代、扩展和收敛
    -> 可执行的育种路线
```
