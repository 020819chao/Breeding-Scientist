# 杂粮育种科学家系统第二轮整改整合报告

> 本文按照《二轮整改.md》的“修改内容—对应文件—改完效果”格式整理。
> 内容覆盖本轮已经完成的代码整改、知识库建设、网页自动化、真实 Session 验证，以及仍需继续完成的边界问题。
>
> 系统定位已经从“谷子假设生成系统”扩展为“面向杂粮作物的六智能体育种科学家系统”。谷子和水稻只是当前已有数据和验证案例，系统目标并不限定于单一作物。

## 0. 本轮整改总体目标

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 将系统运行时统一为六个正式智能体 | [display.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/display.py), [supervisor.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/supervisor.py), [schemas.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/schemas.py) | 系统界面、任务队列、提示词、任务结果和验收逻辑统一使用杂粮育种科学家的六智能体模型 |
| 清理原有独立的 generation、reflection、evolution、ranking、proximity、metareview 运行身份 | 原有模块删除；新实现位于 `co_scientist/agents`、`co_scientist/prioritization` 和 `co_scientist/orchestrator` | 页面和运行日志不再把旧智能体显示成正式智能体；旧能力被重新归属到六个正式智能体内部 |
| 建立面向杂粮而非单一谷子的作物边界 | [config.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/config.py), [crop_kg.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/crop_kg.py) | 可以按作物范围处理谷子、水稻及其他杂粮；每个 Session 按作物进行证据过滤，避免跨作物证据混用 |
| 将知识库、证据图谱、RAG、种质资源和育种任务连接为一条闭环 | [evidence_curator.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/evidence_curator.py), [intake.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/intake.py) | 系统不再只是“生成假设”，而是围绕目标性状建立可追溯的 Breeding Evidence Graph，并将证据传入后续设计、验证、风险和迭代环节 |
| 增加确定性验收边界 | [session_acceptance.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/orchestrator/session_acceptance.py) | Session 完成后可以自动判断知识快照、六智能体、假设闭环、证据包、证据图谱、最终报告和网页页面是否完整 |

## 1. 六个正式智能体统一

本系统最终采用以下六个正式智能体。它们是系统对外展示和运行验收的唯一核心身份。

| 正式名称 | 英文名称 | 主要职责 | 主要输入 | 主要输出 |
| --- | --- | --- | --- | --- |
| 目标解析智能体 | Goal Interpreter | 把用户自然语言转成结构化育种任务 | 作物、目标性状、环境、材料约束、假设数量、成功标准 | Research Plan、作物范围、目标性状、环境条件、终止条件 |
| 证据策展智能体 | Evidence Curator | 统一检索本地知识库、KG、RAG、种质和文献，建立证据网络 | Research Plan、补证据请求、风险缺口、候选路线 | Evidence Package、Breeding Evidence Graph、证据等级、冲突和缺口 |
| 育种设计智能体 | Breeding Designer | 基于证据生成或修订可检验的育种假设 | Evidence Package、目标约束、历史反馈、材料线索 | Hypothesis、机制、亲本路线、标记策略、预期结果、风险假设 |
| 验证规划智能体 | Validation Planner | 把假设转成可操作的验证试验和选择方案 | Hypothesis、证据包、表型协议、田间试验记录 | 表型方案、基因型验证、试验设计、重复数、决策阈值 |
| 风险审查智能体 | Risk Reviewer | 审查遗传、环境、材料、表型、部署和成本风险 | Hypothesis、Evidence Package、Validation Plan | Review、风险等级、反证、证据缺口和 GO/PAUSE/STOP 建议 |
| 迭代编排智能体 | Iteration Orchestrator | 统筹排序、反馈、路线修订、扩展、终止和最终报告 | 所有假设、审查结果、验证计划、风险结果、历史迭代 | 排序结果、保留/修订/扩展/暂停/拒绝决策、下一轮任务、最终报告 |

### 1.1 六个智能体不是简单的固定顺序执行

第一轮存在必要的启动顺序：

```text
Goal Interpreter
        ↓
Evidence Curator（第一轮广度探索 BFRS）
        ↓
Breeding Designer
```

进入闭环后，系统由数据库任务队列驱动，不是机械地从第一个智能体一直排到第六个智能体：

