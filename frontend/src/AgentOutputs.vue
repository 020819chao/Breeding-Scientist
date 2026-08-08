<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import SiteHeader from "./SiteHeader.vue";

const sessionId = window.location.pathname.split("/")[2] || "";
const loading = ref(true);
const error = ref("");
const payload = ref<any>(null);
const selectedAgent = ref(new URLSearchParams(window.location.search).get("agent") || "");
const reviewingKey = ref("");
const reviewFeedback = ref("");
const reviewForm = ref({ reviewer: "", status: "approved", note: "" });
const language = ref<"zh" | "en">((localStorage.getItem("co-scientist-language") as "zh" | "en") || "zh");

const agents = computed<any[]>(() => payload.value?.outputs || []);
const selected = computed(() => agents.value.find((agent) => agent.name === selectedAgent.value) || null);
const selectedOutputs = computed<any[]>(() => selected.value?.outputs || []);

function toggleLanguage() {
  language.value = language.value === "zh" ? "en" : "zh";
  localStorage.setItem("co-scientist-language", language.value);
}

function selectAgent(name: string) {
  selectedAgent.value = name;
  const url = new URL(window.location.href);
  url.searchParams.set("agent", name);
  window.history.pushState({}, "", url);
  reviewFeedback.value = "";
}

function syncFromUrl() {
  selectedAgent.value = new URLSearchParams(window.location.search).get("agent") || "";
}

function reviewStatus(output: any) {
  return output.review?.status_label || "待审核";
}

function reviewStatusClass(output: any) {
  return `is-${output.review?.status || "pending"}`;
}

function openReview(output: any) {
  reviewingKey.value = output.output_key;
  reviewForm.value = { reviewer: "", status: "approved", note: "" };
  reviewFeedback.value = "";
}

async function submitReview(output: any) {
  if (!reviewForm.value.reviewer.trim()) return;
  const body = new URLSearchParams({
    agent: output.agent,
    output_key: output.output_key,
    output_path: output.path || "",
    target_id: output.target_id || "",
    status: reviewForm.value.status,
    reviewer: reviewForm.value.reviewer.trim(),
    note: reviewForm.value.note.trim(),
  });
  try {
    const response = await fetch(`/sessions/${sessionId}/agent-outputs/review`, { method: "POST", body });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    reviewingKey.value = "";
    reviewFeedback.value = "审核已保存";
    await loadOutputs();
  } catch (cause) {
    reviewFeedback.value = cause instanceof Error ? cause.message : "审核保存失败";
  }
}

