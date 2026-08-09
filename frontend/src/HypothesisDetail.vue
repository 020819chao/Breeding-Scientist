<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { IconArrowLeft, IconTranslate } from "@arco-design/web-vue/es/icon";
import { appPathname } from "./path";

type ThemeName = "green" | "gold" | "purple";
type Language = "zh" | "en";

const parts = appPathname().split("/").filter(Boolean);
const sessionId = parts[1] || "";
const hypothesisId = parts[3] || "";
const themes: Record<ThemeName, { label: string; color: string; hover: string; pressed: string }> = {
  green: { label: "绿色", color: "#16865f", hover: "#2a9d76", pressed: "#0f6848" },
  gold: { label: "金色", color: "#b8771e", hover: "#ca8c35", pressed: "#8e5b12" },
  purple: { label: "紫色", color: "#7046b6", hover: "#855fc3", pressed: "#57358f" },
};

const language = ref<Language>((localStorage.getItem("co-scientist-language") as Language) || "zh");
const themeName = ref<ThemeName>((localStorage.getItem("co-scientist-theme") as ThemeName) || "green");
const detail = ref<any>(null);
const loading = ref(true);
const error = ref("");

const currentTheme = computed(() => themes[themeName.value]);
const themeStyles = computed(() => ({
  "--theme-color": currentTheme.value.color,
  "--theme-color-hover": currentTheme.value.hover,
  "--theme-color-pressed": currentTheme.value.pressed,
  "--theme-soft": `${currentTheme.value.color}12`,
}));
const isEnglish = computed(() => language.value === "en");
const copy = computed(() => isEnglish.value ? {
  knowledge: "Knowledge Base", sessions: "Research Sessions", newSession: "New session", theme: "Theme",
  back: "Back to session", route: "Breeding route", evidence: "View evidence graph", revision: "View route evolution",
  kicker: "BREEDING SCIENTIST  /  ROUTE DETAIL", candidate: "Candidate route", evidenceBacked: "Evidence-backed route",
  value: "Route value", why: "Why this route is worth advancing", evidenceOverview: "Evidence overview", basis: "What supports this route",
  materialEvidence: "Material evidence", linkedEvidence: "Linked evidence", localSources: "Local sources", citations: "Source records", completeness: "Plan completeness",
  execution: "Executable plan", executionDescription: "Materials, selection and validation details for moving this route forward.",
  materials: "Materials and route design", checks: "Pre-advancement checks", checksDescription: "Open items to confirm before entering validation.",
  evidenceGaps: "Evidence to add", validation: "Validation readiness", risk: "Risk status", iteration: "Route iteration", sourceRoutes: "Source routes", nextRoutes: "Follow-up routes", currentAction: "Current action", expert: "Expert review", viewReview: "View review opinion", sourceText: "Original hypothesis text", loading: "Loading route details...", retry: "Retry",
} : {
  knowledge: "知识库", sessions: "研究会话", newSession: "新建育种会话", theme: "色调",
  back: "返回会话", route: "育种路线", evidence: "查看证据图谱", revision: "查看路线演化",
  kicker: "BREEDING SCIENTIST  /  路线详情", candidate: "候选路线", evidenceBacked: "证据支持路线",
  value: "路线价值", why: "为什么值得推进", evidenceOverview: "证据概况", basis: "这条路线的依据",
  materialEvidence: "材料依据", linkedEvidence: "关联依据", localSources: "本地资料", citations: "来源记录", completeness: "方案完整度",
  execution: "可执行方案", executionDescription: "用于推进这条路线的材料、选择与验证细节。",
  materials: "材料与路线设计", checks: "推进前检查", checksDescription: "进入验证前还需要确认的事项。",
  evidenceGaps: "需要补充的证据", validation: "验证准备度", risk: "风险状态", iteration: "路线迭代", sourceRoutes: "来源路线", nextRoutes: "后续路线", currentAction: "当前动作", expert: "专家意见", viewReview: "查看评审意见", sourceText: "假设原文", loading: "正在加载路线详情…", retry: "重试",
});

const session = computed(() => detail.value?.session || {});
const hypothesis = computed(() => detail.value?.hypothesis || {});
const route = computed(() => detail.value?.route_view || {});
const evidence = computed(() => detail.value?.evidence_subgraph || {});
const revision = computed(() => detail.value?.route_revision_graph || {});
const closedLoop = computed(() => detail.value?.closed_loop || {});
const reviewViews = computed(() => detail.value?.review_views || []);

function toggleLanguage() {
  language.value = language.value === "zh" ? "en" : "zh";
  localStorage.setItem("co-scientist-language", language.value);
  loadDetail();
}

function selectTheme(value: string | number | Record<string, any> | undefined) {
  if (typeof value !== "string" || !(value in themes)) return;
  themeName.value = value as ThemeName;
  localStorage.setItem("co-scientist-theme", themeName.value);
}

function statusColor(state: string) {
  if (["ready", "candidate", "reviewed"].includes(state)) return "green";
  if (["blocked", "rejected"].includes(state)) return "red";
  if (["draft", "unknown"].includes(state)) return "gray";
  return "arcoblue";
}

function strategyLabel(strategy: string) {
  const labels: Record<string, string> = isEnglish.value
    ? { literature: "Evidence-backed route", debate: "Debate route", combine: "Combined route", simplify: "Simplified route", out_of_box: "Exploratory route", feasibility: "Feasibility route", assumption: "Assumption route", feedback_driven: "Feedback-driven route" }
    : { literature: "证据支持路线", debate: "辩论路线", combine: "组合路线", simplify: "简化路线", out_of_box: "探索路线", feasibility: "可行性路线", assumption: "假设路线", feedback_driven: "反馈驱动路线" };
  return labels[strategy] || strategy;
}