```text
Evidence Curator
        ↓
Breeding Designer
        ↓
Validation Planner + Risk Reviewer
        ↓
Iteration Orchestrator
        ├─ keep：保留路线
        ├─ revise：回到 Evidence Curator / Breeding Designer 补证和修订
        ├─ expand：扩大搜索空间并生成新路线
        ├─ pause：等待本地验证
        └─ reject：终止该路线
```

因此，六个智能体既有第一轮的依赖关系，也有后续的反馈、回流和并行任务。系统真正的核心不是六个名称，而是“证据—假设—验证—风险—决策—再设计”的闭环。

### 1.2 旧能力在六智能体中的重新归属

| 原有能力或旧名称 | 现在的归属 | 当前定位 |
| --- | --- | --- |
| generation | Breeding Designer | 负责初始假设、基于文献的路线和机制设计 |
| reflection | Risk Reviewer | 负责证据审查、反证、风险和缺口 |
| evolution | Breeding Designer + Iteration Orchestrator | 负责修订、简化、组合和扩展路线 |
| ranking | Iteration Orchestrator | 负责综合评分、排序和决策，不再作为独立正式智能体 |
| proximity | 不再作为正式智能体 | 当前系统以作物范围、材料约束和证据图谱路径控制相关性；暂不保留独立 proximity 智能体 |
| metareview | Iteration Orchestrator | 负责反馈汇总、最终报告和闭环收束 |

## 2. 新增和完善杂粮知识库体系

系统知识边界由“三类核心知识源”和“三类结构化支持库”组成。

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 建立种质资源表 | [germplasm.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/germplasm.py), [germplasm_resources_public_seed.csv](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/docs/templates/germplasm_resources_public_seed.csv) | 记录材料名称、Accession ID、作物、性状、可用性、已知基因/QTL、标记、用途、证据和风险 |
| 建立作物知识图谱包 | [crop_kg.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/crop_kg.py), [crop_kg_graph.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/crop_kg_graph.py) | 每种作物可以有独立 KG pack，避免把谷子、水稻或其他杂粮的关系混在一起 |
| 建立本地 RAG 资料库 | [rag.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/rag.py), `data/knowledge/active/rag` | 将论文笔记、实验记录、导师确认资料和项目预检记录切分为可追溯证据块 |
| 接入标记/QTL 库 | [breeding_libraries.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/breeding_libraries.py) | 为基因型验证和 MAS/GS 路线提供结构化依据 |
| 接入表型协议库 | 同上 | 为目标性状、测定时期、测定方法和表型成本提供本地协议 |
| 接入田间试验库 | 同上 | 为重复数、环境、试验设计、历史结果和决策门槛提供本地记录 |
| 增加知识库总体验证 | [validate_knowledge_base.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/scripts/validate_knowledge_base.py) | 可以一次性检查当前活动知识库的目录、CSV、KG、RAG 索引和支持库 |

### 2.1 三类核心知识源

```text
1. Germplasm Resource Table
   种质资源表

2. Crop-pack Knowledge Graph
   按作物组织的知识图谱

3. Local RAG Source Library
   本地论文、实验和项目资料库
```

### 2.2 三类结构化支持库

```text
4. Marker/QTL Library
   标记、基因、QTL、等位变异和可检测性

5. Phenotype Protocol Library
   表型指标、测量协议、时期、成本和标准化要求

6. Field-trial Record Library
   田间试验、环境、重复、处理、结果和风险记录
```

这六类数据共同构成 Evidence Curator 的本地证据边界。系统不会把结构化校验通过误认为生物学结论已经被证明；证据强度、冲突和本地验证缺口仍由 Evidence Curator、Validation Planner 和 Risk Reviewer 进一步判断。

## 3. Evidence Curator 和 Breeding Evidence Graph

