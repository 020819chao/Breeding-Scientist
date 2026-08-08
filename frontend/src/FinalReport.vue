<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { IconArrowLeft, IconCheckCircle, IconRight } from "@arco-design/web-vue/es/icon";
import SiteHeader from "./SiteHeader.vue";

const sessionId = window.location.pathname.split("/")[2] || "";
const loading = ref(true);
const error = ref("");
const report = ref<any>(null);
const language = ref<"zh" | "en">(window.location.search.includes("lang=en") ? "en" : "zh");

const isEnglish = computed(() => language.value === "en");
const copy = computed(() => isEnglish.value
  ? {
      home: "Breeding sessions", back: "Back to session", kicker: "BREEDING SCIENTIST / FINAL REPORT",
      title: "Final breeding report", subtitle: "A traceable synthesis of the prioritized routes, evidence, validation plan, and risk decisions.",
      statusReady: "Results passed checks", statusReview: "Review recommended", reportLanguage: "Report language",
      execution: "Execution summary", acceptance: "Acceptance", knowledge: "Knowledge snapshot",
      basedOn: "Generated from the knowledge base snapshot", raw: "View original report text", snapshot: "Snapshot", batch: "Active batch",
      noReport: "The final report is not available yet.", retry: "Retry", loading: "Loading final report…",
    }
  : {
      home: "育种会话", back: "返回当前会话", kicker: "BREEDING SCIENTIST / FINAL REPORT",
      title: "最终育种报告", subtitle: "汇总本次分析形成的优先路线、证据依据、验证方案和风险判断。",
      statusReady: "结果已通过检查", statusReview: "建议复核", reportLanguage: "报告语言",
      execution: "执行摘要", acceptance: "结果验收", knowledge: "知识快照",
      basedOn: "本报告基于当前知识库快照生成", raw: "查看原始报告文本", snapshot: "知识快照", batch: "知识批次",
      noReport: "最终育种报告暂不可用。", retry: "重试", loading: "正在加载最终育种报告…",
    });

const acceptanceReady = computed(() => report.value?.acceptance?.status === "pass");
const hasLanguageSwitch = computed(() => Boolean(report.value?.has_chinese_overview || report.value?.has_english_overview));