function formatCount(value: unknown) {
  return Number(value || 0).toLocaleString();
}

function completeness() {
  const value = route.value.audit?.completeness_score;
  return value === undefined || value === null ? "—" : `${Math.round(Number(value))}%`;
}

function checkText(level: string) {
  const map: Record<string, string> = isEnglish.value
    ? { ready: "Ready to enter validation", high: "Ready to enter validation", partial: "Partially prepared", medium: "Partially prepared", not_ready: "More validation is needed", low: "More validation is needed" }
    : { ready: "可以进入验证", high: "可以进入验证", partial: "部分准备完成", medium: "部分准备完成", not_ready: "还需要补充验证", low: "还需要补充验证" };
  return map[level] || (isEnglish.value ? "Validation plan recorded" : "已形成验证计划");
}

function riskText(level: string) {
  const map: Record<string, string> = isEnglish.value
    ? { controlled: "Controlled risk", low: "Controlled risk", moderate: "Moderate risk", medium: "Moderate risk", high: "High priority risk", critical: "High priority risk" }
    : { controlled: "风险可控", low: "风险可控", moderate: "存在中等风险", medium: "存在中等风险", high: "需要优先处理风险", critical: "需要优先处理风险" };
  return map[level] || (isEnglish.value ? "Risk review completed" : "已完成风险检查");
}

function gapText(gap: string) {
  if (isEnglish.value) return gap;
  const map: Record<string, string> = { source: "来源证据", validation: "验证数据", germplasm: "种质材料", field_trial: "田间试验", mechanism: "作用机制" };
  return map[gap] || gap;
}

function detailMessage(item: any) {
  const message = typeof item === "string" ? item : item?.message || item?.target || "";
  if (isEnglish.value) return message;
  const map: Record<string, string> = {
    "Latest review verdict is missing_piece.": "最近一次评审仍缺少关键证据。",
    "Material availability requires local confirmation.": "需要在本地确认材料身份、可获得性、种子数量和杂交许可。",
    "Marker/QTL evidence needs local assay or parental polymorphism confirmation before selection.": "进入选择前，需要完成本地标记检测或亲本多态性确认。",
    "Field-trial record is pending or not yet decision-grade.": "田间试验记录尚未完成，或暂时不足以支持决策。",
  };
  return map[message] || message;
}

function detailAction(item: any) {
  const mitigation = typeof item === "string" ? "" : item?.mitigation || "";
  if (isEnglish.value) return mitigation;
  if (mitigation.includes("material identity")) return "确认材料身份、可获得性、种子数量和杂交许可。";
  if (mitigation.includes("marker polymorphism")) return "开展标记多态性、分离和背景依赖性检查。";
  if (mitigation.includes("preflight assay")) return "把风险转为带有明确推进/暂停阈值的预检试验。";
  if (mitigation.includes("focused evidence")) return "补充针对性证据，并请专家确认。";
  return mitigation;
}

function categoryText(category: string) {
  if (isEnglish.value) return category;
  const map: Record<string, string> = { genetic: "遗传", material: "材料", validation: "验证", evidence: "证据", deployment: "应用", gxe: "环境互作" };
  return map[category] || category;
}

async function loadDetail() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/hypotheses/${encodeURIComponent(hypothesisId)}/detail?lang=${language.value}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    detail.value = await response.json();
  } catch {
    error.value = isEnglish.value ? "This route could not be loaded." : "暂时无法加载这条育种路线。";
  } finally {
    loading.value = false;
  }
}

onMounted(loadDetail);
</script>