本轮最大的系统亮点是将第二个智能体从“资料检索器”提升为证据网络构建者。

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 将本地种质、KG、RAG、标记/QTL、表型协议和田间试验统一接入 | [evidence_curator.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/evidence_curator.py), [evidence.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/tools/evidence.py) | Evidence Curator 可以在一个 Evidence Package 中统一返回六类本地证据 |
| 增加广度图谱探索 BFRS | [evidence_curator.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/evidence_curator.py) | 第一轮从目标性状出发扩展材料、基因/QTL、标记、环境、风险和相关资料，避免过早锁定一条路线 |
| 增加深度证据追踪 DFRS | 同上 | 对候选路线执行“材料 → 性状 → 基因/QTL → 标记 → 文献/RAG → 本地验证 → 风险”的多跳追踪 |
| 构建 Breeding Evidence Graph | Evidence Curator 及其图谱辅助函数 | 证据不再以零散文本返回，而是沉淀为节点、边、来源、证据级别、冲突和验证要求 |
| 增加证据等级 | Evidence Package schema 和 Evidence Curator | 区分本地实验记录、本地 RAG/导师资料、本地 KG、同作物文献、近缘作物文献和模型推断 |
| 增加冲突与证据缺口识别 | Evidence Curator、Risk Reviewer | 主动识别材料不可用、标记未验证、遗传背景不一致、单环境证据、反证和缺少本地验证等问题 |

### 3.1 典型图谱节点

```text
germplasm / 种质材料
trait / 目标性状
gene_qtl / 基因或 QTL
marker / 分子标记
environment / 目标环境
phenotype_protocol / 表型协议
field_trial / 田间试验
rag_evidence / RAG 证据卡
literature / 文献
risk / 风险
hypothesis / 育种假设
```

### 3.2 典型图谱关系

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

### 3.3 Evidence Package 主要输出

```text
1. 候选材料清单
2. 候选基因/QTL/标记清单
3. 关键 KG 路径
4. 本地 RAG 证据及来源位置
5. 外部文献证据及 URL
6. 每条证据的来源等级
7. 冲突证据
8. 证据缺口
9. Breeding Evidence Graph 更新结果
10. 当前知识库批次和 Session 快照 ID
```

## 4. 本地检索工具和证据边界

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 接入 `germplasm_search` | [germplasm.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/tools/germplasm.py), [registry.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/tools/registry.py) | 可以按作物、材料、性状、基因/QTL、标记和用途检索本地种质资源 |
| 接入作物 KG 检索 | [crop_kg.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/tools/crop_kg.py) | 可以检索材料—性状—基因/QTL—标记—环境—风险关系 |
| 接入本地 RAG 检索 | [evidence.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/tools/evidence.py) | 返回 `local-rag://`、source path、行号范围和证据摘录 |
| 保留外部文献检索能力 | 工具注册和证据 Curator 任务提示 | 本地证据不足时仍可请求外部文献，但外部文献必须保留实际 URL 和摘录 |
| 增加作物边界过滤 | Evidence Curator、KG search、RAG scope filter | 水稻 Session 不把谷子关系当成水稻证据，其他杂粮同理 |

## 5. 假设生成、排序与迭代闭环

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 将假设设计重新归属 Breeding Designer | [breeding_designer.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/breeding_designer.py) | 假设必须包含机制、材料、目标性状、标记/基因型方案、表型方案、预期结果和验证边界 |
| 支持修订、扩展、简化和路线组合 | [route_revision.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/route_revision.py) | `revise` 不只是重新生成原假设，而是根据风险和缺口明确修复方向；`expand` 可以扩大候选材料或机制空间 |
| 建立综合育种排序机制 | [composite.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/prioritization/composite.py), [iteration_orchestrator_ranking.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/iteration_orchestrator_ranking.py) | 综合证据匹配、正确性、创新性、可检验性、育种价值、选择可操作性、试验可行性、材料可得性、GxE 风险、表型成本和周期等维度 |
| 保留内部 pairwise calibration 能力 | [pairwise_calibration.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/orchestrator/pairwise_calibration.py), [iteration_orchestrator_ranking.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/iteration_orchestrator_ranking.py) | 两两比较不再是独立的旧 Ranking 智能体，而是 Iteration Orchestrator 的辅助校准信号 |
| 清理旧 ELO 独立模块 | 原 `orchestrator/elo.py` 和旧 tournament repository 删除 | 最终排序不再依赖旧 ELO 系统；pairwise 只用于校准路线相对优先级，最终决策仍由综合育种评分和证据门槛控制 |
| 保留假设生命周期 | [display.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/display.py), hypothesis repository | 假设可以处于 draft、candidate、ready、blocked、rejected、archived 等状态，页面展示统一映射为育种语义 |

### 5.1 综合排序维度

