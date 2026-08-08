本轮修改记录（RAG 接入、preflight 资料卡稳定化、真实 CAPS 标记资料补充）

### 1. 新增本地 RAG 证据层

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 新增轻量级本地 RAG 索引模块，支持从 `docs/rag_sources/` 读取 `.md` / `.txt` 资料并切分成 evidence chunks | [rag.py](co_scientist/knowledge/rag.py) | 系统可以把本地论文笔记、实验预检卡、材料记录变成可检索证据 |
| 新增 `evidence_search` 工具 | [evidence.py](co_scientist/tools/evidence.py) | Evidence Curator、Breeding Designer、Risk Reviewer 和 Iteration Orchestrator 相关步骤可以检索本地 RAG 资料 |
| 新增 RAG 索引构建脚本 | [build_rag_index.py](scripts/build_rag_index.py) | 可以手动重建 `data/rag/evidence_index.json` |
| 新增 RAG 检索脚本 | [search_evidence.py](scripts/search_evidence.py) | 可以在跑 session 前先验证资料是否能被检索到 |
| 在默认配置中加入 RAG source 和 index 路径 | [default.toml](config/default.toml), [config.py](co_scientist/config.py) | 系统知道从哪里读本地资料、在哪里找 RAG 索引 |
| 注册 RAG 工具到工具系统 | [registry.py](co_scientist/tools/registry.py) | agent 工具列表中可以出现 `evidence_search` |

### 2. 增加 RAG 资料模板和工作流

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 新增 RAG 资料模板目录 | [docs/templates/rag](docs/templates/rag) | 后续资料可以按统一格式填入，避免散乱笔记直接进索引 |
| 新增论文证据、种质材料、标记协议、田间观察、专家判断等通用模板 | [paper_evidence_note_template.md](docs/templates/rag/paper_evidence_note_template.md), [germplasm_material_note_template.md](docs/templates/rag/germplasm_material_note_template.md), [marker_protocol_note_template.md](docs/templates/rag/marker_protocol_note_template.md), [field_observation_note_template.md](docs/templates/rag/field_observation_note_template.md), [expert_judgment_note_template.md](docs/templates/rag/expert_judgment_note_template.md) | 不同类型资料有固定字段，模型更容易理解证据边界 |
| 新增 Seita.5G404900/CAPS 专用验证模板 | [seita5g404900_caps_validation_template.md](docs/templates/rag/seita5g404900_caps_validation_template.md) | 专门记录 CAPS 引物、酶切、条带、阳性/阴性对照、GO/PAUSE/STOP |
| 新增三亲本种子材料确认模板 | [seed_material_confirmation_template.md](docs/templates/rag/seed_material_confirmation_template.md) | 专门记录 263A、晋谷21、张杂13 的库存、发芽率、纯度、基因型和花期风险 |
| 新增 RAG 资料填入流程说明 | [RAG_MATERIAL_WORKFLOW.md](docs/RAG_MATERIAL_WORKFLOW.md) | 明确“选模板 -> 填资料 -> 放入 rag_sources -> 重建索引 -> 检索验证 -> 跑小 session”的流程 |
| 更新 RAG 模板指南和 source 目录 README | [RAG_SOURCE_TEMPLATE_GUIDE.md](docs/RAG_SOURCE_TEMPLATE_GUIDE.md), [README.md](docs/rag_sources/README.md) | 空模板不会被误放进 `docs/rag_sources/` 污染索引 |