<template>
  <div class="hypothesis-detail-app" :style="themeStyles">
    <a-layout>
      <a-layout-header class="hypothesis-topbar">
        <div class="hypothesis-topbar-inner">
          <a class="hypothesis-brand" href="/">
            <span class="hypothesis-brand-mark">BS</span>
            <span><strong>Breeding Scientist</strong><small>{{ isEnglish ? "Breeding Scientist" : "育种科学家" }}</small></span>
          </a>
          <nav class="hypothesis-nav"><a href="/knowledge">{{ copy.knowledge }}</a><a href="/">{{ copy.sessions }}</a></nav>
          <a-space class="hypothesis-header-actions" :size="10">
            <a-button type="text" class="hypothesis-language" @click="toggleLanguage"><IconTranslate />{{ language === "zh" ? "中文" : "English" }}</a-button>
            <a-dropdown @select="selectTheme">
              <a-button type="text" class="hypothesis-theme"><span class="theme-dot" :style="{ background: currentTheme.color }"></span>{{ copy.theme }} <span class="theme-chevron">⌄</span></a-button>
              <template #content><a-doption v-for="([key, item]) in Object.entries(themes)" :key="key" :value="key"><span class="theme-option"><i :style="{ background: item.color }"></i>{{ item.label }}<b v-if="themeName === key">✓</b></span></a-doption></template>
            </a-dropdown>
            <a-button type="primary" href="/sessions/new">{{ copy.newSession }}</a-button>
          </a-space>
        </div>
      </a-layout-header>

      <a-layout-content>
        <main class="hypothesis-page">
          <div v-if="loading" class="hypothesis-loading"><a-spin :size="32" /><p>{{ copy.loading }}</p></div>
          <a-result v-else-if="error" status="error" :title="error"><template #extra><a-button type="primary" @click="loadDetail">{{ copy.retry }}</a-button></template></a-result>
          <template v-else>
            <div class="hypothesis-breadcrumb"><a :href="`/sessions/${session.id}`"><IconArrowLeft />{{ copy.back }}</a><span>/</span><span>{{ copy.route }}</span><code>{{ hypothesis.id?.slice(-12) }}</code></div>
            <div class="hypothesis-toolbar">
              <div class="route-language-note">{{ copy.route }}</div>
              <div class="hypothesis-actions"><a v-if="evidence.available" :href="`/sessions/${session.id}/hypotheses/${hypothesis.id}/evidence-subgraph`">{{ copy.evidence }}</a><a v-if="revision.available" :href="`/sessions/${session.id}/hypotheses/${hypothesis.id}/route-revision-graph`">{{ copy.revision }}</a></div>
            </div>

            <header class="hypothesis-hero">
              <div class="hypothesis-eyebrow"><span></span>{{ copy.kicker }}</div>
              <h1>{{ route.title || detail.display_title || hypothesis.title || hypothesis.id }}</h1>
              <p class="hypothesis-summary">{{ route.statement || hypothesis.summary || (isEnglish ? "This route has formed an initial design and is awaiting further validation." : "这条路线已形成初步设计，等待进一步验证。") }}</p>
              <div class="hypothesis-tags"><a-tag :color="statusColor(hypothesis.state)">{{ hypothesis.state || copy.candidate }}</a-tag><a-tag v-if="hypothesis.strategy && hypothesis.strategy !== 'literature'" class="strategy-tag">{{ strategyLabel(hypothesis.strategy) }}</a-tag><a-tag v-if="route.available" class="evidence-tag">{{ copy.evidenceBacked }}</a-tag></div>
            </header>

            <section v-if="route.available" class="hypothesis-layout">
              <div class="hypothesis-main-column">
                <a-card class="route-value-card" :bordered="false"><div class="section-kicker">{{ copy.value }}</div><h2>{{ copy.why }}</h2><p>{{ route.mechanism || (isEnglish ? "This route matches the breeding objective and should be advanced with the materials and validation plan below." : "这条路线与当前育种目标相关，建议结合下面的材料和验证计划推进。") }}</p></a-card>

                <section class="hypothesis-section"><div class="section-heading"><div><div class="section-kicker">{{ copy.evidenceOverview }}</div><h2>{{ copy.basis }}</h2></div><a v-if="evidence.available" class="section-link-tag" :href="`/sessions/${session.id}/hypotheses/${hypothesis.id}/evidence-subgraph`">{{ copy.evidence }} <span>→</span></a></div><div class="evidence-stat-grid"><div><strong>{{ formatCount(route.evidence_counts?.germplasm) }}</strong><span>{{ copy.materialEvidence }}</span></div><div><strong>{{ formatCount(route.evidence_counts?.kg) }}</strong><span>{{ copy.linkedEvidence }}</span></div><div><strong>{{ formatCount(route.evidence_counts?.rag) }}</strong><span>{{ copy.localSources }}</span></div><div><strong>{{ formatCount(route.citation_count) }}</strong><span>{{ copy.citations }}</span></div><div><strong>{{ completeness() }}</strong><span>{{ copy.completeness }}</span></div></div></section>

                <section v-if="route.sections?.length" class="hypothesis-section"><div class="section-heading"><div><div class="section-kicker">{{ copy.execution }}</div><h2>{{ copy.materials }}</h2><p>{{ copy.executionDescription }}</p></div></div><div class="route-section-grid"><a-card v-for="(section, index) in route.sections" :key="section.title" :class="['route-section-card', `route-section-card-${index + 1}`]" :bordered="false"><div class="route-card-head"><span class="route-card-number">{{ String(index + 1).padStart(2, '0') }}</span><span class="route-card-rule"></span></div><h3>{{ section.title }}</h3><dl><div v-for="item in section.items" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl></a-card></div></section>

                <section v-if="route.evidence_gap_types?.length || Object.keys(route.validation_summary || {}).length || Object.keys(route.risk_summary || {}).length" class="check-panel"><div class="section-kicker">{{ copy.checks }}</div><h2>{{ copy.checksDescription }}</h2><div class="check-list"><div v-if="route.evidence_gap_types?.length" class="check-row"><strong>{{ copy.evidenceGaps }}</strong><div><a-tag v-for="gap in route.evidence_gap_types" :key="gap" class="gap-tag">{{ gapText(gap) }}</a-tag></div></div><div v-if="Object.keys(route.validation_summary || {}).length" class="check-row"><strong>{{ copy.validation }}</strong><span>{{ checkText(route.validation_summary.readiness_level) }}<em v-if="route.validation_summary.critical_gap_count"> · {{ route.validation_summary.critical_gap_count }} {{ isEnglish ? "critical gaps" : "项关键缺口" }}</em></span></div><div v-if="Object.keys(route.risk_summary || {}).length" class="check-row"><strong>{{ copy.risk }}</strong><span>{{ riskText(route.risk_summary.risk_level) }}<em v-if="route.risk_summary.must_resolve_count"> · {{ route.risk_summary.must_resolve_count }} {{ isEnglish ? "must-resolve items" : "项待处理事项" }}</em></span></div></div></section>

                <section v-if="closedLoop.available" class="hypothesis-section iteration-section"><div class="section-heading"><div><div class="section-kicker">{{ copy.iteration }}</div><h2>{{ isEnglish ? "How this route enters the next cycle" : "这条路线如何进入下一轮" }}</h2></div></div><div class="iteration-summary"><div><strong>{{ closedLoop.parents?.length || 0 }}</strong><span>{{ copy.sourceRoutes }}</span></div><div><strong>{{ closedLoop.action }}</strong><span>{{ copy.currentAction }}</span></div><div><strong>{{ closedLoop.children?.length || 0 }}</strong><span>{{ copy.nextRoutes }}</span></div></div><p v-if="closedLoop.direction" class="iteration-direction">{{ closedLoop.direction }}</p><div v-if="closedLoop.parents?.length || closedLoop.children?.length" class="loop-links"><div v-if="closedLoop.parents?.length"><strong>{{ copy.sourceRoutes }}</strong><a v-for="item in closedLoop.parents" :key="item.id" :href="item.href">{{ item.title }} <span>→</span></a></div><div v-if="closedLoop.children?.length"><strong>{{ copy.nextRoutes }}</strong><a v-for="item in closedLoop.children" :key="item.id" :href="item.href">{{ item.title }} <span>→</span></a></div></div></section>

                <section v-if="reviewViews.length" class="hypothesis-section"><div class="section-heading"><div><div class="section-kicker">{{ copy.expert }}</div><h2>{{ isEnglish ? "Expert review conclusions" : "专家评审结论" }}</h2></div></div><div class="review-grid"><a-card v-for="review in reviewViews" :key="review.id" class="review-card" :bordered="false"><div class="review-card-head"><strong>{{ review.kind_label }}</strong><a-tag color="orange">{{ review.verdict_label }}</a-tag></div><details><summary>{{ copy.viewReview }}<span class="details-chevron"></span></summary><div class="review-body" v-html="review.body_html"></div></details><div v-if="review.score_items?.length" class="review-scores"><span v-for="score in review.score_items" :key="score.label">{{ score.label }} <b>{{ Math.round(score.value * 100) }}%</b></span></div></a-card></div></section>
              </div>

              <aside class="hypothesis-side-column"><div class="side-sticky"><a-card class="side-summary-card" :bordered="false"><div class="side-card-label"><span class="side-mark">BS</span><span>{{ copy.route }}</span></div><h2>{{ route.title || hypothesis.title }}</h2><p>{{ route.statement || hypothesis.summary }}</p><div class="side-status"><span></span>{{ isEnglish ? "Evidence-led · ready for review" : "证据驱动 · 可进入复核" }}</div><a class="side-action" :href="`/sessions/${session.id}`">{{ copy.back }} <span>→</span></a></a-card><a-card v-if="detail.full_text_html" class="source-card" :bordered="false"><div class="section-kicker">{{ copy.sourceText }}</div><details><summary>{{ isEnglish ? "Expand original hypothesis" : "展开假设原文" }}<span class="details-chevron"></span></summary><div class="markdown-body" v-html="detail.full_text_html"></div></details></a-card></div></aside>
            </section>
            <section v-if="route.critical_evidence_gaps?.length || route.must_resolve_items?.length" class="detail-breakdown-panel"><details class="detail-breakdown-details"><summary><span class="detail-breakdown-summary-copy"><span class="section-kicker">{{ isEnglish ? "ACTIONABLE REVIEW" : "具体处理事项" }}</span><strong>{{ isEnglish ? "Review details" : "证据缺口与风险处理" }}</strong><small>{{ isEnglish ? "Expand to see what must be confirmed before advancing." : "展开查看推进前需要确认和处理的具体事项。" }}</small></span><span class="detail-breakdown-summary-count">{{ (route.critical_evidence_gaps?.length || 0) + (route.must_resolve_items?.length || 0) }}</span><span class="details-chevron"></span></summary><div class="detail-breakdown-details-body"><div class="section-kicker">{{ isEnglish ? "ACTIONABLE REVIEW" : "具体处理事项" }}</div><h2>{{ isEnglish ? "What needs to be confirmed" : "需要具体确认什么" }}</h2><div v-if="route.critical_evidence_gaps?.length" class="detail-breakdown-group"><div class="detail-breakdown-heading"><strong>{{ isEnglish ? "Specific evidence gaps" : "具体证据缺口" }}</strong><span>{{ route.critical_evidence_gaps.length }}</span></div><div v-for="(item, index) in route.critical_evidence_gaps" :key="`gap-${index}`" class="detail-breakdown-item"><b>{{ String(index + 1).padStart(2, "0") }}</b><div><strong>{{ detailMessage(item) }}</strong><small v-if="detailAction(item)">{{ detailAction(item) }}</small></div></div></div><div v-if="route.must_resolve_items?.length" class="detail-breakdown-group risk-breakdown-group"><div class="detail-breakdown-heading"><strong>{{ isEnglish ? "Priority risk actions" : "优先处理的风险事项" }}</strong><span>{{ route.must_resolve_items.length }}</span></div><div v-for="(item, index) in route.must_resolve_items" :key="`risk-${index}`" class="detail-breakdown-item"><b>{{ String(index + 1).padStart(2, "0") }}</b><div><strong><em v-if="item.category">{{ categoryText(item.category) }} · </em>{{ detailMessage(item) }}</strong><small v-if="detailAction(item)">{{ detailAction(item) }}</small></div></div></div></div></details></section>
            <section v-if="!route.available" class="fallback-hypothesis"><div class="section-kicker">{{ copy.route }}</div><h2>{{ hypothesis.title }}</h2><div class="markdown-body" v-html="detail.full_text_html"></div></section>
          </template>
        </main>
      </a-layout-content>
    </a-layout>
  </div>