排序不再只看模型偏好或单一 Elo 分数，主要维度包括：

```text
证据匹配度
科学正确性
创新性
可检验性
遗传增益潜力
选择可操作性
田间试验可行性
材料可得性
标记/基因型准备度
GxE 风险
表型成本
育种周期
部署风险
```

### 5.2 迭代决策

```text
keep    保留当前路线，进入优先育种方向
revise  补齐关键证据或修复父本/标记/试验设计
expand  扩大候选材料、机制或环境探索范围
pause   证据不足，等待本地试验或导师确认
reject  存在反证、不可行性或严重风险
```

初始假设数量和最大假设数量由用户输入。系统不会因为“必须增加假设”而无条件扩展；只有 Iteration Orchestrator 根据证据缺口、路线多样性和最大数量约束判断是否需要新增路线。

## 6. 知识批次自动接入

本轮把“手动改三张表、手动改 KG、手动重建 RAG”改成了批次化导入。

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 规定便携式知识批次目录 | [KNOWLEDGE_BATCH_INTAKE.md](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/docs/KNOWLEDGE_BATCH_INTAKE.md), [manifest.json](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/docs/templates/knowledge_intake_batch/manifest.json) | 新数据按照统一目录和 manifest 提交，不需要逐个修改活动文件 |
| 增加批次结构校验 | [intake.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/intake.py), [validate_knowledge_batch.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/scripts/validate_knowledge_batch.py) | 校验路径是否越界、CSV schema、ID 重复、KG 节点/边和 RAG 源目录 |
| 增加稳定 ID 合并 | [intake.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/intake.py) | 旧数据默认保留；相同 `accession_id`、`marker_id`、`protocol_id`、`trial_id` 或 KG 节点/边 ID 会被视为更新 |
| 自动重建 RAG 索引 | [rag.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/rag.py) | 新旧 RAG 资料合并后自动切分、去重和生成统一 evidence index |
| 增加 staging 和原子激活 | [intake.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/intake.py) | 所有校验通过后才替换活动知识库；激活后的二次校验失败会自动回滚 |
| 生成导入报告 | `data/knowledge/active/last_import_report.json` | 可以查看新增、替换、重复、RAG chunk、KG 节点/边和活动校验结果 |
| 生成不可变批次归档 | [versions.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/versions.py) | 每个实际激活批次保存到 `data/knowledge/versions/<batch_id>`，归档内部路径不会指向临时 staging 目录 |

### 6.1 批次导入后的实际逻辑

```text
旧活动知识库 + 新批次
        ↓
隔离 staging
        ↓
manifest / CSV / KG / RAG 校验
        ↓
稳定 ID 合并和重复检测
        ↓
重建 RAG evidence index
        ↓
合并结果二次校验
        ↓
原子激活
        ↓
更新 catalog.json 和 last_import_report.json
```

重要语义：

```text
新批次不是替换整个知识库。
新活动知识库 = 旧数据 + 新增数据 + 相同 ID 的更新版本。
```