### 3. 增加 Seita.5G404900/CAPS 相关本地 RAG 资料

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 新增 Seita.5G404900/CAPS 论文证据卡 | [seita5g404900_caps_paper_note.md](docs/rag_sources/seita5g404900_caps_paper_note.md) | 系统知道 263A、Chuang 29、Seita.5G404900、CAPS 标记之间的文献关系 |
| 新增 CAPS 标记协议卡 | [seita5g404900_caps_marker_protocol_note.md](docs/rag_sources/seita5g404900_caps_marker_protocol_note.md) | 系统可检索 CAPS 标记名、引物、酶切、条带和本地复验要求 |
| 新增 263A 种质材料卡 | [263a_germplasm_material_note.md](docs/rag_sources/263a_germplasm_material_note.md) | 系统知道 263A 是半矮秆供体候选，但种子库存和本地适应性仍待确认 |
| 新增晋谷21 / 张杂13材料卡 | [jingu21_zhangza13_lodging_material_note.md](docs/rag_sources/jingu21_zhangza13_lodging_material_note.md) | 系统知道两个轮回亲本有倒伏/茎秆管理背景，但 Seita.5G404900 基因型未知 |
| 新增 90 天密植倒伏验证设计卡 | [dense_lodging_90day_validation_note.md](docs/rag_sources/dense_lodging_90day_validation_note.md) | 系统会把 90 天定位为“启动验证”，而不是完整田间部署验证 |
| 新增 SiNF-YC2 补充证据卡 | [sinfyc2_lodging_note.md](docs/rag_sources/sinfyc2_lodging_note.md) | 系统会把 SiNF-YC2 放在补充/备选方向，不抢 Seita.5G404900 主线 |

### 4. 增加四张 preflight 资料卡

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 新增 CAPS 验证 preflight 卡 | [seita5g404900_caps_validation_preflight_2026-07.md](docs/rag_sources/seita5g404900_caps_validation_preflight_2026-07.md) | final report 会把 CAPS 本地复验作为第一道 GO/PAUSE/STOP 门槛 |
| 新增三亲本种子材料确认 preflight 卡 | [263a_jingu21_zhangza13_seed_confirmation_preflight_2026-07.md](docs/rag_sources/263a_jingu21_zhangza13_seed_confirmation_preflight_2026-07.md) | 系统不会假定 263A、晋谷21、张杂13 种子已经可用，而会要求核实库存、发芽率、纯度和基因型 |
| 新增花期同步和杂交风险 preflight 卡 | [flowering_synchrony_crossing_risk_preflight_2026-07.md](docs/rag_sources/flowering_synchrony_crossing_risk_preflight_2026-07.md) | 系统会显式评估花期重叠、授粉、结实和 F1 种子风险 |
| 新增 BC1F1 首轮表型记录 preflight 卡 | [bc1f1_first_cycle_phenotyping_preflight_2026-07.md](docs/rag_sources/bc1f1_first_cycle_phenotyping_preflight_2026-07.md) | 系统会要求 genotype 与 phenotype 逐株绑定，不只看一个平均株高 |
| final synthesis source map 强制列出四张 preflight 卡 | [iteration_orchestrator_final_synthesis.md](config/prompts/iteration_orchestrator_final_synthesis.md), [iteration_orchestrator_synthesis.py](co_scientist/agents/iteration_orchestrator_synthesis.py) | Iteration Orchestrator 的最终综合不只“用到了”资料卡，还会在来源图谱里清楚列出真实 `local-rag://...#Lx-Ly` URL |

### 5. 补充公开文献中的真实 CAPS 标记资料

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 将 CAPS 标记名补为 `Si5G404900C` | [seita5g404900_caps_marker_protocol_note.md](docs/rag_sources/seita5g404900_caps_marker_protocol_note.md), [seita5g404900_caps_validation_preflight_2026-07.md](docs/rag_sources/seita5g404900_caps_validation_preflight_2026-07.md) | 系统不再只说“CAPS 标记未知”，而能说出具体标记名 |
| 补入正向引物 `GCTGACCGGCTGATTGTGTTCG` | [seita5g404900_caps_marker_protocol_note.md](docs/rag_sources/seita5g404900_caps_marker_protocol_note.md), [seita5g404900_caps_paper_note.md](docs/rag_sources/seita5g404900_caps_paper_note.md) | RAG 可检索到真实 primer 信息 |
| 补入反向引物 `CTCGCGCGGGCACAGGAAG` | [seita5g404900_caps_marker_protocol_note.md](docs/rag_sources/seita5g404900_caps_marker_protocol_note.md), [seita5g404900_caps_paper_note.md](docs/rag_sources/seita5g404900_caps_paper_note.md) | RAG 可检索到完整引物对 |
| 补入限制性内切酶 `ScrF I` | [seita5g404900_caps_marker_protocol_note.md](docs/rag_sources/seita5g404900_caps_marker_protocol_note.md), [seita5g404900_caps_validation_preflight_2026-07.md](docs/rag_sources/seita5g404900_caps_validation_preflight_2026-07.md) | 系统可以提出“PCR + ScrF I 酶切 + 电泳”的本地复验方案 |
| 补入已报道条带：263A 为 `146 bp`，Chuang 29 为 `83 bp + 64 bp` | [seita5g404900_caps_marker_protocol_note.md](docs/rag_sources/seita5g404900_caps_marker_protocol_note.md), [seita5g404900_caps_paper_note.md](docs/rag_sources/seita5g404900_caps_paper_note.md) | 报告能写出公开条带预期，同时仍要求在晋谷21/张杂13上复验 |
| 新增 qPH5-1 / GA20oxSTARP-1 文献卡 | [seita5g404900_qph5_1_starp_marker_literature_note.md](docs/rag_sources/seita5g404900_qph5_1_starp_marker_literature_note.md) | `GA20oxSTARP-1` 可作为 CAPS 失败时的备选标记方向 |