async function loadOutputs() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/sessions/${sessionId}/agent-outputs`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    payload.value = await response.json();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "成果加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  window.addEventListener("popstate", syncFromUrl);
  loadOutputs();
});
onBeforeUnmount(() => window.removeEventListener("popstate", syncFromUrl));
</script>

<template>
  <div class="agent-outputs-app">
    <a-layout>
      <SiteHeader active="sessions" :language="language" @toggle-language="toggleLanguage" />
      <a-layout-content>
        <main class="agent-outputs-page">
          <a :href="`/sessions/${sessionId}`" class="agent-outputs-back">返回育种会话</a>
          <header class="agent-outputs-hero">
            <span>BREEDING SCIENTIST / REVIEW WORKSPACE</span>
            <h1>六智能体成果审阅</h1>
            <p>选择一个智能体，查看它本次形成的结构化成果、证据链和后续建议。</p>
          </header>

          <div v-if="loading" class="agent-outputs-loading"><a-spin :size="30" /><span>正在加载智能体成果…</span></div>
          <a-result v-else-if="error" status="error" title="成果加载失败" :sub-title="error"><template #extra><a-button type="primary" @click="loadOutputs">重试</a-button></template></a-result>
          <template v-else>
            <section class="agent-picker" aria-labelledby="agent-picker-title">
              <div class="agent-picker-heading"><div><h2 id="agent-picker-title">选择智能体</h2><p>点击后只查看当前智能体的成果。</p></div><span>{{ agents.length }} 个智能体</span></div>
              <div class="agent-picker-grid">
                <button v-for="(agent, index) in agents" :key="agent.name" type="button" class="agent-picker-card" :class="{ active: selectedAgent === agent.name }" :aria-pressed="selectedAgent === agent.name" @click="selectAgent(agent.name)">
                  <small>0{{ index + 1 }}</small><strong>{{ agent.label }}</strong><em>{{ agent.output_count }} 项成果</em>
                </button>
              </div>
            </section>

            <section v-if="!selected" class="agent-outputs-empty"><strong>请选择一个智能体</strong><span>页面只展示当前选择的成果，避免一次看到过多信息。</span></section>
            <section v-else class="agent-result-panel">
              <header class="agent-result-heading"><div><span>智能体 0{{ agents.findIndex((agent) => agent.name === selected.name) + 1 }}</span><h2>{{ selected.label }}</h2><p>{{ selected.purpose }}</p></div><strong>{{ selected.output_count }}<small>项成果</small></strong></header>
              <p class="agent-result-summary">{{ selected.summary }}</p>
              <div v-if="selectedOutputs.length" class="agent-output-grid">
                <article v-for="output in selectedOutputs" :key="output.output_key" class="agent-output-card">
                  <header><div><span>结构化成果</span><h3>{{ output.title }}</h3></div><b :class="reviewStatusClass(output)">{{ reviewStatus(output) }}</b></header>
                  <p>{{ output.summary }}</p>
                  <details v-if="output.details?.length" class="agent-output-details"><summary>查看高级信息</summary><dl><template v-for="detail in output.details" :key="detail.label"><dt>{{ detail.label }}</dt><dd>{{ detail.value }}</dd></template></dl></details>
                  <div class="agent-output-links"><a v-if="output.url" :href="output.url">{{ output.link_label || "查看结果" }}</a><button type="button" @click="openReview(output)">专家审核</button></div>
                  <p v-if="output.review?.reviewer" class="agent-review-meta">审核人：{{ output.review.reviewer }}</p>
                  <p v-if="output.review?.note" class="agent-review-note">审核意见：{{ output.review.note }}</p>
                  <form v-if="reviewingKey === output.output_key" class="agent-review-form" @submit.prevent="submitReview(output)">
                    <div><label>审核人<input v-model="reviewForm.reviewer" required placeholder="姓名或工号" /></label><label>结论<select v-model="reviewForm.status"><option value="approved">通过</option><option value="needs_revision">需修改</option><option value="rejected">不通过</option></select></label></div>
                    <label>审核意见<textarea v-model="reviewForm.note" rows="3" placeholder="填写依据、修改要求或补充验证要求"></textarea></label>
                    <button type="submit">保存审核</button>
                  </form>
                </article>
              </div>
              <p v-else class="agent-outputs-empty">该智能体暂时没有可展示的结构化成果。</p>
            </section>
          </template>
        </main>
      </a-layout-content>
    </a-layout>
  </div>
</template>

<style scoped>
.agent-outputs-app { min-height: 100vh; color: #17241f; background: radial-gradient(circle at 8% 0%, color-mix(in srgb, var(--theme-color) 8%, transparent), transparent 34rem), #f7faf8; }
.agent-outputs-topbar { height: 72px; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; border-bottom: 1px solid #e1ebe4; background: rgba(255,255,255,.9); backdrop-filter: blur(18px); }
.agent-outputs-brand { display: inline-flex; align-items: center; gap: 10px; color: #17241f; text-decoration: none; }.agent-outputs-brand strong,.agent-outputs-brand small { display: block; }.agent-outputs-brand strong { font-size: 15px; }.agent-outputs-brand small { margin-top: 2px; color: #87968e; font-size: 10px; }.agent-outputs-mark { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 11px; color: #fff; background: var(--theme-color); font: 700 12px ui-monospace, monospace; }
.agent-outputs-topbar nav { display: flex; align-items: center; gap: 25px; }.agent-outputs-topbar nav a { color: #65736b; font-size: 13px; text-decoration: none; }.agent-outputs-topbar nav a:hover { color: var(--theme-color); }.agent-outputs-topbar .agent-outputs-new { padding: 10px 16px; border-radius: 999px; color: #fff; background: var(--theme-color); font-weight: 650; }
.agent-outputs-page { width: min(1400px, calc(100% - 48px)); margin: 0 auto; padding: 38px 0 90px; }.agent-outputs-back { color: var(--theme-color); font-size: 13px; text-decoration: none; }.agent-outputs-hero { margin-top: 22px; padding: 30px 36px; border: 1px solid #deebe2; border-radius: 22px; background: linear-gradient(135deg, #fff, color-mix(in srgb, var(--theme-color) 5%, #fff)); box-shadow: 0 18px 42px rgba(54,82,64,.05); }.agent-outputs-hero > span,.agent-result-heading > div > span { color: #b8771e; font: 700 11px ui-monospace, monospace; letter-spacing: .12em; }.agent-outputs-hero h1 { margin: 12px 0 8px; color: #172b21; font-size: clamp(36px, 5vw, 58px); letter-spacing: -.06em; line-height: 1.05; }.agent-outputs-hero p { margin: 0; color: #718078; font-size: 15px; line-height: 1.7; }
.agent-picker { margin-top: 28px; padding: 24px 26px 26px; border: 1px solid #e0eae3; border-radius: 19px; background: #fff; box-shadow: 0 13px 32px rgba(49,78,60,.045); }.agent-picker-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 16px; }.agent-picker-heading h2 { margin: 0; color: #294536; font-size: 24px; }.agent-picker-heading p { margin: 5px 0 0; color: #77877d; font-size: 13px; }.agent-picker-heading > span { padding: 6px 10px; border: 1px solid #dfe9e2; border-radius: 999px; color: #718078; background: #f8fbf9; font-size: 12px; }.agent-picker-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }.agent-picker-card { display: flex; min-height: 78px; flex-direction: column; align-items: flex-start; justify-content: space-between; gap: 6px; padding: 12px 13px; border: 1px solid #dfe9e2; border-radius: 13px; color: #294536; background: #fff; cursor: pointer; text-align: left; transition: .16s ease; }.agent-picker-card:hover,.agent-picker-card.active { border-color: color-mix(in srgb, var(--theme-color) 48%, #dfe9e2); background: var(--theme-soft); box-shadow: 0 8px 20px rgba(49,78,60,.08); transform: translateY(-1px); }.agent-picker-card small { color: #b8771e; font: 700 11px ui-monospace, monospace; }.agent-picker-card strong { width: 100%; overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }.agent-picker-card em { color: var(--theme-color); font-size: 11px; font-style: normal; }
.agent-outputs-empty { display: flex; gap: 9px; margin-top: 18px; padding: 13px 15px; border-left: 3px solid #b8771e; color: #728077; background: #fffaf0; font-size: 13px; }.agent-outputs-empty strong { color: #8a5b19; }.agent-result-panel { margin-top: 18px; padding: 26px 28px; border: 1px solid #e0eae3; border-left: 4px solid var(--theme-color); border-radius: 19px; background: #fff; box-shadow: 0 14px 34px rgba(49,78,60,.05); }.agent-result-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }.agent-result-heading h2 { margin: 8px 0 4px; color: #294536; font-size: 27px; }.agent-result-heading p { margin: 0; color: #77877d; font-size: 13px; line-height: 1.6; }.agent-result-heading > strong { padding: 9px 13px; border: 1px solid #dfe9e2; border-radius: 12px; color: var(--theme-color); background: #f8fbf9; font: 700 22px ui-monospace, monospace; text-align: center; }.agent-result-heading > strong small { display: block; margin-top: 3px; color: #849189; font: 400 11px sans-serif; }.agent-result-summary { margin: 17px 0 0; padding-top: 15px; border-top: 1px solid #edf2ee; color: #687970; font-size: 13px; line-height: 1.7; }
.agent-output-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 18px; }.agent-output-card { position: relative; padding: 18px 19px; border: 1px solid #e0eae3; border-radius: 16px; background: linear-gradient(145deg, #fff, #fbfdfb); box-shadow: 0 10px 24px rgba(49,78,60,.055); }.agent-output-card::before { position: absolute; top: 0; left: 18px; right: 18px; height: 3px; border-radius: 0 0 5px 5px; background: color-mix(in srgb, var(--theme-color) 62%, #dfe9e2); content: ""; }.agent-output-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding-bottom: 12px; border-bottom: 1px solid #edf2ee; }.agent-output-card > header span { color: var(--theme-color); font-size: 10px; font-weight: 700; letter-spacing: .06em; }.agent-output-card h3 { margin: 5px 0 0; color: #294536; font-size: 17px; line-height: 1.45; }.agent-output-card > header b { flex: 0 0 auto; padding: 5px 9px; border: 1px solid #dfe9e2; border-radius: 999px; color: var(--theme-color); background: var(--theme-soft); font-size: 11px; white-space: nowrap; }.agent-output-card > p { margin: 14px 0 0; color: #66776d; font-size: 13px; line-height: 1.75; }.agent-output-card .is-approved { color: #278b55; border-color: #c8e5d1; background: #f3fbf5; }.agent-output-card .is-needs_revision { color: #af741f; border-color: #eed5ae; background: #fff9ef; }.agent-output-card .is-rejected { color: #b53636; border-color: #f0caca; background: #fff5f5; }.agent-output-details { margin-top: 14px; padding: 9px 11px; border: 1px solid #e5eee8; border-radius: 11px; background: #f8fbf9; }.agent-output-details summary { display: flex; align-items: center; justify-content: space-between; color: #607269; font-size: 12px; font-weight: 650; cursor: pointer; list-style: none; }.agent-output-details summary::-webkit-details-marker { display: none; }.agent-output-details summary::after { content: "+"; color: var(--theme-color); font-size: 17px; }.agent-output-details[open] summary { padding-bottom: 9px; border-bottom: 1px solid #e5eee8; }.agent-output-details[open] summary::after { content: "−"; }.agent-output-details dl { display: grid; grid-template-columns: minmax(92px, auto) minmax(0, 1fr); gap: 8px 13px; margin: 13px 2px 3px; font-size: 12px; line-height: 1.55; }.agent-output-details dt { color: #849289; font-weight: 600; }.agent-output-details dd { min-width: 0; margin: 0; color: #40564a; overflow-wrap: anywhere; }.agent-output-links { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; padding-top: 12px; border-top: 1px solid #edf2ee; }.agent-output-links a,.agent-output-links button { display: inline-flex; align-items: center; width: fit-content; padding: 6px 10px; border: 1px solid color-mix(in srgb, var(--theme-color) 27%, #dfe9e2); border-radius: 999px; color: var(--theme-color); background: color-mix(in srgb, var(--theme-color) 5%, #fff); font-size: 12px; font-weight: 650; text-decoration: none; cursor: pointer; }.agent-output-links button { font-family: inherit; }.agent-output-links a:hover,.agent-output-links button:hover { border-color: var(--theme-color); background: var(--theme-soft); }.agent-review-meta,.agent-review-note { margin: 10px 0 0; color: #829188; font-size: 11px; }.agent-review-note { padding-left: 9px; border-left: 2px solid #d9b36d; }.agent-review-form { display: grid; gap: 10px; margin-top: 14px; padding: 12px; border: 1px solid #e5eee8; border-radius: 11px; background: #fcfdfc; }.agent-review-form > div { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }.agent-review-form label { color: #63746a; font-size: 11px; font-weight: 600; }.agent-review-form input,.agent-review-form select,.agent-review-form textarea { width: 100%; min-height: 36px; margin-top: 5px; padding: 8px 10px; border: 1px solid #dfe9e3; border-radius: 9px; color: #40564a; background: #fff; font-size: 12px; }.agent-review-form textarea { resize: vertical; }.agent-review-form > button { width: fit-content; margin: 0; padding: 7px 14px; border: 0; border-radius: 999px; color: #fff; background: var(--theme-color); font-size: 12px; font-weight: 650; }
.agent-outputs-loading { display: grid; min-height: 35vh; place-items: center; align-content: center; gap: 12px; color: #7d9083; }
@media (max-width: 1050px) { .agent-picker-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.agent-output-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .agent-outputs-topbar { padding: 0 16px; }.agent-outputs-topbar nav a:not(.agent-outputs-new) { display: none; }.agent-outputs-page { width: min(100% - 28px, 720px); padding-top: 26px; }.agent-outputs-hero { padding: 26px 22px; }.agent-outputs-hero h1 { font-size: 38px; }.agent-picker,.agent-result-panel { padding: 20px 17px; }.agent-picker-heading { align-items: flex-start; flex-direction: column; }.agent-picker-grid,.agent-output-grid { grid-template-columns: 1fr; }.agent-result-heading { flex-direction: column; }.agent-result-heading > strong { align-self: flex-start; }.agent-review-form > div { grid-template-columns: 1fr; } }
</style>