## 7. 网页端 ZIP 上传自动化

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 增加网页知识库导入入口 | [app.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/app.py), [knowledge_import.html](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/templates/knowledge_import.html) | 访问 `http://127.0.0.1:7878/knowledge` 即可上传知识批次 |
| 增加 ZIP 隔离解压 | [web_intake.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/web_intake.py) | ZIP 先进入临时目录，不直接写活动知识库 |
| 增加 ZIP 安全边界 | 同上 | 拒绝路径穿越、绝对路径、符号链接、过大压缩包、过多文件和过大的解压结果 |
| 支持仅预检模式 | `knowledge_import.html`, `app.py` | 用户可以先上传并查看结果，不激活当前知识库 |
| 复用现有导入器 | `app.py` 调用 `import_knowledge_batch` | 网页端和命令行使用同一套校验、去重、索引和原子激活逻辑 |
| 显示批次统计 | `knowledge_import.html` | 页面显示批次 ID、是否激活、增加/替换/去重数量和 KG/RAG 统计 |
| 增加批次历史和详情页 | [knowledge_batch_detail.html](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/templates/knowledge_batch_detail.html), `app.py` | 可查看历史批次、处理统计、相对上一批次的数值差异和归档状态 |
| 增加文件 hash 差异 | [versions.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/versions.py), `knowledge_batch_detail.html` | 对两个不可变归档比较新增、替换、删除和未变化文件；排除动态 catalog 和导入报告 |
| 增加安全回滚 | `versions.py`, `app.py` | 仅对完整归档的历史批次提供确认式回滚，并将回滚动作写入 `batch_history` |
| 增加预检审核闸门 | `versions.py`, `intake.py`, `app.py` | 预检包保存在 `pending`，填写审核人和意见后才会正式激活，并写入审核审计字段 |
| 增加 incoming 文件夹监控 | [folder_monitor.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/folder_monitor.py), `config.py`, `app.py` | 服务启动后自动发现稳定 ZIP，复用同一套预检并送入待审核；不自动激活 |
| 增加 processed/quarantine 隔离 | `folder_monitor.py` | 成功预检的 ZIP 进入 processed，重复 hash 或失败 ZIP 进入 quarantine，并生成原因记录 |
| 增加知识库监控中心 | [knowledge_monitor.html](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/templates/knowledge_monitor.html), `app.py` | 集中显示 incoming、待审核、processed、quarantine 四类队列，并支持失败 ZIP 重新预检 |
| 收紧网页直通激活 | `config.py`, `default.toml`, `app.py` | 默认网页上传必须先预检和人工审核；只有显式开启 `allow_direct_activation` 才允许管理员直通 |
| 清理上传临时文件 | `web_intake.py`, `app.py` | 当前请求完成后清理 ZIP 和解压目录，不把临时上传内容混入活动知识库 |

### 7.1 网页使用流程

```text
准备符合模板的知识批次 ZIP
        ↓
打开 /knowledge
        ↓
选择 ZIP
        ↓
勾选“仅预检”并上传
        ↓
确认校验、去重和 RAG 统计
        ↓
取消“仅预检”再次上传
        ↓
批次自动激活
```

当前已经实现网页上传和后台 incoming 文件夹监控。两条入口共用 ZIP 安全边界、批次校验、去重、RAG 重建和 pending 审核流程；文件夹监控只自动预检，不会绕过人工审核直接激活。

监控中心：

```text
http://127.0.0.1:7878/knowledge/monitor
```

普通网页上传默认也会进入待审核；页面上的“仅预检”选项在默认配置下会被系统强制执行。

默认目录：

```text
data/knowledge/incoming/    放入待处理 ZIP
data/knowledge/processed/   预检成功后保存原始 ZIP
data/knowledge/quarantine/  重复或失败 ZIP 及原因 JSON
data/knowledge/pending/     通过预检、等待人工审核的批次包
```

## 8. Session 知识快照和版本追踪

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 新建 Session 时捕获知识快照 | [snapshot.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/snapshot.py), [supervisor.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/supervisor.py) | Session 记录活动批次、知识文件路径、文件大小、SHA256 和快照 ID |
| 将快照写入 Session config snapshot | `sessions.config_snapshot` | 每个 Session 可以知道自己创建时看到的是哪一版知识 |
| 将快照写入 artifact | `artifacts/<session_id>/meta/knowledge_snapshot.json` | 审计、复现和调试时不依赖数据库展示层 |
| Evidence Package 绑定快照 | [evidence_curator.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/evidence_curator.py) | 同一 Session 的证据包必须带有同一个 snapshot ID 和 active batch ID |
| 验收时检查快照是否漂移 | [session_acceptance.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/orchestrator/session_acceptance.py) | 活动知识库被改变后，系统能发现 Session 快照与当前活动版本不一致 |
| 新建和恢复 Session 均绑定不可变运行时副本 | [snapshot.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/knowledge/snapshot.py), [supervisor.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/supervisor.py) | Evidence Curator、KG、RAG、种质表和支持库在 Session 生命周期内都读取快照目录；整改前没有副本的旧 Session 会被明确阻止恢复 |
| 页面显示快照和活动批次 | [session_detail.html](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/templates/session_detail.html), [overview.html](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/templates/overview.html) | 用户可以看到当前 Session 使用的知识库版本 |

### 8.1 新旧知识的版本语义

```text
旧活动知识库：A + B
导入新批次：C，并更新 A

旧 Session：继续看到旧版 A + B
新 Session：看到新版 A + B + C
```