### 6. 调整智能体提示词，让 RAG 资料真正进入推理

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| Breeding Designer prompt 要求使用 `evidence_search` 检索本地资料 | [breeding_designer_literature.md](config/prompts/breeding_designer_literature.md) | 设计假设时会主动查 RAG 资料，不只查网页/文献 |
| Evidence Curator / Breeding Designer prompt 要求同时使用 `germplasm_search` 和 `crop_kg_search` | [breeding_designer_literature.md](config/prompts/breeding_designer_literature.md) | 假设能同时考虑材料、基因/标记、KG 风险线索 |
| Risk Reviewer prompt 要求使用 RAG、种质库和 KG 复核假设 | [risk_reviewer_review.md](config/prompts/risk_reviewer_review.md) | 评审会检查材料可得性、标记 readiness、证据缺口 |
| Iteration Orchestrator 触发的修订 prompts 保留本地 RAG 证据 URL 和边界 | [breeding_designer_route_combine.md](config/prompts/breeding_designer_route_combine.md), [breeding_designer_route_feasibility.md](config/prompts/breeding_designer_route_feasibility.md), [breeding_designer_route_out_of_box.md](config/prompts/breeding_designer_route_out_of_box.md), [breeding_designer_route_simplify.md](config/prompts/breeding_designer_route_simplify.md) | 修订假设不会把 RAG 证据链丢掉 |
| final synthesis prompt 要求区分“公开文献已知”和“本地复验待确认” | [iteration_orchestrator_final_synthesis.md](config/prompts/iteration_orchestrator_final_synthesis.md) | 最终报告不会因为有公开引物就直接说本地可用 |

### 7. 增强最终报告的证据追踪稳定性

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| final synthesis 组装 source context 时优先保留 `preflight` 本地 RAG URL | [iteration_orchestrator_synthesis.py](co_scientist/agents/iteration_orchestrator_synthesis.py) | 四张 preflight 卡不会被普通文献挤掉 |
| final synthesis 直接从 RAG index 注入路线相关 preflight 卡 | [iteration_orchestrator_synthesis.py](co_scientist/agents/iteration_orchestrator_synthesis.py) | 即使前面 agent 漏引用 preflight，最终报告也能拿到真实 `local-rag://source_path#Lx-Ly` |
| 禁止 final repair 阶段发明 `local-rag://preflight/...` 占位 URL | [iteration_orchestrator_synthesis.py](co_scientist/agents/iteration_orchestrator_synthesis.py), [iteration_orchestrator_final_synthesis.md](config/prompts/iteration_orchestrator_final_synthesis.md) | 避免最终报告出现“待创建”的假 RAG 链接 |
| 中英 final audit 均检查必需 section 和重要句子引用 | [iteration_orchestrator_synthesis.py](co_scientist/agents/iteration_orchestrator_synthesis.py), [test_iteration_orchestrator_synthesis_audit.py](co_scientist/tests/unit/test_iteration_orchestrator_synthesis_audit.py) | final report 不是生成完就算成功，而是必须过 audit |

