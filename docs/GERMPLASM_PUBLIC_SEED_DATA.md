# Public Germplasm Seed Data

本文档说明 `docs/templates/germplasm_resources_public_seed.csv` 的来源、用途和使用边界。该文件是第一版公开种质资源示范数据，主要用于验证“种质资源库”字段设计是否适合 AI Breeding Scientist 后续检索和推理。

## 当前数据范围

当前示范表共 28 条记录，全部为谷子相关公开数据：

| 数据组 | 记录数 | 主要用途 |
| --- | ---: | --- |
| Frontiers 2025 谷子表型评价材料 | 10 | 示例化“具有表型证据的候选材料” |
| ICRISAT Genebank passport 材料 | 10 | 示例化“公开种质库 accession/passport 信息” |
| 谷子耐密植/株型专题材料 | 8 | 示例化“株高、倒伏、穗部结构、QTL 作图和突变体背景材料” |

## 数据来源

### Frontiers 2025 Phenotypic Diversity Study

来源链接：

- https://doi.org/10.3389/fpls.2025.1624252

该组数据来自一项谷子种质表型多样性研究中的公开表格信息。示范表选取了综合评分靠前的 10 个材料，并记录了材料名称、综合表现摘要、株高、穗部相关指标、千粒重、籽粒颜色参数、育种用途和风险提示。

使用时应注意：

1. 这些材料有表型评价依据，但当前示范表只整理了公开论文中可追溯的信息。
2. 表型证据主要来自特定试验环境，不能直接等同于多生态区稳定表现。
3. 表中未填写 `known_genes_qtls` 和 `markers`，因为该来源表格不能证明这些材料已经具备可用分子标记。
4. 这些记录更适合作为“候选亲本或候选验证材料”，不应直接作为最终育种推荐。

### ICRISAT Genebank Passport Records

来源链接：

- https://genebank.icrisat.org/IND/Passport.aspx?Crop=Foxtail+millet

该组数据来自 ICRISAT Genebank 的谷子 passport 页面。示范表选取了若干 `ISe` accession，并记录了 accession 编号、地方名、来源国家/地区、材料类型和公开 passport 摘要。

使用时应注意：

1. Passport 记录主要说明材料身份、来源和保存信息。
2. Passport 信息通常不等同于具体育种性状证据。
3. 这些 accession 适合用于扩展遗传多样性线索，但在推荐为亲本前需要额外表型和基因型验证。
4. 当前表中 `data_confidence` 标为 `low`，是因为缺少本项目目标性状下的直接证据。

### Foxtail Millet Dense-Planting And Architecture Topic

该组数据围绕谷子密植适应、株型、株高、倒伏风险、穗部结构和 QTL 作图补充了 8 条公开材料线索：

- `263A`
- `Chuang 29`
- `Jingu 21`
- `Zhangza 13`
- `Yugu1`
- `Longgu7`
- `Hongmiaozhangu`
- `Changnong35`

来源包括谷子株高基因研究、硅肥调控倒伏研究、高密度遗传图谱和 RAD-seq QTL 研究。

使用时应注意：

1. `263A` 的半矮秆信息和 `Seita.5G404900` 相关证据来自公开株高遗传研究，适合做株高/倒伏风险相关候选线索。
2. `Chuang 29` 在当前表中作为高秆对照亲本和精英背景线索，不应直接当作耐密植材料。
3. `Jingu 21` 和 `Zhangza 13` 来自硅肥管理研究，当前证据说明管理处理影响倒伏相关性状，不等于材料本身具有稳定遗传抗倒伏性。
4. `Yugu1`、`Longgu7`、`Hongmiaozhangu`、`Changnong35` 主要是作图亲本或突变体背景线索，后续用于 MAS 或亲本推荐前必须抽取具体 QTL、标记和有利等位变异。
5. 这些记录适合驱动模型提出“验证方案”和“候选材料线索”，不适合直接输出为最终商业化育种组合。

## 字段使用边界

| 字段 | 当前解释 |
| --- | --- |
| `availability` | 公开来源通常不能证明本课题组可直接获得材料，因此暂填 `unknown` |
| `primary_traits` | 表示该记录当前与哪些性状或用途相关，不代表已完成育种验证 |
| `strengths` | 来自公开表型或 passport 信息的候选优势 |
| `weaknesses` | 根据表型特征或证据不足推断出的使用限制 |
| `phenotype_evidence` | 仅记录来源中能追溯到的表型信息 |
| `genotype_evidence` | 没有公开标记或测序证据时明确写为未确认 |
| `breeding_use` | 是候选用途，不是最终推荐 |
| `risk_notes` | 用来提醒模型保守使用材料，避免过度外推 |
| `data_confidence` | 反映当前示范表证据强度，不代表材料本身优劣 |

## 推荐使用方式

在后续接入模型或检索工具时，应要求模型遵守以下规则：

1. 可以引用这些记录提出候选材料、候选亲本或验证对象。
2. 必须同时输出 `accession_id`、材料名和 `source_refs`。
3. 如果字段中没有基因/QTL/标记信息，不能编造标记或单倍型。
4. 如果只有 passport 信息，不能声称该材料具有某个已验证目标性状。
5. 如果只有单环境表型信息，必须标注需要多环境验证。
6. 最终报告中应把这类依据标为“种质资源线索”或“表型候选证据”，而不是强证据结论。

## 适合继续扩充的方向

下一批公开数据建议围绕谷子做专题扩充：

1. 耐密植和株型材料
2. 抗旱和水分利用效率材料
3. 产量构成和穗部性状材料
4. 籽粒品质和商品性状材料
5. 公开核心种质或 mini-core collection
6. 带有基因/QTL/标记证据的材料

## 后续接入建议

在进入工具开发前，建议先完成两个轻量检查：

1. CSV 校验：检查必填字段、列数、`accession_id` 唯一性、`data_confidence` 和 `availability` 是否为受控词。
2. 证据边界校验：检查 `known_genes_qtls`、`markers`、`genotype_evidence` 是否存在没有来源支撑的强断言。

当前仓库已提供一个轻量校验脚本：

```bash
python scripts/validate_germplasm.py docs/templates/germplasm_resources_public_seed.csv
```

校验通过时会输出行数和 `No issues found.`。如果后续继续补充 CSV，建议每次补完都先运行该脚本。

当前仓库也提供了一个本地查询脚本，用于在接入 agent 前人工检查种质资源表是否好用：

```bash
python scripts/search_germplasm.py "lodging architecture" --crop "foxtail millet" --min-confidence medium --limit 5
```

也可以按性状过滤：

```bash
python scripts/search_germplasm.py "QTL" --trait "yield traits" --limit 5
```

查询结果会显示材料编号、名称、性状、数据置信度、候选育种用途、风险和来源。这个脚本只做确定性关键词检索，不调用 LLM，也不改变任何数据。

此外，AI Breeding Scientist 已注册同一数据源对应的 LLM 工具：

```text
germplasm_search
```

该工具开放给当前六智能体流程中的 Evidence Curator、Breeding Designer、Risk Reviewer 和 Iteration Orchestrator 相关步骤，用来查询候选亲本、donor accession、作图亲本、突变体背景或验证材料线索。工具返回中会包含 `accession_id`、材料名、候选用途、风险、`source_refs` 和可被工具循环识别的首个 `url`。

使用边界仍然相同：`germplasm_search` 结果只能作为“种质资源线索”，不能替代外部文献证据，也不能证明未列出的标记、基因型、可获得性或多环境稳定育种价值。

这样可以保证种质资源库先作为可信数据资产，再进入 AI Breeding Scientist 的生成、评审和报告流程。