async function loadReport() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/sessions/${sessionId}/overview?lang=${language.value}`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    report.value = await response.json();
    language.value = report.value.language || language.value;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Unable to load report";
  } finally {
    loading.value = false;
  }
}

function toggleLanguage() {
  if (!hasLanguageSwitch.value) return;
  language.value = language.value === "zh" ? "en" : "zh";
  loadReport();
}

onMounted(loadReport);
</script>

<template>
  <div class="final-report-app">
    <a-layout>
      <SiteHeader active="sessions" :language="language" @toggle-language="toggleLanguage" />

      <a-layout-content>
        <main class="final-report-page">
          <div v-if="loading" class="final-report-loading"><a-spin :size="32" /><p>{{ copy.loading }}</p></div>
          <a-result v-else-if="error" status="error" :title="copy.noReport" :sub-title="error"><template #extra><a-button type="primary" @click="loadReport">{{ copy.retry }}</a-button></template></a-result>
          <template v-else-if="report">
            <nav class="final-report-breadcrumb" aria-label="breadcrumb">
              <a href="/sessions"><IconArrowLeft />{{ copy.home }}</a><IconRight /><a :href="`/sessions/${sessionId}`">{{ copy.back }}</a><IconRight /><strong>{{ copy.title }}</strong>
            </nav>

            <header class="final-report-hero">
              <div>
                <div class="final-report-kicker"><span></span>{{ copy.kicker }}</div>
                <h1>{{ copy.title }}</h1>
                <p>{{ copy.subtitle }}</p>
              </div>
              <div class="final-report-hero-actions">
                <a-tag v-if="report.acceptance?.available" :class="['final-report-status', acceptanceReady ? 'is-ready' : 'is-review']"><IconCheckCircle />{{ acceptanceReady ? copy.statusReady : copy.statusReview }}</a-tag>
              </div>
            </header>

            <article class="final-report-document markdown-body" v-html="report.overview_html"></article>

            <details class="final-report-advanced">
              <summary><span>{{ isEnglish ? "Audit and source details" : "审计与来源信息" }}</span><span class="details-chevron"></span></summary>
              <div class="final-report-advanced-body">
                <section v-if="report.acceptance?.available"><div><span class="meta-label">{{ copy.acceptance }}</span><strong>{{ acceptanceReady ? copy.statusReady : copy.statusReview }}</strong></div><ul v-if="report.acceptance.failed_checks?.length"><li v-for="item in report.acceptance.failed_checks" :key="item">{{ item }}</li></ul></section>
                <section v-if="report.knowledge_snapshot?.snapshot_id"><div><span class="meta-label">{{ copy.snapshot }}</span><code>{{ report.knowledge_snapshot.snapshot_id }}</code></div><div v-if="report.knowledge_snapshot.active_batch_id"><span class="meta-label">{{ copy.batch }}</span><code>{{ report.knowledge_snapshot.active_batch_id }}</code></div></section>
                <details class="final-report-raw"><summary>{{ copy.raw }}</summary><pre>{{ report.overview_md }}</pre></details>
              </div>
            </details>
          </template>
        </main>
      </a-layout-content>
    </a-layout>
  </div>
</template>

<style scoped>
.final-report-app { min-height: 100vh; color: #17241f; background: radial-gradient(circle at 8% 0%, color-mix(in srgb, var(--theme-color) 8%, transparent), transparent 34rem), #f7faf8; }
.final-report-topbar { height: 72px; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; border-bottom: 1px solid #e1ebe4; background: rgba(255,255,255,.9); backdrop-filter: blur(18px); }
.final-report-brand { display: inline-flex; align-items: center; gap: 10px; color: #17241f; text-decoration: none; }.final-report-mark { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 11px; color: #fff; background: var(--theme-color, #17845b); font: 700 12px ui-monospace, monospace; box-shadow: 0 8px 20px color-mix(in srgb, var(--theme-color) 25%, transparent); }.final-report-brand strong,.final-report-brand small { display: block; }.final-report-brand strong { font-size: 15px; letter-spacing: -.025em; }.final-report-brand small { margin-top: 2px; color: #87968e; font-size: 10px; }
.final-report-nav { display: flex; align-items: center; gap: 25px; }.final-report-nav a { color: #65736b; text-decoration: none; font-size: 13px; }.final-report-nav a:hover { color: var(--theme-color, #17845b); }.final-report-new-session { min-height: 40px; padding: 0 20px; border-radius: 999px; color: #fff !important; background: var(--theme-color, #17845b); box-shadow: 0 9px 22px color-mix(in srgb, var(--theme-color) 22%, transparent); font-weight: 650; }
.final-report-page { width: min(1200px, calc(100% - 48px)); margin: 0 auto; padding: 42px 0 88px; }.final-report-breadcrumb { display: flex; align-items: center; gap: 10px; margin-bottom: 24px; color: #809087; font-size: 13px; }.final-report-breadcrumb a { display: inline-flex; align-items: center; gap: 5px; color: #b8771e; text-decoration: none; }.final-report-breadcrumb strong { color: #33493c; font-weight: 600; }
.final-report-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 26px; padding: 36px 42px 40px; border: 1px solid #deebe2; border-radius: 24px; background: linear-gradient(135deg, rgba(255,255,255,.96), color-mix(in srgb, var(--theme-color) 5%, #fff)); box-shadow: 0 20px 48px rgba(54,82,64,.06); }.final-report-kicker { display: flex; align-items: center; gap: 10px; color: #b8771e; font: 700 11px ui-monospace, monospace; letter-spacing: .14em; }.final-report-kicker span { width: 22px; height: 1px; background: #b8771e; }.final-report-hero h1 { margin: 13px 0 10px; color: #13231c; font-size: clamp(38px, 5vw, 64px); letter-spacing: -.06em; line-height: 1.02; }.final-report-hero p { max-width: 720px; margin: 0; color: #72847a; font-size: 16px; line-height: 1.7; }.final-report-hero-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: flex-end; }.final-report-status { display: inline-flex; align-items: center; gap: 6px; padding: 9px 13px; border: 1px solid #c8e5d1; border-radius: 999px; color: #278b55; background: #f3fbf5; }.final-report-status.is-review { border-color: #eed5ae; color: #af741f; background: #fff9ef; }.final-report-language { display: inline-flex; align-items: center; gap: 7px; padding: 9px 14px; border: 1px solid #e0e9e2; border-radius: 999px; color: var(--theme-color, #17845b); background: #fff; cursor: pointer; transition: .2s ease; }.final-report-language:hover { border-color: var(--theme-color); box-shadow: 0 6px 16px rgba(54,82,64,.08); transform: translateY(-1px); }
.final-report-meta-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 18px 0; }.final-report-meta-card { min-height: 118px; padding: 20px 22px; border: 1px solid #dfebe2; border-radius: 16px; background: rgba(255,255,255,.86); box-shadow: 0 10px 26px rgba(54,82,64,.035); }.meta-label { display: block; margin-bottom: 9px; color: #8a998f; font-size: 12px; letter-spacing: .05em; }.final-report-meta-card strong { display: block; overflow: hidden; color: #274033; font-size: 19px; text-overflow: ellipsis; white-space: nowrap; }.final-report-meta-card small { display: block; margin-top: 7px; color: #8a998f; line-height: 1.5; }.meta-ready { color: #268a52 !important; }.meta-review { color: #b8771e !important; }
.final-report-document { margin-top: 18px; padding: 40px 48px 52px; border: 1px solid #dfebe2; border-radius: 20px; background: rgba(255,255,255,.92); box-shadow: 0 18px 42px rgba(54,82,64,.05); }.final-report-document :deep(h1) { margin: 0 0 18px; color: #173025; font-size: 34px; letter-spacing: -.05em; }.final-report-document :deep(h2) { margin: 42px 0 18px; padding-top: 26px; border-top: 1px solid #e7efe9; color: #193229; font-size: 28px; letter-spacing: -.04em; }.final-report-document :deep(h3) { margin: 30px 0 12px; color: #2d4939; font-size: 21px; }.final-report-document :deep(p) { margin: 0 0 16px; color: #536c5e; font-size: 16px; line-height: 1.9; }.final-report-document :deep(strong) { color: #264b38; }.final-report-document :deep(a) { color: #b8771e; text-underline-offset: 3px; }.final-report-document :deep(ul),.final-report-document :deep(ol) { margin: 14px 0 22px; padding-left: 24px; }.final-report-document :deep(li) { margin: 11px 0; color: #536c5e; font-size: 15px; line-height: 1.85; }.final-report-document :deep(li::marker) { color: var(--theme-color); }.final-report-document :deep(.table-wrapper) { overflow-x: auto; margin: 20px 0 28px; border: 1px solid #e1ebe4; border-radius: 14px; }.final-report-document :deep(table) { width: 100%; min-width: 760px; border-collapse: collapse; font-size: 14px; }.final-report-document :deep(th) { color: #2f493c; background: #f5faf6; font-weight: 700; }.final-report-document :deep(th),.final-report-document :deep(td) { padding: 14px 15px; border-bottom: 1px solid #e7efe9; text-align: left; vertical-align: top; line-height: 1.65; }.final-report-document :deep(td) { color: #5b7164; }.final-report-document :deep(tr:last-child td) { border-bottom: 0; }
.final-report-advanced { margin-top: 18px; border: 1px solid #dfebe2; border-radius: 16px; background: rgba(255,255,255,.75); }.final-report-advanced > summary { display: flex; align-items: center; justify-content: space-between; padding: 18px 22px; color: #4d6859; cursor: pointer; list-style: none; }.final-report-advanced > summary::-webkit-details-marker,.final-report-raw > summary::-webkit-details-marker { display: none; }.final-report-advanced-body { display: grid; gap: 18px; padding: 0 22px 22px; }.final-report-advanced-body section { display: flex; align-items: center; flex-wrap: wrap; gap: 20px; padding-top: 18px; border-top: 1px solid #e8efe9; }.final-report-advanced-body section strong { color: #2b8b55; }.final-report-advanced-body code { padding: 5px 8px; border-radius: 7px; color: #667e70; background: #f2f7f3; }.final-report-advanced-body ul { flex-basis: 100%; margin: 0; padding-left: 20px; color: #b8771e; }.final-report-raw { border-top: 1px solid #e8efe9; padding-top: 18px; }.final-report-raw > summary { color: #b8771e; cursor: pointer; }.final-report-raw pre { max-height: 420px; overflow: auto; margin: 16px 0 0; padding: 16px; border-radius: 10px; color: #6b7d72; background: #f7faf8; font: 12px/1.7 ui-monospace, monospace; white-space: pre-wrap; }
.final-report-loading { display: grid; min-height: 60vh; place-items: center; align-content: center; gap: 14px; color: #7d9083; }.final-report-loading p { margin: 0; }.details-chevron { width: 9px; height: 9px; border-right: 1.5px solid #8ea095; border-bottom: 1.5px solid #8ea095; transform: rotate(45deg) translateY(-2px); transition: transform .2s ease; }.final-report-advanced[open] > summary .details-chevron { transform: rotate(225deg) translate(-1px, -1px); }
@media (max-width: 800px) { .final-report-topbar { padding: 0 20px; }.final-report-nav a:not(.final-report-new-session) { display: none; }.final-report-page { width: min(100% - 28px, 720px); padding-top: 26px; }.final-report-hero { display: block; padding: 28px 24px; }.final-report-hero-actions { justify-content: flex-start; margin-top: 24px; }.final-report-meta-grid { grid-template-columns: 1fr; }.final-report-document { padding: 30px 24px 38px; }.final-report-document :deep(h1) { font-size: 30px; }.final-report-document :deep(h2) { font-size: 25px; } }
</style>
