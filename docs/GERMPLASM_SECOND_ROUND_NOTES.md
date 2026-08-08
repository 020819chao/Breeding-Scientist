# Germplasm Resource Second-Round Notes

本文档总结第二轮围绕“谷子种质资源库”的建设内容。该轮修改目标是先把种质资源变成可校验、可查询、可被智能体调用的数据资产，而不是直接做复杂知识图谱或大规模数据库。

## 本轮完成内容

### 1. 建立种质资源字段规范

新增：

- `docs/GERMPLASM_RESOURCE_SCHEMA.md`
- `docs/templates/germplasm_resources_template.csv`
- `docs/templates/germplasm_resources_example.csv`

字段覆盖：

- 材料编号、名称、作物、类型、来源、可获得性
- 主要性状、生态区、优势、短板
- 基因/QTL、标记、表型证据、基因型证据
- 育种用途、风险、来源引用、数据置信度

第一版最小必填字段为：

```text
accession_id, name, crop, germplasm_type, source, availability, primary_traits, summary
```

### 2. 建立谷子公开示范数据

新增：

- `docs/templates/germplasm_resources_public_seed.csv`
- `docs/GERMPLASM_PUBLIC_SEED_DATA.md`

当前包含 28 条谷子公开数据：

| 数据组 | 记录数 |
| --- | ---: |
| Frontiers 2025 谷子表型评价材料 | 10 |
| ICRISAT Genebank passport 材料 | 10 |
| 谷子耐密植/株型专题材料 | 8 |

专题方向优先覆盖：

- 耐密植
- 株型
- 株高
- 倒伏风险
- 穗部结构
- QTL 作图亲本
- 突变体背景材料

### 3. 增加数据质量校验

新增：

- `co_scientist/knowledge/germplasm.py`
- `scripts/validate_germplasm.py`
- `co_scientist/tests/unit/test_germplasm_validation.py`

校验内容包括：

- CSV 表头是否匹配 schema
- 每行是否为 31 列
- 必填字段是否为空
- `accession_id` 是否唯一
- `availability` 和 `data_confidence` 是否为受控词
- 基因/QTL/标记强断言是否缺少来源或基因型证据

### 4. 增加本地查询能力

新增：

- `scripts/search_germplasm.py`
- `load_germplasm_records`
- `search_germplasm_records`

示例：

```bash
python scripts/search_germplasm.py "lodging architecture" --crop "foxtail millet" --min-confidence medium --limit 5
```

查询结果会返回：

- 材料编号
- 材料名称
- 主要性状
- 数据置信度
- 候选育种用途
- 风险提示
- 来源

### 5. 接入智能体工具系统

新增：

- `co_scientist/tools/germplasm.py`

新增工具：

```text
germplasm_search
```

工具已注册到当前六智能体流程中的以下执行步骤：

- Evidence Curator 的证据取证步骤
- Breeding Designer 的假设设计步骤
- Risk Reviewer 的风险复核步骤
- Iteration Orchestrator 触发的假设修订步骤

未开放给：

- 配对校准 / 综合排序辅助步骤
- 相似度图谱辅助步骤
- 最终报告组装辅助步骤

这样可以让假设设计、风险评审和迭代修订步骤查询候选亲本、donor accession、作图亲本、突变体背景或验证材料线索，同时避免排序辅助步骤和最终报告组装阶段直接把种质线索误当作强证据。

### 6. 明确模型使用边界

已更新的主要实现位置：

- `co_scientist/agents/breeding_designer.py`
- `co_scientist/agents/risk_reviewer.py`
- `config/prompts/breeding_designer_literature.md`
- `config/prompts/risk_reviewer_review.md`
- `config/prompts/breeding_designer_route_feasibility.md`

核心约束：

1. `germplasm_search` 结果只能作为种质资源线索。
2. 不得根据未列出字段编造标记、基因型、可获得性或多环境稳定性。
3. 如果只有 passport 信息，不能声称材料具有已验证目标性状。
4. 如果只有单环境表型，必须标注需要多环境验证。
5. 关键科学结论仍需外部文献证据支持。

### 7. 修复 Windows UTF-8 读取问题

修复：

- `co_scientist/storage/db.py`

数据库初始化读取 `schema.sql` 和 migrations 时改为显式 `encoding="utf-8"`，避免 Windows GBK 环境下测试或初始化数据库失败。

## 当前验证结果

使用环境：

```text
D:\Develped\AssistDevelped\Anaconda\envs\breeding-scientist\python.exe
Python 3.12.13
pytest 9.1.1
```

已通过：

```text
python scripts/validate_germplasm.py
```

结果：

```text
Validated 28 rows in docs\templates\germplasm_resources_public_seed.csv
No issues found.
```

已通过相关单元测试：

```text
python -m pytest co_scientist\tests\unit\test_germplasm_validation.py co_scientist\tests\unit\test_tools_registry.py
```

结果：

```text
12 passed
```

## 当前定位

本轮不是完成最终知识图谱，而是完成知识图谱前置资产：

```text
可信种质资源表 -> 可校验 -> 可查询 -> 可被智能体调用 -> 可追踪来源
```

后续如果继续做知识图谱，可以从当前 CSV 中抽取：

```text
Germplasm -> has_trait -> Trait
Germplasm -> carries_gene_or_qtl -> Gene/QTL
Germplasm -> has_marker -> Marker
Germplasm -> suitable_for -> BreedingUse
Germplasm -> has_risk -> Risk
Germplasm -> supported_by -> Source
```

## 建议下一步

下一步建议做一个极小的真实任务验证：

```text
目标：提出一个谷子耐密植株型改良假设
要求：必须使用 germplasm_search，并至少使用一个外部文献工具
观察：模型是否能把 263A / Chuang 29 / Jingu 21 等材料作为候选线索，同时保留风险和证据边界
```

如果真实 LLM 流程能稳定使用该工具，再进入轻量知识图谱设计。
