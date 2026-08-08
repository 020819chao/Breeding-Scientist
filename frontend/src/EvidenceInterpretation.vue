<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { IconArrowLeft, IconCheckCircle, IconRight } from "@arco-design/web-vue/es/icon";
import SiteHeader from "./SiteHeader.vue";

const pathParts = window.location.pathname.split("/");
const sessionId = pathParts[2] || "";
const artifactPath = window.location.pathname.split("/artifacts/")[1] || "";
const loading = ref(true);
const error = ref("");
const payload = ref<any>(null);
const language = ref<"zh" | "en">((localStorage.getItem("co-scientist-language") as "zh" | "en") || "zh");

const evidence = computed(() => payload.value?.evidence_view || null);
const isEnglish = computed(() => language.value === "en");

function toggleLanguage() {
  language.value = language.value === "zh" ? "en" : "zh";
  localStorage.setItem("co-scientist-language", language.value);
}

async function loadArtifact() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/sessions/${sessionId}/artifacts/${artifactPath}`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    payload.value = await response.json();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "证据解读加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(loadArtifact);
</script>

<template>
  <div class="evidence-interpretation-app">
    <SiteHeader active="sessions" :language="language" @toggle-language="toggleLanguage" />
    <main class="evidence-interpretation-page">
      <div v-if="loading" class="evidence-interpretation-loading"><a-spin :size="32" /><span>{{ isEnglish ? "Loading evidence interpretation…" : "正在加载证据解读…" }}</span></div>
      <a-result v-else-if="error" status="error" :title="isEnglish ? 'Evidence interpretation unavailable' : '证据解读暂不可用'" :sub-title="error"><template #extra><a-button type="primary" @click="loadArtifact">{{ isEnglish ? "Retry" : "重试" }}</a-button></template></a-result>
      <template v-else-if="evidence">
        <nav class="evidence-interpretation-breadcrumb" aria-label="breadcrumb">
          <a :href="`/sessions/${sessionId}`"><IconArrowLeft />{{ isEnglish ? "Back to breeding session" : "返回育种会话" }}</a><IconRight /><strong>{{ isEnglish ? "Evidence interpretation" : "证据解读" }}</strong>
        </nav>

        <header class="evidence-interpretation-hero">
          <div>
            <p class="evidence-interpretation-kicker">EVIDENCE CURATOR · 证据整理</p>
            <h1>{{ isEnglish ? "Evidence interpretation" : "证据解读" }}</h1>
            <p class="evidence-interpretation-goal">{{ isEnglish ? "Research goal: " : "研究目标：" }}{{ evidence.research_goal }}</p>
          </div>
          <span class="evidence-interpretation-status"><i></i>{{ evidence.status }}</span>
        </header>

        <section class="evidence-interpretation-conclusion">
          <div class="evidence-interpretation-kicker">{{ isEnglish ? "CURRENT ASSESSMENT" : "当前判断" }}</div>
          <h2>{{ evidence.support_label }}</h2>
          <p>{{ evidence.conclusion }}</p>
        </section>

        <section class="evidence-interpretation-section evidence-source-section">
          <header><div class="evidence-interpretation-kicker">{{ isEnglish ? "EVIDENCE COVERAGE" : "证据覆盖" }}</div><h2>{{ isEnglish ? "What did we find?" : "我们查到了什么" }}</h2></header>
          <div class="evidence-source-grid">
            <article v-for="source in evidence.source_groups" :key="source.label"><strong>{{ source.count }}</strong><span>{{ source.label }}</span></article>
          </div>
        </section>

        <section v-if="evidence.key_findings?.length" class="evidence-interpretation-section">
          <header><div class="evidence-interpretation-kicker">{{ isEnglish ? "KEY FINDINGS" : "关键发现" }}</div><h2>{{ isEnglish ? "What do these findings tell us?" : "这些证据说明了什么" }}</h2></header>
          <div class="evidence-finding-grid">
            <article v-for="finding in evidence.key_findings" :key="`${finding.source_label}-${finding.title}`" class="evidence-finding-card">
              <div class="evidence-finding-meta"><span>{{ finding.source_label }}</span><span>{{ finding.confidence }}</span></div>
              <h3>{{ finding.title }}</h3><p>{{ finding.summary }}</p>
              <a v-if="finding.source_url" :href="finding.source_url" target="_blank" rel="noreferrer">{{ isEnglish ? "View source" : "查看来源" }} <span>↗</span></a>
            </article>
          </div>
        </section>

        <section v-if="evidence.gaps?.length" class="evidence-interpretation-section evidence-gaps-section">
          <header><div class="evidence-interpretation-kicker">{{ isEnglish ? "EVIDENCE BOUNDARY" : "证据边界" }}</div><h2>{{ isEnglish ? "What remains uncertain?" : "目前还不能确定什么" }}</h2></header>
          <div class="evidence-gap-list"><article v-for="gap in evidence.gaps" :key="`${gap.label}-${gap.message}`"><div><strong>{{ gap.label }}</strong><span>{{ gap.severity }}</span></div><p>{{ gap.message }}</p></article></div>
        </section>

        <section class="evidence-interpretation-section evidence-next-steps">
          <header><div class="evidence-interpretation-kicker">{{ isEnglish ? "NEXT STEP" : "下一步" }}</div><h2>{{ isEnglish ? "How should we proceed?" : "建议如何推进" }}</h2></header>
          <ol><li v-for="step in evidence.next_steps" :key="step">{{ step }}</li></ol>
        </section>

        <details class="evidence-interpretation-details"><summary>{{ isEnglish ? "View evidence source details" : "查看证据来源详情" }}<span></span></summary><dl><dt>成果类型</dt><dd>六智能体成果文件</dd><dt>知识快照</dt><dd>{{ evidence.snapshot_id }}</dd><dt>知识批次</dt><dd>{{ evidence.batch_id }}</dd><dt>检索模式</dt><dd>{{ evidence.search_mode }}</dd><dt>原始文件</dt><dd>{{ payload.artifact_path }}</dd></dl></details>
        <details class="evidence-interpretation-details"><summary>{{ isEnglish ? "View raw evidence data (JSON)" : "查看原始证据数据（JSON）" }}<span></span></summary><pre>{{ evidence.raw_json }}</pre></details>
      </template>
      <section v-else class="evidence-interpretation-empty"><strong>{{ payload?.artifact_name || "成果文件" }}</strong><p>当前文件不是可解读的证据包。</p><pre>{{ payload?.content }}</pre></section>
    </main>
  </div>
</template>

<style scoped>
.evidence-interpretation-app { min-height: 100vh; color: #172a20; background: radial-gradient(circle at 8% 0%, color-mix(in srgb, var(--theme-color) 9%, transparent), transparent 34rem), #f7faf8; }
.evidence-interpretation-page { width: min(1260px, calc(100% - 60px)); margin: 0 auto; padding: 38px 0 96px; }
.evidence-interpretation-breadcrumb { display: flex; align-items: center; gap: 10px; margin-bottom: 25px; color: #8a998f; font-size: 14px; }.evidence-interpretation-breadcrumb a { display: inline-flex; align-items: center; gap: 6px; color: var(--theme-color); font-weight: 650; text-decoration: none; }.evidence-interpretation-breadcrumb strong { color: #52665a; font-weight: 600; }
.evidence-interpretation-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 30px; padding: 28px 4px 30px; border-bottom: 1px solid #e3ece6; }.evidence-interpretation-kicker { color: var(--theme-color); font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .1em; }.evidence-interpretation-hero h1 { margin: 14px 0 10px; color: #14271e; font-size: clamp(42px, 5vw, 64px); letter-spacing: -.065em; line-height: 1.03; }.evidence-interpretation-goal { max-width: 980px; margin: 0; color: #71837a; font-size: 16px; line-height: 1.8; }.evidence-interpretation-status { display: inline-flex; align-items: center; gap: 8px; margin-top: 7px; padding: 10px 15px; border: 1px solid color-mix(in srgb, var(--theme-color) 28%, #dfe9e2); border-radius: 999px; color: var(--theme-color); background: var(--theme-soft); font-size: 13px; font-weight: 700; white-space: nowrap; }.evidence-interpretation-status i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.evidence-interpretation-conclusion { position: relative; margin: 28px 0 48px; padding: 27px 31px; overflow: hidden; border: 1px solid color-mix(in srgb, var(--theme-color) 18%, #dfe9e2); border-left: 6px solid var(--theme-color); border-radius: 19px; background: linear-gradient(135deg, color-mix(in srgb, var(--theme-color) 9%, #fff), #fff); box-shadow: 0 17px 36px color-mix(in srgb, var(--theme-color) 7%, transparent); }.evidence-interpretation-conclusion::after { content: ""; position: absolute; top: -82px; right: -62px; width: 210px; height: 210px; border-radius: 50%; background: color-mix(in srgb, var(--theme-color) 9%, transparent); }.evidence-interpretation-conclusion > * { position: relative; z-index: 1; }.evidence-interpretation-conclusion h2 { margin: 10px 0 9px; color: #183328; font-size: 29px; letter-spacing: -.04em; }.evidence-interpretation-conclusion p { max-width: 980px; margin: 0; color: #5e7467; font-size: 16px; line-height: 1.8; }
.evidence-interpretation-section { margin: 0 0 48px; }.evidence-interpretation-section > header { margin-bottom: 18px; }.evidence-interpretation-section h2 { margin: 7px 0 0; color: #1b3126; font-size: 31px; letter-spacing: -.055em; }.evidence-source-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }.evidence-source-grid article { position: relative; min-height: 118px; padding: 20px 17px 17px; border: 1px solid #e1ebe4; border-radius: 16px; background: rgba(255,255,255,.9); box-shadow: 0 9px 24px rgba(56,82,65,.045); transition: transform .18s ease, box-shadow .18s ease; }.evidence-source-grid article::before { content: ""; position: absolute; top: 0; right: 14px; left: 14px; height: 3px; border-radius: 0 0 4px 4px; background: var(--theme-color); opacity: .65; }.evidence-source-grid article:hover { transform: translateY(-3px); box-shadow: 0 15px 28px rgba(56,82,65,.09); }.evidence-source-grid strong,.evidence-source-grid span { display: block; }.evidence-source-grid strong { color: var(--theme-color); font: 700 31px ui-monospace, monospace; line-height: 1; }.evidence-source-grid span { margin-top: 12px; color: #687b70; font-size: 13px; line-height: 1.4; }
.evidence-finding-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }.evidence-finding-card { min-height: 190px; padding: 22px 23px; border: 1px solid #e0eae3; border-radius: 17px; background: rgba(255,255,255,.9); box-shadow: 0 10px 26px rgba(56,82,65,.04); transition: transform .18s ease, box-shadow .18s ease; }.evidence-finding-card:hover { transform: translateY(-3px); box-shadow: 0 16px 30px rgba(56,82,65,.085); }.evidence-finding-meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: #788b80; font-size: 12px; }.evidence-finding-meta span:last-child { padding: 5px 9px; border: 1px solid #e7dfc9; border-radius: 999px; color: #a66e1a; background: #fff9ed; }.evidence-finding-card h3 { margin: 15px 0 9px; color: #234033; font-size: 18px; letter-spacing: -.025em; }.evidence-finding-card p { margin: 0 0 15px; color: #667a6e; font-size: 14px; line-height: 1.75; }.evidence-finding-card a { color: var(--theme-color); font-size: 13px; font-weight: 700; text-decoration: none; }
.evidence-gaps-section { padding: 24px 26px 26px; border: 1px solid #eadfc9; border-left: 5px solid #b8771e; border-radius: 17px; background: #fffaf2; }.evidence-gap-list { display: grid; gap: 9px; }.evidence-gap-list article { padding: 14px 16px; border: 1px solid #efdfbd; border-radius: 12px; background: rgba(255,255,255,.72); }.evidence-gap-list article > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.evidence-gap-list strong { color: #6b5130; font-size: 14px; }.evidence-gap-list article span { padding: 4px 8px; border-radius: 999px; color: #a66e1a; background: #fff0d5; font-size: 11px; font-weight: 700; }.evidence-gap-list p { margin: 7px 0 0; color: #7b6c57; font-size: 13px; line-height: 1.65; }
.evidence-next-steps { padding: 24px 26px 26px; border: 1px solid #dfe9e2; border-radius: 17px; background: rgba(255,255,255,.88); }.evidence-next-steps ol { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; counter-reset: next-step; }.evidence-next-steps li { display: grid; grid-template-columns: 31px minmax(0, 1fr); gap: 11px; align-items: start; padding: 13px 14px; border: 1px solid #e3ece6; border-radius: 11px; color: #5f7467; background: #fbfdfb; font-size: 14px; line-height: 1.65; counter-increment: next-step; }.evidence-next-steps li::before { content: counter(next-step, decimal-leading-zero); display: grid; width: 28px; height: 28px; place-items: center; border-radius: 9px; color: var(--theme-color); background: var(--theme-soft); font: 700 11px ui-monospace, monospace; }
.evidence-interpretation-details { margin: 13px 0; border: 1px solid #dfe9e2; border-radius: 14px; background: rgba(255,255,255,.78); }.evidence-interpretation-details summary { padding: 16px 19px; color: #5d7265; font-size: 13px; font-weight: 700; list-style: none; cursor: pointer; }.evidence-interpretation-details summary::-webkit-details-marker { display: none; }.evidence-interpretation-details summary > span { float: right; width: 8px; height: 8px; margin-top: 3px; border-right: 1.5px solid #8ea095; border-bottom: 1.5px solid #8ea095; transform: rotate(45deg); transition: transform .18s ease; }.evidence-interpretation-details[open] summary > span { transform: rotate(225deg) translate(-1px,-1px); }.evidence-interpretation-details dl { display: grid; grid-template-columns: 120px minmax(0,1fr); gap: 8px 15px; margin: 0; padding: 17px 19px 19px; border-top: 1px solid #e8efea; }.evidence-interpretation-details dt { color: #8a998f; font-size: 12px; }.evidence-interpretation-details dd { margin: 0; color: #5f7467; font-size: 12px; overflow-wrap: anywhere; }.evidence-interpretation-details pre { margin: 0; max-height: 430px; overflow: auto; padding: 17px 19px 20px; border-top: 1px solid #e8efea; background: #f7faf8; font-size: 11px; line-height: 1.6; white-space: pre-wrap; }.evidence-interpretation-loading { display: grid; min-height: 64vh; place-items: center; align-content: center; gap: 12px; color: #7d9083; }.evidence-interpretation-empty { padding: 30px; border: 1px solid #dfe9e2; border-radius: 18px; background: #fff; }.evidence-interpretation-empty pre { overflow: auto; white-space: pre-wrap; }
@media (max-width: 900px) { .evidence-interpretation-page { width: min(100% - 44px, 720px); }.evidence-source-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 640px) { .evidence-interpretation-page { width: calc(100% - 32px); padding-top: 25px; }.evidence-interpretation-hero { display: block; padding-top: 18px; }.evidence-interpretation-hero h1 { font-size: 44px; }.evidence-interpretation-status { margin-top: 18px; }.evidence-interpretation-conclusion { padding: 22px 20px 23px; }.evidence-interpretation-conclusion h2 { font-size: 25px; }.evidence-source-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.evidence-finding-grid { grid-template-columns: 1fr; }.evidence-interpretation-section h2 { font-size: 27px; }.evidence-gaps-section,.evidence-next-steps { padding: 22px 19px; }.evidence-interpretation-details dl { grid-template-columns: 1fr; gap: 2px; } }
</style>