</template>

<style scoped>
.hypothesis-detail-app { min-height: 100vh; color: #17241f; background: radial-gradient(circle at 8% 0%, color-mix(in srgb, var(--theme-color) 9%, transparent), transparent 30rem), #f7faf8; }
.hypothesis-topbar { height: 72px; background: rgba(255,255,255,.9); border-bottom: 1px solid #e1ebe4; backdrop-filter: blur(18px); }
.hypothesis-topbar-inner { max-width: 1600px; height: 100%; margin: auto; padding: 0 28px; display: flex; align-items: center; gap: 40px; }
.hypothesis-brand { display: flex; align-items: center; gap: 10px; color: #17241f; text-decoration: none; }
.hypothesis-brand-mark { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 11px; color: #fff; background: var(--theme-color); box-shadow: 0 8px 20px color-mix(in srgb, var(--theme-color) 25%, transparent); font: 700 12px ui-monospace, monospace; }
.hypothesis-brand strong, .hypothesis-brand small { display: block; }.hypothesis-brand strong { font-size: 15px; letter-spacing: -.025em; }.hypothesis-brand small { margin-top: 2px; color: #84928a; font-size: 10px; }
.hypothesis-nav { display: flex; gap: 26px; margin-right: auto; }.hypothesis-nav a { color: #65736b; font-size: 13px; transition: color .2s ease, transform .2s ease; }.hypothesis-nav a:hover, .hypothesis-actions a:hover { color: var(--theme-color); }.hypothesis-nav a:hover { transform: translateY(-1px); }
.hypothesis-language, .hypothesis-theme { border-radius: 999px; color: #65736b; }.hypothesis-language { color: var(--theme-color); }.theme-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 7px; }.theme-chevron { margin-left: 4px; color: #97a29b; }.theme-option { display: flex; align-items: center; min-width: 108px; gap: 8px; }.theme-option i { width: 9px; height: 9px; border-radius: 50%; }.theme-option b { margin-left: auto; color: var(--theme-color); }
.hypothesis-page { max-width: 1400px; margin: auto; padding: 34px 28px 100px; }.hypothesis-loading { min-height: 620px; display: grid; place-content: center; justify-items: center; color: #89968f; }.hypothesis-loading p { margin-top: 14px; }.hypothesis-breadcrumb { display: flex; align-items: center; gap: 9px; margin-bottom: 22px; color: #8b9890; font-size: 13px; }.hypothesis-breadcrumb a { display: inline-flex; align-items: center; gap: 6px; color: var(--theme-color); }.hypothesis-breadcrumb code { margin-left: 5px; color: #75837a; font-size: 11px; }
.hypothesis-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 28px; }.route-language-note { color: var(--theme-color); font: 600 11px ui-monospace, monospace; letter-spacing: .11em; text-transform: uppercase; }.hypothesis-actions { display: flex; gap: 22px; }.hypothesis-actions a { color: var(--theme-color); font-size: 13px; font-weight: 600; transition: color .2s ease, transform .2s ease; }.hypothesis-actions a:hover { transform: translateX(2px); }.hypothesis-actions span { margin-left: 4px; font-size: 16px; transition: transform .2s ease; }.hypothesis-actions a:hover span { display: inline-block; transform: translateX(3px); }
.hypothesis-hero { max-width: 1120px; padding: 12px 0 38px; }.hypothesis-eyebrow, .section-kicker { color: var(--theme-color); font: 600 11px ui-monospace, monospace; letter-spacing: .12em; text-transform: uppercase; }.hypothesis-eyebrow span { display: inline-block; width: 17px; height: 1px; margin: 0 8px 3px 0; background: var(--theme-color); }.hypothesis-hero h1 { max-width: 1120px; margin: 17px 0 16px; color: #14231c; font-size: clamp(34px, 3.5vw, 52px); line-height: 1.16; letter-spacing: -.055em; }.hypothesis-summary { max-width: 1050px; margin: 0; color: #687970; font-size: 16px; line-height: 1.8; }.hypothesis-tags { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 21px; }.hypothesis-tags :deep(.arco-tag) { padding: 5px 12px; border-radius: 999px; font-size: 12px; }.strategy-tag { color: #65736b; background: #fff; border-color: #dce5df; }.evidence-tag { color: var(--theme-color); background: var(--theme-soft); border-color: color-mix(in srgb, var(--theme-color) 25%, #fff); }
.hypothesis-layout { display: block; }.hypothesis-main-column, .hypothesis-side-column { min-width: 0; }.hypothesis-side-column { margin-top: 42px; }.side-sticky { position: static; display: block; }.side-summary-card { display: none; }.route-value-card, .side-summary-card, .source-card, .route-section-card, .review-card { border: 1px solid #dfe9e2; border-radius: 16px; background: rgba(255,255,255,.88); box-shadow: 0 12px 30px rgba(54, 82, 64, .04); }.route-value-card { position: relative; overflow: hidden; padding: 0; border-left: 5px solid var(--theme-color); background: linear-gradient(120deg, color-mix(in srgb, var(--theme-color) 6%, #fff), rgba(255,255,255,.94)); }.route-value-card :deep(.arco-card-body) { padding: 31px 37px 34px; }.route-value-card h2 { margin: 10px 0 12px; color: #17241f; font-size: 29px; letter-spacing: -.045em; }.route-value-card p { max-width: 1120px; margin: 0; color: #52645a; font-size: 15px; line-height: 1.9; }
.hypothesis-section { margin-top: 48px; }.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 20px; }.section-heading h2 { margin: 8px 0 0; color: #17241f; font-size: 30px; letter-spacing: -.045em; }.section-heading p { margin: 7px 0 0; color: #839189; font-size: 13px; }.section-link-tag { display: inline-flex; align-items: center; gap: 5px; padding: 8px 12px; border: 1px solid color-mix(in srgb, var(--theme-color) 24%, #fff); border-radius: 999px; color: var(--theme-color); background: var(--theme-soft); cursor: pointer; font-size: 12px; font-weight: 600; transition: background .2s ease, transform .2s ease, box-shadow .2s ease; }.section-link-tag:hover { background: color-mix(in srgb, var(--theme-color) 10%, #fff); transform: translateY(-1px); box-shadow: 0 6px 14px color-mix(in srgb, var(--theme-color) 14%, transparent); }.evidence-stat-grid { display: grid; grid-template-columns: repeat(5, 1fr); overflow: hidden; border: 1px solid #dfe9e2; border-radius: 16px; background: rgba(255,255,255,.8); }.evidence-stat-grid div { min-height: 118px; padding: 24px 20px; border-right: 1px solid #e7eee8; transition: background .2s ease, transform .2s ease; }.evidence-stat-grid div:last-child { border-right: 0; }.evidence-stat-grid div:hover { background: color-mix(in srgb, var(--theme-color) 5%, #fff); transform: translateY(-2px); }.evidence-stat-grid strong, .evidence-stat-grid span { display: block; }.evidence-stat-grid strong { color: var(--theme-color); font: 600 26px ui-monospace, monospace; }.evidence-stat-grid span { margin-top: 9px; color: #839189; font-size: 12px; }
.route-section-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 15px; }.route-section-card { padding: 24px; }.route-section-card h3 { margin: 0 0 18px; color: #1d3027; font-size: 17px; }.route-section-card dl { margin: 0; }.route-section-card dl > div { padding: 12px 0; border-top: 1px solid #edf2ee; }.route-section-card dt { color: #8a978f; font-size: 12px; }.route-section-card dd { margin: 5px 0 0; color: #3c5145; font-size: 14px; line-height: 1.65; }
.check-panel { margin-top: 48px; padding: 28px 32px; border: 1px solid color-mix(in srgb, var(--theme-color) 18%, #dfe9e2); border-radius: 18px; background: color-mix(in srgb, var(--theme-color) 4%, #fff); }.check-panel h2 { margin: 8px 0 22px; color: #1b2c23; font-size: 24px; letter-spacing: -.035em; }.check-list { display: grid; gap: 0; }.check-row { display: grid; grid-template-columns: 180px 1fr; gap: 20px; align-items: start; padding: 16px 0; border-top: 1px solid #e7eee8; color: #53645a; font-size: 14px; line-height: 1.65; }.check-row strong { color: #24392e; }.check-row em { color: #8a978f; font-style: normal; }.gap-tag { margin: 0 6px 6px 0; color: var(--theme-color); border-color: color-mix(in srgb, var(--theme-color) 22%, #fff); background: #fff; }
.iteration-summary { display: grid; grid-template-columns: repeat(3, 1fr); overflow: hidden; border: 1px solid #dfe9e2; border-radius: 16px; background: rgba(255,255,255,.8); }.iteration-summary div { min-height: 100px; padding: 20px 22px; border-right: 1px solid #e7eee8; }.iteration-summary div:last-child { border-right: 0; }.iteration-summary strong, .iteration-summary span { display: block; }.iteration-summary strong { color: var(--theme-color); font-size: 18px; }.iteration-summary span { margin-top: 8px; color: #85928a; font-size: 12px; }.iteration-direction { margin: 16px 0 0; color: #607167; line-height: 1.7; }.loop-links { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-top: 18px; }.loop-links > div { display: grid; gap: 8px; padding: 17px 19px; border: 1px solid #e3ebe5; border-radius: 14px; background: #fff; }.loop-links strong { color: #53645a; font-size: 12px; }.loop-links a { overflow: hidden; color: var(--theme-color); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.loop-links a span { margin-left: 4px; }
.review-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 15px; }.review-card { padding: 22px; }.review-card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #314439; }.review-card details { margin-top: 18px; }.review-card summary, .source-card summary { display: flex; align-items: center; justify-content: space-between; cursor: pointer; color: var(--theme-color); font-size: 13px; font-weight: 600; list-style: none; }.review-card summary::-webkit-details-marker, .source-card summary::-webkit-details-marker { display: none; }.details-chevron { width: 8px; height: 8px; border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor; transform: rotate(45deg); transition: transform .2s ease; }.review-card details[open] .details-chevron, .source-card details[open] .details-chevron { transform: rotate(225deg) translate(-2px, -2px); }.review-body, .markdown-body { margin-top: 15px; color: #56685d; font-size: 13px; line-height: 1.8; }.review-body :deep(p), .markdown-body :deep(p) { margin: 0 0 10px; }.review-body :deep(a), .markdown-body :deep(a) { color: var(--theme-color); }.review-scores { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 18px; color: #8a978f; font-size: 11px; }.review-scores b { color: #43584a; font-weight: 600; }.side-summary-card { position: relative; overflow: hidden; padding: 27px 26px 25px; border-color: color-mix(in srgb, var(--theme-color) 24%, #dfe9e2); background: linear-gradient(145deg, color-mix(in srgb, var(--theme-color) 5%, #fff), rgba(255,255,255,.92)); }.side-summary-card::before { content: ""; position: absolute; top: -70px; right: -65px; width: 190px; height: 190px; border-radius: 50%; background: var(--theme-color); opacity: .06; }.side-card-label { position: relative; display: flex; align-items: center; gap: 10px; color: var(--theme-color); font-size: 12px; font-weight: 600; }.side-mark { display: grid; width: 32px; height: 32px; place-items: center; border: 1px solid color-mix(in srgb, var(--theme-color) 30%, #fff); border-radius: 10px; font: 700 10px ui-monospace, monospace; }.side-summary-card h2 { position: relative; margin: 30px 0 12px; color: #17241f; font-size: 26px; line-height: 1.3; letter-spacing: -.045em; }.side-summary-card p { position: relative; margin: 0; color: #738279; font-size: 14px; line-height: 1.8; }.side-status { display: flex; align-items: center; gap: 8px; margin: 30px 0 24px; color: #74857a; font-size: 12px; }.side-status span { width: 8px; height: 8px; border: 3px solid color-mix(in srgb, var(--theme-color) 20%, #fff); border-radius: 50%; background: var(--theme-color); }.side-action { display: flex; align-items: center; justify-content: space-between; padding-top: 16px; border-top: 1px solid #e8eee9; color: var(--theme-color); font-size: 13px; font-weight: 600; }.source-card { padding: 23px 25px; }.source-card details { margin-top: 15px; }.fallback-hypothesis { padding: 36px; border: 1px solid #dfe9e2; border-radius: 20px; background: #fff; }.fallback-hypothesis h2 { margin: 12px 0 20px; font-size: 30px; }.hypothesis-detail-app :deep(.arco-btn-primary) { background: var(--theme-color); border-color: var(--theme-color); }.hypothesis-detail-app :deep(.arco-btn-primary:hover) { background: var(--theme-color-hover); border-color: var(--theme-color-hover); }
.review-grid { grid-template-columns: 1fr; }
.route-section-card { position: relative; overflow: hidden; }.route-section-card::before { content: ""; position: absolute; inset: 0 0 auto; height: 3px; background: var(--route-accent, var(--theme-color)); }.route-section-card-2 { --route-accent: color-mix(in srgb, var(--theme-color) 70%, #d18a2a); }.route-section-card-3 { --route-accent: color-mix(in srgb, var(--theme-color) 62%, #397bb3); }.route-section-card-4 { --route-accent: color-mix(in srgb, var(--theme-color) 60%, #7956ad); }.route-card-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }.route-card-number { color: var(--route-accent, var(--theme-color)); font: 700 12px ui-monospace, monospace; letter-spacing: .08em; }.route-card-rule { flex: 1; height: 1px; background: color-mix(in srgb, var(--route-accent, var(--theme-color)) 18%, #edf2ee); }.route-section-card h3 { margin-bottom: 18px; font-size: 21px; letter-spacing: -.03em; }.route-section-card dl > div { padding: 15px 16px; border: 0; border-radius: 11px; background: #f8faf8; transition: background .18s ease, transform .18s ease; }.route-section-card dl > div + div { margin-top: 9px; }.route-section-card dl > div:hover { background: color-mix(in srgb, var(--route-accent, var(--theme-color)) 6%, #fff); transform: translateX(2px); }.route-section-card dt { color: var(--route-accent, var(--theme-color)); font-size: 12px; font-weight: 600; }.route-section-card dd { margin-top: 7px; color: #405348; font-size: 15px; line-height: 1.75; }
@media (max-width: 1080px) { .hypothesis-layout { grid-template-columns: 1fr; }.side-sticky { position: static; grid-template-columns: repeat(2, minmax(0, 1fr)); }.evidence-stat-grid { grid-template-columns: repeat(3, 1fr); }.evidence-stat-grid div:nth-child(3) { border-right: 0; }.evidence-stat-grid div:nth-child(-n+3) { border-bottom: 1px solid #e7eee8; } }
@media (max-width: 720px) { .hypothesis-topbar-inner { padding: 0 16px; gap: 16px; }.hypothesis-nav { display: none; }.hypothesis-topbar-inner > :last-child > :not(:last-child) { display: none; }.hypothesis-page { padding: 24px 16px 70px; }.hypothesis-toolbar { align-items: start; flex-direction: column; gap: 13px; }.hypothesis-actions { flex-wrap: wrap; gap: 12px 18px; }.hypothesis-hero h1 { font-size: 39px; }.hypothesis-summary { font-size: 15px; }.route-value-card { padding: 27px 25px 29px; }.route-value-card h2 { font-size: 26px; }.evidence-stat-grid, .route-section-grid, .loop-links, .review-grid, .side-sticky { grid-template-columns: 1fr; }.evidence-stat-grid div { border-right: 0; border-bottom: 1px solid #e7eee8; }.evidence-stat-grid div:last-child { border-bottom: 0; }.check-panel { padding: 24px 20px; }.check-row { grid-template-columns: 1fr; gap: 6px; }.iteration-summary { grid-template-columns: 1fr; }.iteration-summary div { border-right: 0; border-bottom: 1px solid #e7eee8; }.iteration-summary div:last-child { border-bottom: 0; } }
.hypothesis-page { max-width: 1600px; padding-top: 24px; }.hypothesis-hero { max-width: 1500px; }.hypothesis-hero h1 { max-width: 1500px; }.hypothesis-breadcrumb { margin-bottom: 0; }.hypothesis-toolbar { justify-content: flex-end; margin-top: -20px; margin-bottom: 34px; }.route-language-note { display: none; }.hypothesis-topbar-inner { gap: 30px; }.hypothesis-topbar { height: 68px; }
@media (max-width: 720px) { .hypothesis-page { padding-top: 20px; }.hypothesis-toolbar { justify-content: flex-start; margin-top: 12px; margin-bottom: 26px; }.route-language-note { display: none; } }
.hypothesis-detail-app :deep(.arco-btn) { border-radius: 999px; transition: transform .25s ease, box-shadow .25s ease, background-color .25s ease, color .25s ease; }.hypothesis-language, .hypothesis-theme { height: 38px; padding: 0 15px !important; gap: 7px; border: 1px solid color-mix(in srgb, var(--theme-color) 10%, transparent) !important; color: var(--theme-color) !important; background: color-mix(in srgb, var(--theme-color) 5%, white) !important; box-shadow: 0 8px 22px color-mix(in srgb, var(--theme-color) 9%, transparent); }.hypothesis-theme { color: #5f6b63 !important; }.hypothesis-language:hover, .hypothesis-theme:hover { color: var(--theme-color-hover) !important; background: color-mix(in srgb, var(--theme-color) 10%, white) !important; transform: translateY(-1px); }.hypothesis-detail-app :deep(.arco-btn-primary) { min-height: 38px; padding: 0 18px; border-color: var(--theme-color); background: var(--theme-color); box-shadow: 0 10px 24px color-mix(in srgb, var(--theme-color) 22%, transparent); }.hypothesis-detail-app :deep(.arco-btn-primary:hover) { border-color: var(--theme-color-hover); background: var(--theme-color-hover); box-shadow: 0 14px 30px color-mix(in srgb, var(--theme-color) 30%, transparent); transform: translateY(-2px); }
.hypothesis-header-actions { display: flex; align-items: center; flex-wrap: nowrap; }.hypothesis-header-actions :deep(.arco-btn) { white-space: nowrap; }.hypothesis-header-actions :deep(.arco-btn-primary) { margin-left: 4px; }
@media (max-width: 720px) { .hypothesis-header-actions { gap: 6px; }.hypothesis-header-actions :deep(.arco-btn) { padding: 0 11px !important; }.hypothesis-header-actions :deep(.arco-btn-primary) { margin-left: 0; } }
.hypothesis-breadcrumb { width: max-content; max-width: 100%; padding: 8px 13px; border: 1px solid #e2ebe4; border-radius: 999px; background: rgba(255,255,255,.72); box-shadow: 0 8px 22px rgba(64, 96, 75, .045); }.hypothesis-breadcrumb code { padding: 4px 8px; border: 1px solid #e8eee9; border-radius: 7px; background: #f6f9f6; }.hypothesis-actions { align-items: center; gap: 9px; }.hypothesis-actions a { display: inline-flex; align-items: center; gap: 5px; padding: 8px 13px; border: 1px solid color-mix(in srgb, var(--theme-color) 16%, #e2ebe4); border-radius: 999px; background: rgba(255,255,255,.7); box-shadow: 0 7px 18px rgba(64, 96, 75, .035); }.hypothesis-actions a:hover { border-color: color-mix(in srgb, var(--theme-color) 32%, #e2ebe4); background: color-mix(in srgb, var(--theme-color) 5%, #fff); box-shadow: 0 10px 22px color-mix(in srgb, var(--theme-color) 10%, transparent); }.hypothesis-toolbar { align-items: center; }
@media (max-width: 720px) { .hypothesis-breadcrumb { width: 100%; overflow: hidden; border-radius: 14px; white-space: nowrap; }.hypothesis-actions { width: 100%; flex-wrap: wrap; }.hypothesis-actions a { flex: 1 1 auto; justify-content: center; } }
.detail-breakdown-panel { margin-top: 30px; padding: 0; border: 1px solid color-mix(in srgb, var(--theme-color) 18%, #dfe9e2); border-radius: 18px; background: color-mix(in srgb, var(--theme-color) 4%, #fff); box-shadow: 0 14px 34px rgba(54,82,64,.045); overflow: hidden; }.detail-breakdown-details > summary { display: flex; align-items: center; gap: 18px; padding: 20px 26px; cursor: pointer; list-style: none; }.detail-breakdown-details > summary::-webkit-details-marker { display: none; }.detail-breakdown-summary-copy { display: grid; flex: 1; gap: 3px; }.detail-breakdown-summary-copy .section-kicker { margin: 0; }.detail-breakdown-summary-copy strong { color: #1b2c23; font-size: 18px; }.detail-breakdown-summary-copy small { color: #7b8b81; font-size: 13px; }.detail-breakdown-summary-count { display: grid; min-width: 38px; height: 38px; place-items: center; border-radius: 999px; color: var(--theme-color); background: var(--theme-soft); font: 700 13px ui-monospace, monospace; }.detail-breakdown-details > summary .details-chevron { flex: 0 0 auto; }.detail-breakdown-details-body { padding: 2px 26px 26px; }.detail-breakdown-panel h2 { margin: 8px 0 24px; color: #1b2c23; font-size: 25px; letter-spacing: -.035em; }.detail-breakdown-group { overflow: hidden; border: 1px solid #e2ebe4; border-radius: 14px; background: rgba(255,255,255,.82); }.detail-breakdown-group + .detail-breakdown-group { margin-top: 16px; }.detail-breakdown-heading { display: flex; align-items: center; justify-content: space-between; padding: 15px 18px; border-bottom: 1px solid #e7eee8; color: #24392e; background: #f8fbf8; }.detail-breakdown-heading strong { font-size: 14px; }.detail-breakdown-heading span { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 999px; color: var(--theme-color); background: var(--theme-soft); font: 700 12px ui-monospace, monospace; }.risk-breakdown-group .detail-breakdown-heading { background: #fffaf3; }.risk-breakdown-group .detail-breakdown-heading span { color: #b8771e; background: #b8771e16; }.detail-breakdown-item { display: grid; grid-template-columns: 34px minmax(0,1fr); gap: 12px; padding: 16px 18px; border-bottom: 1px solid #edf2ee; }.detail-breakdown-item:last-child { border-bottom: 0; }.detail-breakdown-item > b { display: grid; width: 28px; height: 24px; place-items: center; border-radius: 7px; color: var(--theme-color); background: var(--theme-soft); font: 700 11px ui-monospace, monospace; letter-spacing: .05em; }.risk-breakdown-group .detail-breakdown-item > b { color: #b8771e; background: #b8771e14; }.detail-breakdown-item strong,.detail-breakdown-item small { display: block; }.detail-breakdown-item strong { color: #394e41; font-size: 14px; line-height: 1.6; }.detail-breakdown-item strong em { color: var(--theme-color); font-style: normal; }.detail-breakdown-item small { margin-top: 5px; color: #7b8b81; font-size: 12px; line-height: 1.65; }
@media (max-width: 720px) { .detail-breakdown-details > summary { padding: 18px 20px; }.detail-breakdown-details-body { padding: 2px 20px 20px; }.detail-breakdown-summary-copy strong { font-size: 16px; }.detail-breakdown-panel h2 { font-size: 23px; }.detail-breakdown-item { padding: 14px 15px; } }
</style>
