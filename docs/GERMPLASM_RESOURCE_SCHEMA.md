# Germplasm Resource Schema

本文档定义第一版“种质资源库”的录入格式。目标不是一次性做成大而全的数据库，而是先把育种方案最需要的材料信息结构化，方便后续接入检索工具和知识图谱。

## 设计原则

1. 每一行对应一个可独立使用或评价的种质材料。
2. 优先记录“育种决策需要的信息”，而不是把所有背景资料都塞进去。
3. 每个重要结论尽量保留来源，避免系统把未验证信息当成事实。
4. 字段保留作物、性状、基因/QTL、标记、环境、可用性等接口，后续可自然转成知识图谱关系。

## 必填字段

| 字段 | 含义 | 填写建议 |
| --- | --- | --- |
| `accession_id` | 材料唯一编号 | 使用课题组内部编号、资源库编号或自定义稳定 ID |
| `name` | 材料名称 | 品种名、品系名、地方品种名、导入系名等 |
| `crop` | 作物 | 如 wheat, foxtail millet, rice, maize |
| `germplasm_type` | 材料类型 | variety, inbred line, landrace, wild relative, mutant, introgression line, RIL, DH, MAGIC 等 |
| `source` | 来源 | 实验室、单位、公开资源库、文献、合作方等 |
| `availability` | 当前是否可用 | available, limited, unavailable, unknown |
| `primary_traits` | 主要相关性状 | 多个性状用分号分隔 |
| `summary` | 一句话摘要 | 说明这个材料为什么值得被系统知道 |

## 强烈建议字段

| 字段 | 含义 | 填写建议 |
| --- | --- | --- |
| `ecological_zone` | 适应生态区或来源环境 | 如 Huang-Huai wheat region, arid northwest China |
| `strengths` | 育种优势 | 抗病、耐旱、高产、优质、早熟、株型好等 |
| `weaknesses` | 明显短板 | 倒伏、品质差、熟期不合适、农艺性状差等 |
| `known_genes_qtls` | 已知基因/QTL/单倍型 | 如 Rht-B1, Ppd-D1, qDTY12.1, SiNF-YC2 Hap-A |
| `markers` | 可用标记 | SNP、KASP、SSR、InDel 或平台信息 |
| `phenotype_evidence` | 表型证据摘要 | 写清性状、年份、环境、指标和大致结论 |
| `genotype_evidence` | 基因型证据摘要 | 写清检测平台、标记、等位变异或数据来源 |
| `breeding_use` | 推荐育种用途 | 亲本选择、回交导入、MAS、GS 训练群体、验证材料等 |
| `risk_notes` | 使用风险 | G×E 风险、连锁累赘、表型不稳定、证据不足等 |
| `source_refs` | 来源引用 | DOI、URL、论文题名、内部报告编号或数据文件名 |

## 可选扩展字段

| 字段 | 含义 |
| --- | --- |
| `pedigree` | 系谱或亲本来源 |
| `population` | 所属群体，如 RIL、DH、association panel |
| `maturity_group` | 熟期或生育期类型 |
| `plant_height` | 株高描述或数值 |
| `yield_level` | 产量表现摘要 |
| `quality_traits` | 品质性状 |
| `stress_tolerance` | 逆境抗性 |
| `disease_resistance` | 病害抗性 |
| `preferred_crosses` | 推荐组合 |
| `avoid_crosses` | 不推荐组合 |
| `data_confidence` | high, medium, low |
| `last_updated` | 最近更新时间，建议 YYYY-MM-DD |
| `notes` | 其他备注 |

## 受控词建议

`availability` 建议使用：

- `available`
- `limited`
- `unavailable`
- `unknown`

`data_confidence` 建议使用：

- `high`: 多环境或多来源证据支持
- `medium`: 有实验或文献证据，但环境/材料范围有限
- `low`: 初步观察、单点数据或未充分验证

`germplasm_type` 建议优先使用英文短语，方便后续检索和图谱关系标准化：

- `variety`
- `inbred line`
- `landrace`
- `wild relative`
- `mutant`
- `introgression line`
- `RIL`
- `DH`
- `MAGIC`
- `association panel`

## 最小录入要求

如果暂时资料不完整，第一批至少填写：

```text
accession_id, name, crop, germplasm_type, source, availability, primary_traits, summary
```

只要这 8 个字段稳定，后续就可以逐步补充基因型、表型、标记和风险信息。

## 后续知识图谱映射

该表后续可抽取成以下关系：

```text
Germplasm -> has_trait -> Trait
Germplasm -> carries_gene_or_qtl -> Gene/QTL
Germplasm -> has_marker -> Marker
Germplasm -> adapted_to -> Environment
Germplasm -> suitable_for -> BreedingUse
Germplasm -> has_risk -> Risk
Germplasm -> supported_by -> Source
```

因此，第一版表格不需要复杂图数据库，但字段应尽量保持稳定、可解析、可追溯。