因此，新 Session 使用新快照并不意味着旧数据失效。批次导入是合并式更新，旧记录会进入新活动知识库；只有相同稳定 ID 的记录会以新版本覆盖旧版本。

### 8.2 快照边界和历史 Session 兼容策略

当前已完成 Session 的结果、证据包、图谱和报告不会被新批次改写；新建和恢复的、具有运行时快照的 Session 也不会误读活动知识库：

```text
已完成旧 Session：历史结果稳定
新建 Session：绑定新快照
恢复新快照 Session：强制读取旧快照对应的知识文件
```

对于本轮快照功能上线之前创建的历史 Session，系统没有保存当时知识文件的不可变副本，无法保证恢复时复原历史知识。因此系统不会让这类 Session 悄悄读取当前活动知识库，而是明确提示“缺少不可变知识快照，请新建 Session”。这保证了科学可复现性，代价是极老的 Session 需要从新批次重新开始。

## 9. 前端报告、图谱和知识结果展示

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| Session 详情页展示六智能体状态 | [session_detail.html](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/templates/session_detail.html), [display.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/display.py) | 用户看到的是六个正式智能体，而不是内部任务名称 |
| 增加证据图谱页面 | [evidence_graph.html](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/templates/evidence_graph.html), [evidence_graph.js](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/static/evidence_graph.js) | 可以浏览节点、边、类型、来源和证据路径 |
| 增加路线修订图 | [route_revision_graph.html](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/templates/route_revision_graph.html) | 可以看到父假设、修订路线、扩展路线和当前叶节点 |
| 展示种质资源表 | [session_detail.html](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/web/templates/session_detail.html) | 直接查看材料、Accession ID、用途、来源、风险和证据缺口 |
| 展示排序和迭代决策 | `session_detail.html`, `hypothesis_detail.html` | 可以看到综合分、决策动作、下一步意图和证据状态 |
| 展示 Session 验收结果 | `session_detail.html`, `overview.html` | 用户可以区分“运行完成”和“科学验收通过” |
| 增加知识快照信息 | `session_detail.html`, `overview.html` | 显示 snapshot ID 和 active batch ID，支持追溯 |
| 增加知识库上传页面 | `base.html`, `knowledge_import.html` | 导航栏可直接进入知识批次导入页面 |

## 10. 最终报告和中文审计

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 最终报告要求固定育种决策内容 | [iteration_orchestrator_synthesis.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/agents/iteration_orchestrator_synthesis.py) | 报告必须覆盖作物/种质、目标性状、基因/QTL、表型、基因型、试验设计、风险和来源支持 |
| 自动补充下一轮育种周期 | 同上 | 即使模型没有完整生成，也会明确下一轮需要补的材料、标记、表型和决策门槛 |
| 自动补充 90 天验证计划 | 同上 | 报告不会只停留在概念假设，而会落到近期验证动作 |
| 自动补充育种决策完整性区块 | 同上 | 缺失维度会被明确标注为系统推断或证据缺口，不伪造文献证据 |
| 支持中文标题和中文育种术语 | 同上 | “目标性状、表型测定、基因分型、试验设计、风险、种质”等不会被英文审计器误判为缺失 |
| 忽略系统自身的 audit 说明 | 同上 | 二次审计不会把 `Passed deterministic checks` 当成未经引用的科学断言 |
| 增加中文审计回归测试 | [test_iteration_orchestrator_synthesis_audit.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/tests/unit/test_iteration_orchestrator_synthesis_audit.py) | 中文最终报告审计行为有自动化保护 |

## 11. Session 真实运行验证

### 11.1 已验证的水稻 Session

Session：`ses_01KZ816XGG7NBMMYHYP677RG9D`

查看地址：

```text
http://127.0.0.1:7878/sessions/ses_01KZ816XGG7NBMMYHYP677RG9D
```

| 验证项目 | 结果 |
| --- | --- |
| 作物识别 | rice |
| 活动知识批次 | `rice_2026_08_04_evidence_pack` |
| 知识快照 | `kb_9d8b1c94a7ac4c44268a` |
| 六智能体运行 | 通过 |
| 假设闭环 | 初始 1、最终 1、最大 1，正常保持 |
| Evidence Package | 2 个 |
| 作用域证据 | 129 条 |
| RAG 结果 | 6 条 |
| 证据图谱 | 130 个节点、118 条边 |
| 最终报告审计 | 通过 |
| 网页路由 | 3 个 Session 页面 HTTP 200 |
| Session 终止原因 | `breeding_max_hypotheses_reached`，符合用户设置的最大假设数 |

