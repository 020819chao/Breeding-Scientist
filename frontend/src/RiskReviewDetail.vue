<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { IconArrowLeft, IconRight } from "@arco-design/web-vue/es/icon";
import SiteHeader from "./SiteHeader.vue";

const parts = window.location.pathname.split("/").filter(Boolean);
const sessionId = parts[1] || "";
const artifactPath = window.location.pathname.split("/artifacts/")[1] || "";
const loading = ref(true);
const error = ref("");
const payload = ref<any>(null);
const language = ref<"zh" | "en">((localStorage.getItem("co-scientist-language") as "zh" | "en") || "zh");
const review = computed(() => payload.value?.content ? JSON.parse(payload.value.content) : {});
const record = computed(() => review.value.record || {});
const isEnglish = computed(() => language.value === "en");
const verdictLabel = computed(() => record.value.verdict === "missing_piece" ? "需要补充证据" : record.value.verdict || "待确认");
const scoreItems = computed(() => [
  ["正确性", record.value.correctness], ["可测试性", record.value.testability],
  ["可行性", record.value.feasibility], ["材料可获得性", record.value.material_availability],
  ["标记准备度", record.value.marker_readiness], ["G×E 风险", record.value.gxe_risk],
]);
function toggleLanguage() { language.value = language.value === "zh" ? "en" : "zh"; localStorage.setItem("co-scientist-language", language.value); }
async function loadReview() {
  loading.value = true; error.value = "";
  try {
    const response = await fetch(`/api/sessions/${sessionId}/artifacts/${artifactPath}`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    payload.value = await response.json();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "风险评审加载失败"; }
  finally { loading.value = false; }
}
onMounted(loadReview);
</script>

<template>
  <div class="risk-review-app">
    <SiteHeader active="sessions" :language="language" @toggle-language="toggleLanguage" />
    <main class="risk-review-page">
      <div v-if="loading" class="risk-review-loading"><a-spin :size="32" /><span>正在加载风险评审...</span></div>
      <a-result v-else-if="error" status="error" title="风险评审暂不可用" :sub-title="error"><template #extra><a-button type="primary" @click="loadReview">重试</a-button></template></a-result>
      <template v-else>
        <nav class="risk-review-breadcrumb"><a :href="`/sessions/${sessionId}/agent-outputs?agent=Risk%20Reviewer`"><IconArrowLeft />返回风险评审</a><IconRight /><strong>风险评审详情</strong></nav>
        <header class="risk-review-hero"><div><p class="risk-review-kicker">RISK REVIEWER / RESULT DETAIL</p><h1>风险评审</h1><p>针对当前育种假设的证据完整性、可执行性与推进风险评估。</p></div><div class="risk-review-status"><strong>{{ verdictLabel }}</strong><span>{{ record.kind === "full" ? "完整评审" : record.kind || "评审结果" }}</span></div></header>
        <section class="risk-review-summary"><span class="risk-review-kicker">当前结论</span><p>{{ review.notes || "本次评审尚未提供文字结论。" }}</p><a v-if="review.hypothesis_id" :href="`/sessions/${sessionId}/hypotheses/${review.hypothesis_id}`">查看对应假设 <IconRight /></a></section>
        <section class="risk-review-section"><header><span class="risk-review-kicker">01 / SCORES</span><h2>风险与可执行性评分</h2></header><div class="risk-review-score-grid"><article v-for="item in scoreItems" :key="item[0]"><strong>{{ item[1] == null ? "—" : item[1] }}</strong><span>{{ item[0] }}</span><i v-if="item[1] != null" :style="{ width: `${Number(item[1]) * 100}%` }"></i></article></div></section>
        <section v-if="record.assumptions?.length" class="risk-review-section"><header><span class="risk-review-kicker">02 / ASSUMPTIONS</span><h2>哪些前提还不稳固？</h2></header><div class="risk-review-assumption-list"><article v-for="assumption in record.assumptions" :key="assumption.assumption"><div><strong>{{ assumption.plausibility }}</strong><span>{{ assumption.assumption }}</span></div><p>{{ assumption.rationale }}</p></article></div></section>
        <section v-if="record.evidence?.length" class="risk-review-section"><header><span class="risk-review-kicker">03 / EVIDENCE</span><h2>评审依据</h2></header><div class="risk-review-evidence-list"><article v-for="evidence in record.evidence" :key="evidence.claim"><p>{{ evidence.claim }}</p><a v-if="evidence.url" :href="evidence.url" target="_blank" rel="noreferrer">查看来源 <IconRight /></a></article></div></section>
        <details class="risk-review-raw"><summary>查看原始评审数据<span></span></summary><pre>{{ payload.content }}</pre></details>
      </template>
    </main>
  </div>
</template>

<style scoped>
.risk-review-app{min-height:100vh;color:#172a20;background:radial-gradient(circle at 7% 0%,color-mix(in srgb,var(--theme-color) 9%,transparent),transparent 34rem),#f7faf8}.risk-review-page{width:min(1260px,calc(100% - 56px));margin:0 auto;padding:34px 0 86px}.risk-review-breadcrumb{display:flex;align-items:center;gap:9px;margin-bottom:23px;color:#718279;font-size:14px}.risk-review-breadcrumb a{display:inline-flex;align-items:center;gap:6px;color:var(--theme-color);font-weight:700;text-decoration:none}.risk-review-breadcrumb strong{color:#52675b;font-weight:600}.risk-review-kicker{color:var(--theme-color);font:700 11px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.1em}.risk-review-hero{display:flex;align-items:flex-start;justify-content:space-between;gap:28px;padding:29px 31px;border:1px solid #deebe2;border-radius:21px;background:linear-gradient(135deg,#fff,color-mix(in srgb,var(--theme-color) 5%,#fff));box-shadow:0 16px 36px rgba(49,78,60,.05)}.risk-review-hero h1{margin:13px 0 8px;color:#173027;font-size:clamp(38px,5vw,57px);letter-spacing:-.06em;line-height:1.05}.risk-review-hero p:not(.risk-review-kicker){margin:0;color:#6c8073;font-size:16px;line-height:1.7}.risk-review-status{display:grid;min-width:145px;padding:14px 16px;border:1px solid #eadfc9;border-radius:15px;color:#a66e1a;background:#fff8eb;text-align:center}.risk-review-status strong{font-size:18px}.risk-review-status span{margin-top:6px;color:#8c806c;font-size:12px}.risk-review-summary{margin:18px 0 25px;padding:21px 24px;border-left:4px solid #b8771e;border-radius:13px;background:#fffaf2;box-shadow:0 8px 23px rgba(49,78,60,.04)}.risk-review-summary p{margin:9px 0 13px;color:#61756a;font-size:14px;line-height:1.85;white-space:pre-wrap}.risk-review-summary a,.risk-review-evidence-list a{display:inline-flex;align-items:center;gap:4px;color:var(--theme-color);font-size:13px;font-weight:700;text-decoration:none}.risk-review-section{margin:0 0 25px;padding:23px 25px;border:1px solid #e0eae3;border-radius:17px;background:rgba(255,255,255,.9);box-shadow:0 8px 22px rgba(49,78,60,.035)}.risk-review-section header{margin-bottom:17px}.risk-review-section h2{margin:7px 0 0;color:#233f31;font-size:25px;letter-spacing:-.045em}.risk-review-score-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.risk-review-score-grid article{position:relative;min-height:85px;padding:15px;border:1px solid #e5eee8;border-radius:12px;background:#fbfdfb;overflow:hidden}.risk-review-score-grid strong,.risk-review-score-grid span{display:block}.risk-review-score-grid strong{color:var(--theme-color);font:700 23px ui-monospace,monospace}.risk-review-score-grid span{margin-top:7px;color:#718379;font-size:12px}.risk-review-score-grid i{position:absolute;right:15px;bottom:13px;left:15px;height:3px;border-radius:3px;background:linear-gradient(90deg,var(--theme-color),#dfe9e2)}.risk-review-assumption-list,.risk-review-evidence-list{display:grid;gap:10px}.risk-review-assumption-list article,.risk-review-evidence-list article{padding:14px 15px;border:1px solid #e5eee8;border-radius:12px;background:#fbfdfb}.risk-review-assumption-list article>div{display:flex;align-items:flex-start;gap:10px}.risk-review-assumption-list strong{flex:0 0 auto;padding:4px 8px;border-radius:999px;color:#a66e1a;background:#fff0d5;font-size:11px}.risk-review-assumption-list span{color:#405d4d;font-size:13px;line-height:1.6}.risk-review-assumption-list p{margin:8px 0 0;padding-left:2px;color:#718379;font-size:12px;line-height:1.7}.risk-review-evidence-list article{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.risk-review-evidence-list p{margin:0;color:#60756a;font-size:13px;line-height:1.7}.risk-review-evidence-list a{flex:0 0 auto}.risk-review-raw{border:1px solid #dfe9e2;border-radius:14px;background:#fff}.risk-review-raw summary{padding:15px 18px;color:#65786c;font-size:13px;font-weight:700;cursor:pointer;list-style:none}.risk-review-raw summary::-webkit-details-marker{display:none}.risk-review-raw summary span{float:right;width:8px;height:8px;margin-top:3px;border-right:1.5px solid #8ea095;border-bottom:1.5px solid #8ea095;transform:rotate(45deg)}.risk-review-raw pre{max-height:420px;overflow:auto;margin:0;padding:17px;border-top:1px solid #e8efea;background:#f7faf8;font-size:11px;line-height:1.6;white-space:pre-wrap}.risk-review-loading{display:grid;min-height:64vh;place-items:center;align-content:center;gap:12px;color:#7d9083}@media(max-width:750px){.risk-review-page{width:calc(100% - 34px)}.risk-review-hero{display:block}.risk-review-status{width:fit-content;margin-top:18px}.risk-review-score-grid{grid-template-columns:repeat(2,1fr)}.risk-review-evidence-list article{display:block}.risk-review-evidence-list a{margin-top:8px}}@media(max-width:500px){.risk-review-page{width:calc(100% - 24px);padding-top:24px}.risk-review-hero,.risk-review-section{padding:20px 17px}.risk-review-score-grid{grid-template-columns:1fr}}
</style>
