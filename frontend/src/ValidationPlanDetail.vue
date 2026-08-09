<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { IconArrowLeft, IconRight } from "@arco-design/web-vue/es/icon";
import SiteHeader from "./SiteHeader.vue";
import { appPathname } from "./path";

const parts = appPathname().split("/").filter(Boolean);
const sessionId = parts[1] || "";
const artifactPath = appPathname().split("/artifacts/")[1] || "";
const loading = ref(true);
const error = ref("");
const payload = ref<any>(null);
const language = ref<"zh" | "en">((localStorage.getItem("co-scientist-language") as "zh" | "en") || "zh");

const plan = computed(() => {
  try {
    return payload.value?.content ? JSON.parse(payload.value.content) : {};
  } catch {
    return {};
  }
});
const isEnglish = computed(() => language.value === "en");
const readinessLabel = computed(() => {
  if (plan.value.readiness_level === "ready") return isEnglish.value ? "Ready for validation" : "可以进入验证";
  if (plan.value.readiness_level === "needs_preflight") return isEnglish.value ? "Preflight required" : "需要前置确认";
  return plan.value.readiness_level || (isEnglish.value ? "Pending" : "待确认");
});

function toggleLanguage() {
  language.value = language.value === "zh" ? "en" : "zh";
  localStorage.setItem("co-scientist-language", language.value);
}
function display(value: unknown) {
  return Array.isArray(value) ? value.join("、") : String(value ?? "—");
}
async function loadPlan() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/sessions/${sessionId}/artifacts/${artifactPath}`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    payload.value = await response.json();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "验证计划加载失败";
  } finally {
    loading.value = false;
  }
}
onMounted(loadPlan);
</script>

<template>
  <div class="validation-plan-app">
    <SiteHeader active="sessions" :language="language" @toggle-language="toggleLanguage" />
    <main class="validation-plan-page">
      <div v-if="loading" class="validation-plan-loading"><a-spin :size="32" /><span>正在加载验证计划...</span></div>
      <a-result v-else-if="error" status="error" title="验证计划暂不可用" :sub-title="error"><template #extra><a-button type="primary" @click="loadPlan">重试</a-button></template></a-result>
      <template v-else>
        <nav class="validation-plan-breadcrumb"><a :href="`/sessions/${sessionId}/agent-outputs?agent=Validation%20Planner`"><IconArrowLeft />返回验证规划</a><IconRight /><strong>验证计划</strong></nav>
        <header class="validation-plan-hero"><div><p class="validation-plan-kicker">VALIDATION PLANNER / RESULT DETAIL</p><h1>验证计划</h1><p>{{ plan.hypothesis_title || "对应育种路线" }}</p></div><div class="validation-plan-status"><strong>{{ plan.validation_readiness_score ?? "—" }}</strong><span>{{ readinessLabel }}</span></div></header>
        <section class="validation-plan-intro"><span class="validation-plan-kicker">研究背景</span><p>{{ plan.research_goal || "—" }}</p></section>

        <section class="validation-plan-metrics"><article><strong>{{ plan.validation_readiness_score ?? "—" }}</strong><span>验证准备度</span></article><article><strong>{{ plan.evidence_basis?.germplasm_hits ?? "—" }}</strong><span>材料证据命中</span></article><article><strong>{{ plan.evidence_basis?.marker_qtl_hits ?? "—" }}</strong><span>标记/QTL 命中</span></article><article><strong>{{ plan.field_trial_design?.replication ?? "—" }}</strong><span>试验重复</span></article></section>

        <section class="validation-plan-section"><header><span class="validation-plan-kicker">01 / BREEDING GOAL</span><h2>本次验证什么？</h2></header><dl class="validation-plan-detail-grid"><dt>作物</dt><dd>{{ plan.breeding_goal?.crop || "—" }}</dd><dt>目标性状</dt><dd>{{ plan.breeding_goal?.target_trait || "—" }}</dd><dt>目标环境</dt><dd>{{ plan.breeding_goal?.target_environment || "—" }}</dd><dt>候选基因/标记</dt><dd>{{ display(plan.breeding_goal?.candidate_genes_qtl_markers) }}</dd></dl></section>

        <div class="validation-plan-columns"><section class="validation-plan-section"><header><span class="validation-plan-kicker">02 / MATERIALS</span><h2>材料与对照</h2></header><div class="validation-plan-list"><div><strong>所需材料</strong><p>{{ display(plan.materials_plan?.required_materials) }}</p></div><div><strong>对照材料</strong><p>{{ display(plan.materials_plan?.controls) }}</p></div><div><strong>可获得性确认</strong><p>{{ plan.materials_plan?.availability_check || "—" }}</p></div></div></section><section class="validation-plan-section"><header><span class="validation-plan-kicker">03 / GENOTYPING</span><h2>基因型验证</h2></header><div class="validation-plan-list"><div><strong>目标</strong><p>{{ plan.genotyping_plan?.objective || "—" }}</p></div><div><strong>检测方法</strong><p>{{ plan.genotyping_plan?.assay || "—" }}</p></div><div><strong>继续条件</strong><p>{{ plan.genotyping_plan?.go_no_go || "—" }}</p></div></div></section></div>

        <section class="validation-plan-section"><header><span class="validation-plan-kicker">04 / PHENOTYPING & FIELD TRIAL</span><h2>如何开展验证？</h2></header><div class="validation-plan-test-grid"><article><strong>表型测定</strong><p>{{ plan.phenotyping_plan?.protocol || "—" }}</p><small>{{ display(plan.phenotyping_plan?.timepoints) }}</small></article><article><strong>田间试验设计</strong><p>{{ plan.field_trial_design?.design || "—" }}</p><small>{{ plan.field_trial_design?.replication || "—" }}</small></article><article><strong>推进判定</strong><p>{{ plan.field_trial_design?.decision_thresholds || "—" }}</p></article></div></section>

        <section v-if="plan.critical_evidence_gaps?.length" class="validation-plan-gaps"><header><span class="validation-plan-kicker">05 / OPEN ITEMS</span><h2>验证前还需要确认什么？</h2></header><ul><li v-for="gap in plan.critical_evidence_gaps" :key="`${gap.type}-${gap.message}`"><b>{{ gap.severity }}</b><span>{{ gap.message }}</span></li></ul></section>
        <details class="validation-plan-raw"><summary>查看原始计划数据<span></span></summary><pre>{{ payload.content }}</pre></details>
      </template>
    </main>
  </div>
</template>

<style scoped>
.validation-plan-app{min-height:100vh;color:#172a20;background:radial-gradient(circle at 7% 0%,color-mix(in srgb,var(--theme-color) 9%,transparent),transparent 34rem),#f7faf8}.validation-plan-page{width:min(1260px,calc(100% - 56px));margin:0 auto;padding:34px 0 86px}.validation-plan-breadcrumb{display:flex;align-items:center;gap:9px;margin-bottom:23px;color:#718279;font-size:14px}.validation-plan-breadcrumb a{display:inline-flex;align-items:center;gap:6px;color:var(--theme-color);font-weight:700;text-decoration:none}.validation-plan-breadcrumb strong{color:#52675b;font-weight:600}.validation-plan-kicker{color:var(--theme-color);font:700 11px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.1em}.validation-plan-hero{display:flex;align-items:flex-start;justify-content:space-between;gap:28px;padding:29px 31px;border:1px solid #deebe2;border-radius:21px;background:linear-gradient(135deg,#fff,color-mix(in srgb,var(--theme-color) 5%,#fff));box-shadow:0 16px 36px rgba(49,78,60,.05)}.validation-plan-hero h1{margin:13px 0 8px;color:#173027;font-size:clamp(38px,5vw,57px);letter-spacing:-.06em;line-height:1.05}.validation-plan-hero p:not(.validation-plan-kicker){max-width:850px;margin:0;color:#6c8073;font-size:16px;line-height:1.7}.validation-plan-status{display:grid;min-width:130px;padding:14px 16px;border:1px solid #dce9df;border-radius:15px;color:var(--theme-color);background:var(--theme-soft);text-align:center}.validation-plan-status strong{font:700 30px ui-monospace,monospace}.validation-plan-status span{margin-top:6px;font-size:12px;font-weight:700}.validation-plan-intro{margin-top:18px;padding:20px 23px;border-left:4px solid var(--theme-color);border-radius:13px;background:#fff;box-shadow:0 8px 23px rgba(49,78,60,.04)}.validation-plan-intro p{margin:9px 0 0;color:#61756a;font-size:14px;line-height:1.8}.validation-plan-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0 34px}.validation-plan-metrics article{min-height:94px;padding:17px;border:1px solid #e0eae3;border-radius:14px;background:#fff}.validation-plan-metrics strong,.validation-plan-metrics span{display:block}.validation-plan-metrics strong{color:var(--theme-color);font:700 23px ui-monospace,monospace}.validation-plan-metrics span{margin-top:9px;color:#73857a;font-size:12px}.validation-plan-section{margin:0 0 25px;padding:23px 25px;border:1px solid #e0eae3;border-radius:17px;background:rgba(255,255,255,.9);box-shadow:0 8px 22px rgba(49,78,60,.035)}.validation-plan-section header,.validation-plan-gaps header{margin-bottom:17px}.validation-plan-section h2,.validation-plan-gaps h2{margin:7px 0 0;color:#233f31;font-size:25px;letter-spacing:-.045em}.validation-plan-detail-grid{display:grid;grid-template-columns:125px minmax(0,1fr);gap:11px 18px;margin:0}.validation-plan-detail-grid dt{color:#87978e;font-size:12px}.validation-plan-detail-grid dd{margin:0;color:#526a5d;font-size:13px;line-height:1.65;overflow-wrap:anywhere}.validation-plan-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:17px}.validation-plan-list{display:grid;gap:12px}.validation-plan-list div{padding:13px 14px;border:1px solid #e7eee9;border-radius:11px;background:#fbfdfb}.validation-plan-list strong{color:#537064;font-size:12px}.validation-plan-list p{margin:6px 0 0;color:#65796d;font-size:13px;line-height:1.7}.validation-plan-test-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.validation-plan-test-grid article{padding:16px;border:1px solid #e5eee8;border-radius:12px;background:#fbfdfb}.validation-plan-test-grid strong{color:#49695a;font-size:13px}.validation-plan-test-grid p{margin:9px 0 8px;color:#63786b;font-size:13px;line-height:1.7}.validation-plan-test-grid small{color:#87988e;font-size:11px;line-height:1.6}.validation-plan-gaps{margin-bottom:25px;padding:23px 25px;border:1px solid #eadfc9;border-left:5px solid #b8771e;border-radius:17px;background:#fffaf2}.validation-plan-gaps ul{display:grid;gap:9px;margin:0;padding:0;list-style:none}.validation-plan-gaps li{display:flex;align-items:flex-start;gap:10px;padding:11px 13px;border:1px solid #efdfbd;border-radius:10px;background:rgba(255,255,255,.7);color:#746852;font-size:13px;line-height:1.6}.validation-plan-gaps b{flex:0 0 auto;padding:3px 7px;border-radius:999px;color:#a66e1a;background:#fff0d5;font-size:10px}.validation-plan-raw{border:1px solid #dfe9e2;border-radius:14px;background:#fff}.validation-plan-raw summary{padding:15px 18px;color:#65786c;font-size:13px;font-weight:700;cursor:pointer;list-style:none}.validation-plan-raw summary::-webkit-details-marker{display:none}.validation-plan-raw summary span{float:right;width:8px;height:8px;margin-top:3px;border-right:1.5px solid #8ea095;border-bottom:1.5px solid #8ea095;transform:rotate(45deg)}.validation-plan-raw pre{max-height:420px;overflow:auto;margin:0;padding:17px;border-top:1px solid #e8efea;background:#f7faf8;font-size:11px;line-height:1.6;white-space:pre-wrap}.validation-plan-loading{display:grid;min-height:64vh;place-items:center;align-content:center;gap:12px;color:#7d9083}@media(max-width:850px){.validation-plan-page{width:min(100% - 34px,720px)}.validation-plan-hero{display:block}.validation-plan-status{width:fit-content;margin-top:18px}.validation-plan-metrics{grid-template-columns:repeat(2,1fr)}.validation-plan-columns,.validation-plan-test-grid{grid-template-columns:1fr}}@media(max-width:520px){.validation-plan-page{width:calc(100% - 24px);padding-top:24px}.validation-plan-hero,.validation-plan-section,.validation-plan-gaps{padding:20px 17px}.validation-plan-hero h1{font-size:40px}.validation-plan-detail-grid{grid-template-columns:1fr;gap:3px}.validation-plan-detail-grid dd{margin-bottom:8px}}
</style>