### 11.2 运行过程中发现并处理的问题

| 问题 | 原因 | 处理结果 |
| --- | --- | --- |
| 第一次小 Session 连接失败 | 外部 DeepSeek API 连接异常 | 使用允许网络访问的运行方式重新验证，后续调用正常 |
| 两个初始假设、0.9 美元预算的 Session 中途停止 | Risk Reviewer 的单智能体预算配额耗尽 | 改为一个初始假设并提高总预算后完成验证；该问题属于预算参数配置，不是知识库错误 |
| 中文最终报告审计失败 | 审计器原本主要使用英文关键词，漏识别中文“目标性状”和“表型测定” | 增加中文术语后重新审计通过 |
| Windows PowerShell 输出中文显示异常 | 终端编码和文件编码显示层不一致 | 文件本身使用 UTF-8，报告审计读取和网页展示按 UTF-8 处理；后续可继续统一终端显示体验 |

## 12. 知识批次网页上传验证

| 验证内容 | 结果 |
| --- | --- |
| 测试批次 | `rice_20260804_demo_upload.zip` |
| 数据来源 | 当前已有水稻知识批次，未编造新数据 |
| manifest | 识别成功 |
| 结构化表 | 种质、标记/QTL、表型协议、田间试验均通过 |
| 水稻 KG | 42 个节点、25 条边 |
| 合并后种质记录 | 36 条 |
| 合并后 RAG chunk | 39 条 |
| RAG 重复检测 | 检测到 1 条重复文档 |
| 预检结果 | 通过 |
| 当前知识库是否被改变 | 否，测试使用了“仅预检”模式 |

网页入口：

```text
http://127.0.0.1:7878/knowledge
```

## 13. 验证脚本和测试

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 增加种质资源验证测试 | `test_germplasm_validation.py` | 防止种质字段、ID 和来源边界回归 |
| 增加 KG 和 RAG 测试 | `test_crop_kg.py`, `test_crop_kg_graph.py`, `test_rag.py` | 防止作物范围、节点边和证据索引回归 |
| 增加 Evidence Curator 测试 | `test_evidence_curator.py` | 验证本地种质、KG、RAG、支持库和图谱输出 |
| 增加知识批次导入测试 | `test_knowledge_batch_validation.py`, `test_knowledge_intake.py` | 验证 manifest、路径安全、合并、去重和激活 |
| 增加网页上传测试 | [test_web_knowledge_intake.py](D:/Develped/Pycharm/PycharmProjects/Co-Scientist-GrainBreeding/co_scientist/tests/unit/test_web_knowledge_intake.py) | 验证网页 ZIP 上传、恶意路径拦截和真实批次导入 |
| 增加快照测试 | `test_knowledge_snapshot.py` | 验证快照生成、文件哈希和知识库漂移检测 |
| 增加六智能体身份测试 | `test_six_agent_runtime_identity.py` | 防止旧 generation/reflection/ranking/proximity 等名称重新进入运行时 |
| 增加 Session 验收测试 | `test_session_acceptance.py` | 验证快照、证据作用域、图谱、报告和网页路由 |
| 增加报告审计测试 | `test_iteration_orchestrator_synthesis_audit.py` | 验证中英文报告、育种完整性和审计修复 |

当前验证结果：

```text
340 passed
ruff check passed
```

## 14. 当前系统已经具备的能力

```text
用户输入杂粮育种目标
        ↓
Goal Interpreter 解析任务边界
        ↓
Evidence Curator 查询种质、KG、RAG、标记/QTL、表型协议和田间记录
        ↓
构建 Breeding Evidence Graph
        ↓
Breeding Designer 生成可检验育种假设
        ↓
Validation Planner 设计表型、基因型和田间验证
        ↓
Risk Reviewer 识别冲突、风险和证据缺口
        ↓
Iteration Orchestrator 综合排序并决定 keep/revise/expand/pause/reject
        ↓
补证、修订、扩展或终止
        ↓
最终报告、图谱、种质资源表和 Session 验收
```