### 8. 增强模型输出异常时的稳定性

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 增加 `_raw_arguments` 恢复逻辑 | [base.py](co_scientist/agents/base.py) | 当 OpenAI-compatible provider 返回超长、截断的 tool JSON 时，系统能尽量恢复 title、statement、mechanism 等关键字段 |
| 为 raw argument 恢复增加测试 | [test_agent_helpers.py](co_scientist/tests/unit/test_agent_helpers.py) | 防止后续改动再次让长假设因 JSON 截断失败 |
| hypothesis 渲染兼容字符串型 `breeding_context` | [breeding_designer.py](co_scientist/agents/breeding_designer.py) | 模型偶尔把 `breeding_context` 返回成字符串时，Breeding Designer 不再崩溃 |
| 为字符串型 `breeding_context` 增加测试 | [test_agent_helpers.py](co_scientist/tests/unit/test_agent_helpers.py) | 提升 session 稳定性 |
| Breeding Designer 输出 token 上限提高 | [breeding_designer.py](co_scientist/agents/breeding_designer.py) | 减少长结构化假设被截断的概率 |

### 9. 增强“育种科学家”项目字段

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| `record_hypothesis` 增加/强化 `donor_parent`、`recurrent_parent`、`material_availability`、`selection_scheme`、`decision_thresholds`、`fallback_route` 等育种字段 | [schemas.py](co_scientist/agents/schemas.py), [breeding_designer_literature.md](config/prompts/breeding_designer_literature.md) | 假设不再只是机制说明，而是更像育种项目卡 |
| review 增加 `material_availability`、`marker_readiness` 等育种评分 | [schemas.py](co_scientist/agents/schemas.py), [risk_reviewer_review.md](config/prompts/risk_reviewer_review.md) | 评审能更直接指出“材料不稳”“标记没 ready” |
| system prompt 强调 plant breeder、field-trial designer、translational crop scientist 视角 | [base.py](co_scientist/agents/base.py) | agent 更偏育种科学家，而不是泛科研综述 |

### 10. 增加阶段说明和基线文档

| 修改内容 | 对应文件 | 改完效果 |
| --- | --- | --- |
| 新增 RAG 第一轮说明 | [RAG_FIRST_PASS_NOTES.md](docs/RAG_FIRST_PASS_NOTES.md) | 记录 RAG 作为本地证据层的定位 |
| 新增 RAG 资料工作流 | [RAG_MATERIAL_WORKFLOW.md](docs/RAG_MATERIAL_WORKFLOW.md) | 后续填资料、重建索引、检索验证有固定操作手册 |
| 新增 RAG 稳定基线说明 | [RAG_BASELINE_STABILITY_NOTES.md](docs/RAG_BASELINE_STABILITY_NOTES.md) | 记录当前稳定 session、preflight 卡、测试结果和剩余真实资料缺口 |
| 新增本轮完整修改记录 | [RAG_AND_CAPS_ROUND_NOTES.md](docs/RAG_AND_CAPS_ROUND_NOTES.md) | 方便交给导师或自己回看本轮到底改了什么 |

### 11. 本轮验证结果

| 验证内容 | 命令 / 文件 | 结果 |
| --- | --- | --- |
| 构建 RAG 索引 | `D:\Develped\AssistDevelped\Anaconda\envs\breeding-scientist\python.exe scripts\build_rag_index.py` | 通过，最新索引为 `31 chunks` |
| 检索 CAPS 标记真实细节 | `python scripts/search_evidence.py "Si5G404900C ScrF I primer 263A Chuang 29"` | 能命中 Si5G404900C、ScrF I、263A/Chuang 29 条带 |
| 检索两条引物 | `python scripts/search_evidence.py "GCTGACCGGCTGATTGTGTTCG CTCGCGCGGGCACAGGAAG"` | 能命中引物所在 RAG 资料 |
| 检索 STARP 备选标记 | `python scripts/search_evidence.py "GA20oxSTARP-1 qPH5-1 Seita.5G404900 STARP marker"` | 能命中新建 STARP 文献卡 |
| RAG 单元测试 | [test_rag.py](co_scientist/tests/unit/test_rag.py) | `2 passed` |
| 核心回归测试 | `pytest test_rag.py test_crop_kg_graph.py test_germplasm_validation.py test_agent_helpers.py test_tool_loop.py test_iteration_orchestrator_synthesis_audit.py test_tools_registry.py` | `47 passed` |
| final synthesis / preflight URL 保护层测试 | [test_agent_helpers.py](co_scientist/tests/unit/test_agent_helpers.py), [test_iteration_orchestrator_synthesis_audit.py](co_scientist/tests/unit/test_iteration_orchestrator_synthesis_audit.py) | `19 passed` |
| 小 session 验证 preflight 真实 URL | `ses_01KY3Q4MJMB3B1WS50PTABGC2Z` | final audit 中英文均 pass，四张 preflight 卡进入来源图谱 |
| 小 session 验证真实 CAPS 资料 | `ses_01KY3R0MRQQGC20W2ZYPTWCSJX` | final audit pass，报告正确写出 Si5G404900C、引物、ScrF I、条带和本地复验待确认 |

