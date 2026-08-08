# 谷子种质资源库接入验证报告

本文档基于真实运行 session `ses_01KXSK6RVT3KGXFXVSYM7CHQRQ`，总结第二轮“种质资源库 + germplasm_search 工具”是否真正进入 AI Breeding Scientist 工作流，以及最终总评是否形成了可落地的育种建议。

## 1. 验证目标

本轮验证的问题是：

1. 模型是否会主动调用本地种质资源库工具 `germplasm_search`。
2. 生成假设时是否会使用具体材料编号、材料来源和风险边界。
3. 证据整理、风险评审和假设修订过程中是否会继续检查种质资源线索。
4. 最终总评是否能从多个假设中收敛出可执行的育种路线。

运行目标为：

```text
提出一个谷子耐密植株型改良假设，要求结合可用种质资源线索，说明候选材料、目标性状、可能机制、验证试验和风险。
```

偏好要求包括：

```text
优先使用 germplasm_search 查询种质资源线索；候选材料需说明 accession ID、来源、风险和证据缺口；不要编造未列出的基因、标记或多环境表现。
```

## 2. 工具调用验证

从 transcript 检查结果看，`germplasm_search` 已被多个智能体实际调用。

### Breeding Designer 设计步骤

Breeding Designer 在生成育种假设设计卡时调用了：

```text
germplasm_search
pubmed_search
record_hypothesis
```

说明生成假设时模型不仅查外部文献，也查询了本地种质资源库，并把材料线索写入假设卡。

### Risk Reviewer 评审步骤

Risk Reviewer 在审查假设证据边界时多次调用：

```text
germplasm_search
record_review
```

说明 Risk Reviewer 会回查候选材料是否存在于本地种质资源表中，并检查材料证据边界。

### Iteration Orchestrator 修订步骤

Iteration Orchestrator 触发的假设修订步骤也多次调用：

```text
germplasm_search
record_hypothesis
```

说明假设修订时也会继续利用种质资源线索，而不是只做文本改写。

## 3. 种质资源库实际使用情况

最终生成和演化出的假设中，已经明确使用了以下本地种质资源条目：

| 材料 | 种质库 ID | 使用方式 |
| --- | --- | --- |
| 263A | `ARCH-263A` | 半矮秆供体；Seita.5G404900 GA20氧化酶移码缺失；CAPS标记线索 |
| Chuang 29 | `ARCH-Chuang29` | 高秆对照或精英背景线索 |
| Jingu 21 | `ARCH-Jingu21` | 茎秆强度/倒伏相关候选，但被标注为管理响应，遗传基础待验证 |
| Zhangza 13 | `ARCH-Zhangza13` | 与 Jingu 21 类似，作为茎秆强度候选和风险线索 |
| Xiaojinmiao | `FPS2025-136` | 自然短茎厚秆候选受体；单穗粒重高；单环境表型证据 |
| Huangmaogu | `FPS2025-116` | Xiaojinmiao 的替代受体候选 |
| Yugu1 | `ARCH-Yugu1` | 参考基因组背景、作图/突变体资源背景 |
| Longgu7 | `ARCH-Longgu7` | 穗颈长/农艺性状 QTL 作图亲本 |
| Hongmiaozhangu | `ARCH-Hongmiaozhangu` | RAD-seq QTL 作图亲本 |
| Changnong35 | `ARCH-Changnong35` | Hongmiaozhangu 的作图群体亲本 |

这些材料并不是只在工具结果里出现，而是进入了 `breeding_context.germplasm`、`entities` 和最终总评。

## 4. 代表性假设

本次运行产生了多个与种质库高度相关的假设。

### 假设一：半矮秆 × 茎秆强度聚合

文件：

```text
hyp_2d272854082e0213
```

核心材料：

```text
263A (ARCH-263A)
Jingu 21 (ARCH-Jingu21)
Zhangza 13 (ARCH-Zhangza13)
Chuang 29 (ARCH-Chuang29)
```

该假设提出用 263A 的半矮秆等位基因与 Jingu 21 / Zhangza 13 的茎秆强度表型组合，但也指出 Jingu 21 / Zhangza 13 的茎秆强度可能只是硅肥管理响应，遗传基础需要验证。

### 假设二：263A × Xiaojinmiao

文件：

```text
hyp_9c5475509a53648d
hyp_0156217b37ce8e6a
```

核心材料：

```text
263A (ARCH-263A)
Xiaojinmiao (FPS2025-136)
Huangmaogu (FPS2025-116)
```

该方向最终被总评认为更适合优先验证，因为它不依赖尚未定位的茎秆强度 QTL，而是利用现有表型较明确的自然短茎厚秆材料作为受体。

### 假设三：三重耐密植株型聚合

文件：

```text
hyp_80e5d4f235a27ccd
```

核心材料：

```text
263A (ARCH-263A)
Longgu7 (ARCH-Longgu7)
Hongmiaozhangu (ARCH-Hongmiaozhangu)
Yugu1 (ARCH-Yugu1)
Changnong35 (ARCH-Changnong35)
```