此外，知识侧已经具备：

```text
网页上传 ZIP
→ 自动校验
→ 自动去重
→ 自动合并
→ 自动重建 RAG
→ 自动合并 KG
→ 原子激活
→ 新建 Session 绑定新快照
```

## 15. 尚未完成的整改项

这一部分必须和“已完成内容”区分开，不能在汇报中写成已经完成。

| 待整改内容 | 当前状态 | 下一步要求 |
| --- | --- | --- |
| 历史 Session 的迁移恢复 | 新建 Session 和新快照 Session 的恢复隔离已完成；整改前 Session 没有历史副本 | 当前采取明确阻止恢复策略；如需迁移，可由用户确认后把历史资料重新整理为一个新知识批次 |
| 网页上传历史和批次对比 | 已完成批次历史、详情、数值统计差异、文件 hash 差异和安全回滚 | 后续增加更细的字段级差异展示 |
| 文件夹自动监控 | 已完成基础版和监控中心：稳定 ZIP 自动预检、重复 hash 去重、processed/quarantine 隔离、pending 审核、失败重试 | 后续增加可配置的重试策略、监控任务历史和登录权限控制 |
| 导入前人工审核 | 已完成“预检—审核—激活”三状态、审核人、时间和意见记录 | 后续增加登录身份和权限控制，避免仅依赖表单填写人 |
| 真实多作物数据扩充 | 当前已有谷子和水稻数据，其他杂粮仍需按批次加入 | 按高粱、黍子、荞麦、燕麦、藜麦等作物逐批扩充，不把近缘作物证据直接当作目标作物证据 |
| 外部文献检索稳定性 | 依赖 API、网络和外部服务可用性 | 对失败进行缓存、重试和离线降级，并在报告中显式标注外部检索失败 |
| 运行预算配置 | 小规模 Session 已暴露单智能体预算配额偏紧的问题 | 根据六智能体工作量重新校准预算分配，尤其是 Evidence Curator、Risk Reviewer 和 Iteration Orchestrator |

## 16. 下一阶段建议

### P0：验证并推广快照隔离策略

验收标准：

```text
导入新批次
→ 恢复具有运行时快照的旧 Session
→ Evidence Curator 只能读取旧快照
→ 新 Session 读取新快照
→ 两个 Session 的证据包不会混用
```

本项核心实现已经完成，下一步是继续用多个作物和多个批次做回归验证；整改前没有历史副本的 Session 继续保持“禁止恢复”的保护策略。

### P1：完善知识批次审核和文件级对比

包括：

```text
批次历史和详情                 已完成
当前批次与历史批次数值对比       已完成
新增/替换/去重统计               已完成
文件 hash 对比                  已完成
人工审核记录                    已完成基础版
安全回滚                        已完成
登录身份和权限控制              待完成
```

### P2：使用真实新增数据进行多作物验证

建议顺序：

```text
水稻新增批次
→ 谷子新增批次
→ 高粱/黍子/荞麦等批次
→ 同一目标性状跨环境验证
```

### P3：优化排序和闭环质量

重点检查：

```text
是否真的根据风险生成修订假设
是否会在证据不足时暂停而不是硬生成
是否能在第二轮产生新假设
综合排序是否压过单纯 pairwise 偏好
最终报告是否明确区分文献证据、本地证据和系统推断
```

## 17. 第二轮整改最终结论

本轮整改已经完成了从“旧式假设生成/反思/排序流程”向“杂粮六智能体育种科学家”的主要系统迁移：

```text
旧系统重点：生成假设、反思假设、比赛排序

当前系统重点：
目标解析
→ 证据图谱构建
→ 育种假设设计
→ 验证方案
→ 风险审查
→ 迭代编排和综合排序
→ 知识库版本追踪
→ 可复现 Session 验收
```

当前系统已经可以通过网页接入批量知识，并将旧数据和新增数据合并后提供给新的 Session；已经完成的 Session 保留创建时的证据和知识快照；六智能体闭环和水稻实际运行均已通过验收。

下一阶段的核心不是再增加更多智能体，而是把知识版本隔离、批次审核、真实多作物数据和迭代质量进一步做深，最终形成稳定、可追溯、可复现、面向杂粮育种实际工作的科学家系统。