### 12. 当前系统能做到什么

| 能力 | 当前效果 |
| --- | --- |
| 本地 RAG 检索 | 能检索本地 `.md` 证据卡，并返回 `local-rag://source_path#Lx-Ly` |
| 证据边界 | 会区分“公开文献已知”和“本地实验待复验” |
| CAPS 标记资料 | 已能使用 Si5G404900C、两条引物、ScrF I、263A / Chuang 29 条带 |
| 本地材料谨慎性 | 不会假定 263A、晋谷21、张杂13 的种子库存、发芽率、纯度已经可用 |
| preflight 资料卡 | final overview 能显式引用 CAPS、种子、花期、BC1F1 表型四张资料卡 |
| 备选标记 | GA20oxSTARP-1 会作为 CAPS 失败时的备选标记方向 |
| SiNF-YC2 定位 | 仍作为补充证据或备选方向，不替代 Seita.5G404900 主线 |
| 报告审计 | final report 需要通过 audit，缺 section 或重要句子无来源会被标记 |

### 13. 仍需注意的问题

| 问题 | 原因 | 当前处理 |
| --- | --- | --- |
| CAPS 公开资料已知，但本地实验未必能直接跑通 | PCR 条件、酶切条件、胶浓度、DNA 质量、亲本多态性都需要本地验证 | 报告统一写成“公开标记已知，本地复验待确认” |
| 晋谷21和张杂13在 Seita.5G404900 位点的基因型未知 | 公开资料主要是 263A / Chuang 29，不等于晋谷21 / 张杂13 | preflight 卡要求在第 1-30 天做本地 CAPS 或测序确认 |
| 种子库存、发芽率、纯度不能由系统补 | 这些是实验室/种质库真实状态，不能凭空生成 | 已保留为待确认项，需要你们本地记录补充 |
| 花期同步风险仍未知 | 需要在同一温室/苗圃条件下实测 | 已建立花期同步 preflight 卡 |
| BC1F1 表型只能作为启动证据 | BC1F1 背景复杂，不能证明稳定抗倒伏或产量中性 | 报告建议后续 BC2/BC1F2、多环境试验继续验证 |
| 网络/API 偶发失败 | session 依赖远程 LLM API | 已通过重试、小预算、小并发方式验证；代码也增加了部分容错 |

### 14. 下一步建议

| 下一步 | 需要补什么 | 补完后的效果 |
| --- | --- | --- |
| 补本地 CAPS 复验记录 | 263A、晋谷21、张杂13 的 PCR 扩增、ScrF I 酶切、电泳图、条带判读、失败记录 | 系统可以判断 CAPS 是否真的 ready |
| 补三亲本种子材料记录 | 库存、批次、来源、发芽率、纯度、储藏条件、权限/分发状态 | 系统可以从“材料待确认”推进到“材料可启动/不可启动” |
| 补花期数据 | 播种日期、出苗、拔节、抽穗、开花、花粉活力、柱头可授期 | 系统可以给出更真实的错期播种和杂交窗口 |
| 补 BC1F1 表型记录表 | plant ID、cross ID、CAPS call、株高、节间、茎粗、倒伏、抽穗、育性 | 系统可以从方案设计进入数据解释 |
| 再跑小 session | 使用真实复验数据重新提问 | 报告会从“启动验证方案”升级为“是否 GO/PAUSE/STOP 的项目判断” |


