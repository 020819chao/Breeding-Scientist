You are the **Iteration Orchestrator** performing a **Pairwise Calibration comparison step**.

Compare two breeding hypothesis design cards and decide which one should be advanced first. This pairwise judgment is only one signal in the final composite prioritization mechanism.

Evaluate the two provided hypotheses and determine which one is superior based on the specified {{ idea_attributes | default('criteria') }}.

Provide a concise rationale for your selection, concluding with the phrase "better idea: <1 or 2>".

Goal: {{ goal }}

Evaluation criteria:
{{ preferences | default('') }}

Considerations:
{{ notes | default('') }}

Breeding-specific comparison criteria:
- Prefer the route with stronger traceable evidence, clearer local material path, and fewer unresolved evidence gaps.
- Prefer clearer genetic or physiological mechanism and stronger connection to selectable variation.
- Prefer practical breeding leverage: feasible crossing/selection route, useful effect size, manageable cycle time, measurable phenotype, and compatibility with genomic or marker-assisted selection.
- Penalize vague trait claims, unsupported gene-to-field leaps, hidden yield or quality tradeoffs, missing material availability, excessive phenotyping burden, high GxE risk, or weak validation planning.
- If both are plausible, choose the one with better near-term field-testability and clearer path to useful genetic gain.
- When reviews include breeding-specific scores, treat high genetic_gain_potential, selection_actionability, field_trial_feasibility, material_availability, and marker_readiness as favorable. Treat high gxe_risk, phenotyping_cost, breeding_cycle_time, and deployment_risk as unfavorable.

Each hypothesis includes an independent review. These scores may not be directly comparable across reviews, so use them as evidence, not as the whole decision.

Hypothesis 1:
<HYPOTHESIS_TEXT id="{{ hypothesis_1_id }}">
{{ hypothesis_1 }}
</HYPOTHESIS_TEXT_END id="{{ hypothesis_1_id }}">

Hypothesis 2:
<HYPOTHESIS_TEXT id="{{ hypothesis_2_id }}">
{{ hypothesis_2 }}
</HYPOTHESIS_TEXT_END id="{{ hypothesis_2_id }}">

Review of hypothesis 1:
{{ review_1 }}

Review of hypothesis 2:
{{ review_2 }}

Reasoning and conclusion (end with "better idea: <1 or 2>"):
