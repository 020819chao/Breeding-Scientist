# Breeding Libraries Schema

本文档定义 Evidence Curator 使用的三类本地结构化证据库：

- `marker_qtl_library_template.csv`: 标记、基因、QTL 线索库空白模板
- `phenotype_protocol_library_template.csv`: 表型鉴定协议库空白模板
- `field_trial_records_template.csv`: 田间试验与本地验证记录库空白模板
- 对应的 `*_seed.csv` 文件仅用于系统测试和示例演示

这三张表的目标不是替代文献或真实实验结论，而是让系统能把“可检索资料”变成可追溯的 Breeding Evidence Graph 节点和边。

## Common Rules

每张表都遵循以下原则：

1. 一行代表一个可独立引用的证据对象。
2. 所有 ID 必须唯一，并保持稳定。
3. 多个值建议用英文分号 `;` 分隔，例如 `263A; Jingu21; Zhangza13`。
4. `data_confidence` 只能使用 `high`、`medium`、`low`。
5. `source_refs` 尽量填写 DOI、URL、local-rag URI、内部记录编号或导师确认记录。
6. seed 数据只用于系统测试。真实项目数据需要补充来源、日期、材料可用性和本地验证状态。

推荐证据等级理解：

| `data_confidence` | 含义 |
| --- | --- |
| `high` | 有明确来源，且本地记录、协议或文献支持较强 |
| `medium` | 有线索或部分证据，但材料、环境或验证范围有限 |
| `low` | 初步观察、待验证线索、类比信息或单点记录 |

## Marker/QTL Library

默认文件：

```text
docs/templates/marker_qtl_library_template.csv
```

用途：

记录与育种目标相关的候选标记、候选基因、QTL、检测方法和验证状态。Evidence Curator 会把命中记录转成 `marker_qtl`、`gene_qtl`、`trait`、`germplasm`、`risk` 等节点。

必填字段：

```text
marker_id, crop, trait, gene_or_qtl, marker_name, source_refs, data_confidence
```

字段说明：

| 字段 | 含义 | 填写建议 |
| --- | --- | --- |
| `marker_id` | 标记/QTL 记录唯一 ID | 如 `MQTL-SETARIA-LODGE-001` |
| `crop` | 作物 | 如 `foxtail millet` |
| `trait` | 相关性状 | 多个性状用 `;` 分隔 |
| `gene_or_qtl` | 候选基因、QTL 或区段 | 可写基因名、QTL 名、候选 route |
| `marker_name` | 标记或检测面板名称 | 如 CAPS、KASP、SSR、amplicon panel |
| `marker_type` | 标记类型 | 如 `CAPS`、`KASP`、`SSR`、`SNP_panel` |
| `linked_materials` | 相关材料 | 写 donor、recurrent parent、check 或群体 |
| `validation_status` | 验证状态 | 推荐使用 `validated_local`、`needs_local_parent_preflight`、`testing_seed_local_validation_pending` |
| `assay_protocol` | 检测方法摘要 | 写清 PCR、酶切、测序、芯片或平台 |
| `source_refs` | 来源 | DOI、URL、local-rag URI 或内部记录 |
| `evidence_summary` | 证据摘要 | 一句话说明该标记能支持什么 |
| `risk_notes` | 风险 | 如背景效应、标记不多态、连锁累赘、产量代价 |
| `data_confidence` | 置信度 | `high`、`medium`、`low` |
| `last_updated` | 更新时间 | 推荐 `YYYY-MM-DD` |
| `notes` | 备注 | 标注 seed、真实记录、导师确认等 |

常见图谱映射：

```text
MarkerQTL -> has_trait -> Trait
MarkerQTL -> tags_gene_or_qtl -> Gene/QTL
Germplasm -> has_marker -> MarkerQTL
MarkerQTL -> has_risk -> Risk
```

## Phenotype Protocol Library

默认文件：

```text
docs/templates/phenotype_protocol_library_template.csv
```

用途：

记录某个性状应该如何测、在什么环境测、何时测、如何设置重复、达到什么阈值才算可推进。Evidence Curator 会把命中记录转成 `phenotype_protocol`、`trait`、`environment` 等节点。

必填字段：

```text
protocol_id, crop, trait, measurement_method, decision_thresholds, data_confidence
```

字段说明：