该假设提出“矮秆 + 短穗颈 + 半直立叶”的三靶标聚合路线。它更复杂，也更有长期价值，但总评倾向于先做更简化、更可验证的 263A × Xiaojinmiao 预实验。

## 5. 最终总评结论

最终总评文件：

```text
data/artifacts/ses_01KXSK6RVT3KGXFXVSYM7CHQRQ/final/overview.md
```

总评收敛到一个两阶段策略：

### 优先路线

```text
263A × Xiaojinmiao (FPS2025-136)
```

核心逻辑：

1. 263A 提供已验证的 Seita.5G404900 GA20氧化酶功能缺失矮秆等位基因。
2. Xiaojinmiao 提供自然短茎厚秆表型线索。
3. 先做 F2 剂量效应预实验，验证矮秆等位基因进入 Xiaojinmiao 背景后是否过度矮化或显著损失单穗粒重。
4. 如果通过，再进入后续密植胁迫选择和聚合阶段。

### 并行风险控制路线

```text
Jingu 21 × Yugu1
```

核心逻辑：

1. 检查 Jingu 21 的茎秆强度是否存在遗传基础。
2. 如果能定位到主效 QTL，则开发 KASP 标记并考虑与 263A 路线聚合。
3. 如果不能定位，则放弃 Jingu 21 / Zhangza 13 作为遗传供体，只保留其作为管理响应参考。

## 6. 建议首轮实验

### 实验一：263A × Xiaojinmiao F2 剂量效应预实验

目的：

```text
验证 Seita.5G404900 矮秆等位基因在 Xiaojinmiao 背景中是否产生可接受的半矮秆效果，而不是过度矮化或严重降低单穗粒重。
```

设计：

| 项目 | 内容 |
| --- | --- |
| 群体 | 263A × Xiaojinmiao F2 |
| 群体规模 | ≥150-200 株 |
| 密度处理 | 22.5 万株/hm² 和 45 万株/hm² |
| 重复 | 3 次重复 |
| 分型 | Seita.5G404900 CAPS 标记 |
| 基因型分组 | `+/+`, `+/-`, `-/-` |
| 表型 | 株高、茎粗、基部节间壁厚、倒伏率、单穗粒重、小区产量 |
| 决策标准 | 若纯合缺失系株高低于受体野生型 70% 或单穗粒重下降 >15%，则放弃该组合 |

### 实验二：Jingu 21 × Yugu1 茎秆强度 QTL 定位

目的：

```text
验证 Jingu 21 的茎秆强度是否具有可遗传基础。
```

设计：

| 项目 | 内容 |
| --- | --- |
| 群体 | Jingu 21 × Yugu1 F2 |
| 群体规模 | ≥200 株，理想情况下 300-500 株 |
| 环境 | 赤峰 45 万株/hm² 密植条件 |
| 表型 | 基部第二节间壁厚、茎外径、倒伏率、茎秆抗折力 |
| 基因型 | GBS 或 RAD-seq |
| 决策标准 | 若检测到 LOD > 3.0 且 PVE > 10% 的 QTL，则继续开发 KASP 标记；否则放弃 Jingu 21 作为遗传供体 |

## 7. 证据边界

本次总评比较重要的一点是：它没有把种质库条目当作绝对事实，而是保留了证据边界。

主要证据缺口：

1. `263A` 的 Seita.5G404900 等位基因在 `Xiaojinmiao` 背景中的剂量效应未知。
2. `Xiaojinmiao` 的短茎和厚秆遗传力未知。
3. `Xiaojinmiao` / `Huangmaogu` 目前主要来自赤峰单环境表型评价，多环境 G×E 未验证。
4. `Jingu 21` / `Zhangza 13` 的茎秆强度可能来自硅肥管理响应，不一定是稳定遗传性状。
5. 谷子茎秆基部节间壁厚的遗传力和 QTL 检测效力仍缺少直接文献。

## 8. 当前问题

最终报告内容质量较好，但 audit 文件仍显示：

```text
status: needs_attention
missing_breeding_elements:
- crop_or_germplasm
- target_trait
- phenotyping
- genotyping
- trial_design
```

从正文看，这些元素实际上已经存在于 `Breeding decision table` 和 `Suggested next breeding cycle` 中。因此这更像是审计规则的误报，而不是最终报告真的缺少这些内容。

后续建议修复 final report audit 的检测规则，使其能识别中文字段和表格中的育种要素。

## 9. 阶段性结论

本次验证说明：

1. 本地谷子种质资源库已经进入实际工作流。
2. `germplasm_search` 被 Breeding Designer、Risk Reviewer 和 Iteration Orchestrator 触发的修订步骤实际调用。
3. 生成假设不再停留在“泛泛调控某基因”，而是落到了具体材料和实验组合。
4. 最终总评形成了可执行的首轮实验方案。
5. 种质资源库有效提升了假设的育种落地性。

因此，第二轮“种质资源库”方向是有效的。下一步可以做：

```text
修复 final report audit 中文/表格识别误报
补充更多谷子种质条目
构建轻量知识图谱关系
做一个不使用 germplasm_search 的对照运行
```