| 字段 | 含义 | 填写建议 |
| --- | --- | --- |
| `protocol_id` | 协议唯一 ID | 如 `PHENO-SETARIA-DROUGHT-001` |
| `crop` | 作物 | 如 `foxtail millet` |
| `trait` | 目标性状 | 如 lodging resistance、drought tolerance |
| `target_environment` | 目标环境 | 如 dense planting nursery、managed drought block |
| `measurement_method` | 测定方法 | 写清指标组合和记录方式 |
| `scale_or_unit` | 量纲或评分尺度 | 如 `1-9 score; percentage; kg/plot` |
| `stage` | 测定时期 | 如 heading、maturity、post-harvest |
| `replication` | 重复与试验设计 | 写 RCBD、重复数、对照材料 |
| `decision_thresholds` | 推进阈值 | 必须写清什么条件下 advance、pause、reject |
| `source_refs` | 来源 | local-rag URI、协议文件、论文或内部记录 |
| `validation_status` | 协议状态 | 如 `local_protocol_ready`、`testing_seed_protocol` |
| `risk_notes` | 协议风险 | 如单季偏差、环境不均一、样本量不足 |
| `data_confidence` | 置信度 | `high`、`medium`、`low` |
| `notes` | 备注 | 可写适用边界 |

常见图谱映射：

```text
PhenotypeProtocol -> validates_trait -> Trait
PhenotypeProtocol -> adapted_to -> Environment
```

## Field Trial Records

默认文件：

```text
docs/templates/field_trial_records_template.csv
```

用途：

记录田间试验、预试验、观察记录或计划中的本地验证记录。Evidence Curator 会把命中记录转成 `field_trial`、`trait`、`environment`、`germplasm`、`risk` 等节点。

必填字段：

```text
trial_id, crop, trait, environment, materials, phenotype_summary, data_confidence
```

字段说明：

| 字段 | 含义 | 填写建议 |
| --- | --- | --- |
| `trial_id` | 试验记录唯一 ID | 如 `TRIAL-SETARIA-LODGE-2026-PRE-001` |
| `crop` | 作物 | 如 `foxtail millet` |
| `trait` | 目标性状 | 多个性状用 `;` 分隔 |
| `environment` | 试验环境 | 如 dense planting nursery、disease nursery |
| `season` | 季节或年份 | 如 `2026 pre-season` |
| `materials` | 材料 | donor、recurrent parent、check、群体或候选材料 |
| `test_design` | 试验设计 | RCBD、亲本预检、温室/田间设置等 |
| `phenotype_summary` | 表型摘要 | 写清已观测什么，或计划记录什么 |
| `genotype_summary` | 基因型摘要 | 写标记检测、测序、未验证状态等 |
| `decision_outcome` | 决策结果 | 推荐使用 `advance`、`pause`、`reject`、`pending_local_validation`、`requires_replicated_trial` |
| `source_refs` | 来源 | local-rag URI、内部试验记录、导师确认资料 |
| `data_confidence` | 置信度 | `high`、`medium`、`low` |
| `risk_notes` | 风险 | 如种子不足、单点环境、病圃逃逸、样本量不足 |
| `notes` | 备注 | 可标注 seed row 或真实记录状态 |

常见图谱映射：

```text
FieldTrial -> observes_trait -> Trait
FieldTrial -> adapted_to -> Environment
FieldTrial -> uses_material -> Germplasm
FieldTrial -> has_risk -> Risk
```

## Validation And Search

校验三张默认库：

```bash
python scripts/validate_breeding_libraries.py
```

只校验某一类：

```bash
python scripts/validate_breeding_libraries.py --kind marker_qtl
python scripts/validate_breeding_libraries.py --kind phenotype_protocol
python scripts/validate_breeding_libraries.py --kind field_trial
```

跨三库检索：

```bash
python scripts/search_breeding_libraries.py "drought tolerance stay-green" --crop "foxtail millet"
```

只检索某一类：

```bash
python scripts/search_breeding_libraries.py blast --kind field_trial --crop "foxtail millet"
```

使用自定义 CSV：

```bash
python scripts/validate_breeding_libraries.py --marker-qtl-csv path/to/marker_qtl.csv
python scripts/search_breeding_libraries.py lodging --marker-qtl-csv path/to/marker_qtl.csv
```

## Evidence Boundary

这三类库进入 Evidence Curator 后，默认是结构化线索，而不是最终证明。

系统可以据此生成假设、补证据、构建证据图和提出验证计划，但最终结论仍需要：

- 本地材料可用性确认
- 标记或基因型本地验证
- 表型协议可执行性确认
- 田间或实验室验证记录
- 文献、导师确认或外部权威来源支撑

如果 `validation_status` 或 `decision_outcome` 包含 `pending`、`needs`、`requires` 等词，Evidence Curator 会把它们转成证据缺口，推动后续智能体进行验证规划或迭代修改。
