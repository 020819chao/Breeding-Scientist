<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { IconCheck, IconFile, IconTranslate } from "@arco-design/web-vue/es/icon";

type ThemeName = "green" | "gold" | "purple";
type Language = "zh" | "en";

const themes: Record<ThemeName, { label: string; color: string; hover: string; pressed: string }> = {
  green: { label: "绿色", color: "#16865f", hover: "#2a9d76", pressed: "#0f6848" },
  gold: { label: "金色", color: "#b8771e", hover: "#ca8c35", pressed: "#8e5b12" },
  purple: { label: "紫色", color: "#7046b6", hover: "#855fc3", pressed: "#57358f" },
};

const language = ref<Language>((localStorage.getItem("co-scientist-language") as Language) || "zh");
const themeName = ref<ThemeName>((localStorage.getItem("co-scientist-theme") as ThemeName) || "green");
const data = ref<any>(null);
const loading = ref(true);
const error = ref("");
const reviewer = ref("");
const note = ref("");
const submitting = ref(false);
const approvalResult = ref<any>(null);
const rollbackResult = ref<any>(null);
const batchId = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).pop() || "");

const isEnglish = computed(() => language.value === "en");
const currentTheme = computed(() => themes[themeName.value]);
const themeStyles = computed(() => ({
  "--theme-color": currentTheme.value.color,
  "--theme-color-hover": currentTheme.value.hover,
  "--theme-color-pressed": currentTheme.value.pressed,
  "--theme-soft": `${currentTheme.value.color}14`,
}));
const record = computed(() => data.value?.record || {});
const stats = computed(() => record.value.stats || {});
const added = computed(() => stats.value.added || {});
const copy = computed(() => isEnglish.value ? {
  knowledge: "Knowledge base", sessions: "Research sessions", newSession: "New session", theme: "Theme", language: "中文",
  back: "Knowledge intake", kicker: "BATCH RESULT", title: "Knowledge batch detail", result: "Processing result", id: "Batch ID",
  pending: "Waiting for expert review", active: "Approved and active", archived: "Historical version", scope: "Crop scope", time: "Processed",
  reviewer: "Reviewer", reviewNote: "Review note", addedTitle: "New knowledge added", addedLead: "The system automatically validated and merged this batch into the knowledge workflow.",
  germplasm: "Germplasm resources", marker: "Marker / QTL", phenotype: "Phenotype protocols", trial: "Field trials", evidence: "Evidence documents",
  merged: "This batch was merged with the existing knowledge base. Categories not included in this upload remain unchanged.",
  reviewTitle: "Expert review", reviewLead: "Preflight passed. Add the reviewer and a short note before activating this batch.", reviewerPlaceholder: "Expert or reviewer name", notePlaceholder: "Record scope, risks and approval rationale", approve: "Approve and activate", approving: "Activating…",
  activeTitle: "Knowledge base updated", activeLead: "This batch has passed review and is now available to new breeding sessions.", rollback: "Restore as active knowledge base", rollbackConfirm: "I understand this historical version will become active. The current version will remain in history.", rollbackAction: "Restore as active", rolling: "Restoring…",
  rollbackSuccess: "Knowledge base restored", approveSuccess: "Batch approved and activated", failed: "Operation failed", backList: "Back to batch history", loading: "Loading batch detail…", retry: "Retry",
} : {
  knowledge: "知识库", sessions: "研究会话", newSession: "新建育种会话", theme: "色调", language: "English",
  back: "知识库接入", kicker: "BATCH RESULT", title: "知识批次详情", result: "资料处理结果", id: "批次 ID",
  pending: "待专家审核", active: "已审核并生效", archived: "历史资料", scope: "作物范围", time: "处理时间",
  reviewer: "审核人", reviewNote: "审核意见", addedTitle: "本次新增资料", addedLead: "系统已自动完成检查、整理和合并，资料现在进入知识库流程。",
  germplasm: "种质资源", marker: "标记 / QTL", phenotype: "表型协议", trial: "田间试验", evidence: "证据资料",
  merged: "本次资料已与原有知识合并；未上传的资料类别保持不变。",
  reviewTitle: "专家审核", reviewLead: "自动预检已经通过，填写审核人和意见后即可激活这批资料。", reviewerPlaceholder: "专家或审核人姓名", notePlaceholder: "可记录数据范围、风险和批准理由", approve: "审核通过并激活", approving: "正在激活…",
  activeTitle: "知识库已更新", activeLead: "这批资料已通过审核，新的育种会话现在可以使用它们。", rollback: "恢复为当前知识库", rollbackConfirm: "我了解这个历史版本会成为当前知识库，当前版本仍会保留在历史记录中。", rollbackAction: "恢复为当前版本", rolling: "正在恢复…",
  rollbackSuccess: "知识库已恢复", approveSuccess: "批次已审核并激活", failed: "操作未完成", backList: "返回知识批次历史", loading: "正在加载批次详情…", retry: "重试",
});

const statItems = computed(() => [
  { key: "germplasm_resources", label: copy.value.germplasm, value: added.value.germplasm_resources || 0, tone: "green" },
  { key: "marker_qtl", label: copy.value.marker, value: added.value.marker_qtl || 0, tone: "gold" },
  { key: "phenotype_protocol", label: copy.value.phenotype, value: added.value.phenotype_protocol || 0, tone: "purple" },
  { key: "field_trial", label: copy.value.trial, value: added.value.field_trial || 0, tone: "blue" },
  { key: "rag_documents_added", label: copy.value.evidence, value: stats.value.rag_documents_added || 0, tone: "red" },
]);

function toggleLanguage() {
  language.value = language.value === "zh" ? "en" : "zh";
  localStorage.setItem("co-scientist-language", language.value);
}

function selectTheme(value: string | number | Record<string, any> | undefined) {
  if (typeof value !== "string" || !(value in themes)) return;
  themeName.value = value as ThemeName;
  localStorage.setItem("co-scientist-theme", themeName.value);
}

function formatScope(value: unknown) {
  return Array.isArray(value) ? value.join(isEnglish.value ? " · " : "、") : String(value || "—");
}

function formatDate(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(isEnglish.value ? "en-GB" : "zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function statusLabel() {
  return record.value.is_pending ? copy.value.pending : record.value.is_active ? copy.value.active : copy.value.archived;
}

function statusColor() {
  return record.value.is_pending ? "orange" : record.value.is_active ? "green" : "gray";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/knowledge/batches/${encodeURIComponent(batchId)}/detail`);
    if (!response.ok) throw new Error(isEnglish.value ? "Batch not found" : "找不到这条知识批次");
    data.value = await response.json();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

async function submitAction(kind: "approve" | "rollback") {
  submitting.value = true;
  approvalResult.value = null;
  rollbackResult.value = null;
  try {
    const values: Record<string, string> = kind === "approve" ? { reviewer: reviewer.value, note: note.value } : { confirm: "true" };
    const response = await fetch(`/knowledge/batches/${encodeURIComponent(batchId)}/${kind}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: new URLSearchParams(values),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || copy.value.failed);
    data.value = payload;
    approvalResult.value = payload.approval_result || null;
    rollbackResult.value = payload.rollback_result || null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    submitting.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="batch-detail-app" :style="themeStyles">
    <header class="batch-detail-topbar">
      <div class="batch-detail-topbar-inner">
        <a href="/" class="batch-detail-brand"><span>BS</span><div><strong>Breeding Scientist</strong><small>育种科学家</small></div></a>
        <nav><a href="/knowledge" class="active">{{ copy.knowledge }}</a><a href="/sessions">{{ copy.sessions }}</a></nav>
        <div class="batch-detail-actions">
          <a-button class="header-pill" @click="toggleLanguage"><IconTranslate />{{ copy.language }}</a-button>
          <a-dropdown trigger="click"><a-button class="header-pill"><i class="theme-dot" />{{ copy.theme }} <span class="chevron">⌄</span></a-button><template #content><a-doption v-for="(item, key) in themes" :key="key" @click="selectTheme(key)"><span class="theme-choice"><i :style="{ background: item.color }" />{{ item.label }}<b v-if="key === themeName">✓</b></span></a-doption></template></a-dropdown>
          <a-button type="primary" href="/sessions/new">{{ copy.newSession }}</a-button>
        </div>
      </div>
    </header>

    <main v-if="!loading && !error" class="batch-detail-page">
      <div class="batch-detail-breadcrumb"><a href="/knowledge">{{ copy.back }}</a><span>/</span><strong>{{ copy.result }}</strong></div>
      <section class="batch-detail-hero">
        <div class="batch-detail-kicker">{{ copy.kicker }}</div>
        <div class="batch-detail-title-row"><div><h1>{{ copy.title }}</h1><p>{{ copy.id }} <code>{{ batchId }}</code></p></div><a-tag class="status-tag" :color="statusColor()">{{ statusLabel() }}</a-tag></div>
      </section>

      <a-alert v-if="approvalResult?.ok" type="success" class="batch-feedback"><template #icon><IconCheck /></template>{{ copy.approveSuccess }}</a-alert>
      <a-alert v-if="rollbackResult?.ok" type="success" class="batch-feedback"><template #icon><IconCheck /></template>{{ copy.rollbackSuccess }}</a-alert>
      <a-alert v-if="approvalResult && !approvalResult.ok || rollbackResult && !rollbackResult.ok || error" type="error" class="batch-feedback">{{ error || approvalResult?.error || rollbackResult?.error || copy.failed }}</a-alert>

      <section class="batch-summary-card">
        <div class="batch-summary-heading"><div><span>{{ copy.result }}</span><h2>{{ statusLabel() }}</h2></div><span class="summary-check"><IconCheck /></span></div>
        <div class="batch-meta-grid"><div><small>{{ copy.scope }}</small><strong>{{ formatScope(record.crop_scope) }}</strong></div><div><small>{{ copy.time }}</small><strong>{{ formatDate(record.imported_at) }}</strong></div><div v-if="record.reviewer"><small>{{ copy.reviewer }}</small><strong>{{ record.reviewer }}</strong></div><div v-if="record.review_note"><small>{{ copy.reviewNote }}</small><strong>{{ record.review_note }}</strong></div></div>
      </section>

      <section class="batch-section">
        <div class="batch-section-heading"><div><span class="batch-kicker">AUTOMATED KNOWLEDGE UPDATE</span><h2>{{ copy.addedTitle }}</h2><p>{{ copy.addedLead }}</p></div><span class="auto-mark">AUTO</span></div>
        <div class="batch-stat-grid"><article v-for="item in statItems" :key="item.key" class="batch-stat-card" :class="item.tone"><span class="stat-icon"><IconFile /></span><small>{{ item.label }}</small><strong>{{ item.value }}</strong><em>{{ isEnglish ? "records" : "条" }}</em></article></div>
        <p class="batch-merge-note"><IconCheck />{{ copy.merged }}</p>
      </section>

      <section v-if="record.is_pending" class="batch-action-card review-action">
        <div class="action-copy"><span class="batch-kicker">EXPERT REVIEW</span><h2>{{ copy.reviewTitle }}</h2><p>{{ copy.reviewLead }}</p></div>
        <form @submit.prevent="submitAction('approve')"><a-form-item :label="copy.reviewer"><a-input v-model="reviewer" required :placeholder="copy.reviewerPlaceholder" /></a-form-item><a-form-item :label="copy.reviewNote"><a-textarea v-model="note" :placeholder="copy.notePlaceholder" :auto-size="{ minRows: 3, maxRows: 5 }" /></a-form-item><a-button html-type="submit" type="primary" :loading="submitting" :disabled="!reviewer.trim()">{{ submitting ? copy.approving : copy.approve }}</a-button></form>
      </section>
      <section v-else class="batch-action-card active-action"><div class="active-action-icon"><IconCheck /></div><div><span class="batch-kicker">KNOWLEDGE BASE STATUS</span><h2>{{ copy.activeTitle }}</h2><p>{{ copy.activeLead }}</p></div><form v-if="record.archive_path" @submit.prevent="submitAction('rollback')"><label><input type="checkbox" required />{{ copy.rollbackConfirm }}</label><a-button html-type="submit" status="danger" :loading="submitting">{{ submitting ? copy.rolling : copy.rollback }}</a-button></form></section>

      <a href="/knowledge" class="batch-back-link">← {{ copy.backList }}</a>
    </main>
    <div v-else class="batch-detail-loading"><a-spin :size="32" /><p>{{ error || copy.loading }}</p><a-button v-if="error" @click="load">{{ copy.retry }}</a-button></div>
  </div>
</template>

<style scoped>
.batch-detail-app { min-height: 100vh; color: #18261f; background: radial-gradient(circle at 5% -4%, color-mix(in srgb, var(--theme-color) 10%, transparent), transparent 34rem), #f7faf8; }.batch-detail-topbar { height: 72px; border-bottom: 1px solid #e0e9e2; background: rgba(255,255,255,.92); box-shadow: 0 10px 30px rgba(71,102,83,.05); backdrop-filter: blur(18px); }.batch-detail-topbar-inner { max-width: 1440px; height: 100%; margin: auto; padding: 0 28px; display: flex; align-items: center; gap: 38px; }.batch-detail-brand { display: flex; align-items: center; gap: 10px; color: #17241f; }.batch-detail-brand > span { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 12px; color: #fff; background: var(--theme-color); box-shadow: 0 8px 20px color-mix(in srgb, var(--theme-color) 25%, transparent); font: 700 12px ui-monospace, monospace; }.batch-detail-brand strong,.batch-detail-brand small { display: block; }.batch-detail-brand strong { font-size: 15px; }.batch-detail-brand small { margin-top: 2px; color: #84928a; font-size: 10px; }.batch-detail-topbar nav { display: flex; gap: 25px; margin-right: auto; }.batch-detail-topbar nav a { position: relative; padding: 25px 0; color: #66746b; font-size: 13px; }.batch-detail-topbar nav a.active { color: #17241f; }.batch-detail-topbar nav a.active::after { content: ""; position: absolute; right: 0; bottom: 0; left: 0; height: 3px; border-radius: 99px; background: var(--theme-color); }.batch-detail-actions { display: flex; align-items: center; gap: 9px; }.header-pill { height: 38px; border: 1px solid color-mix(in srgb, var(--theme-color) 15%, #dfe9e2); border-radius: 999px; color: var(--theme-color); background: color-mix(in srgb, var(--theme-color) 5%, #fff); }.batch-detail-actions :deep(.arco-btn-primary) { height: 40px; padding: 0 18px; border-radius: 999px; border-color: var(--theme-color); background: var(--theme-color); box-shadow: 0 10px 24px color-mix(in srgb, var(--theme-color) 22%, transparent); }.theme-dot,.theme-choice i { display: inline-block; width: 8px; height: 8px; margin-right: 7px; border-radius: 50%; background: var(--theme-color); }.chevron { margin-left: 5px; color: #95a199; }.theme-choice { display: flex; min-width: 108px; align-items: center; }.theme-choice i { width: 9px; height: 9px; }.theme-choice b { margin-left: auto; color: var(--theme-color); }.batch-detail-page { max-width: 1220px; margin: auto; padding: 36px 28px 90px; }.batch-detail-breadcrumb { display: flex; gap: 9px; align-items: center; margin-bottom: 30px; color: #8a978f; font-size: 13px; }.batch-detail-breadcrumb a { color: var(--theme-color); }.batch-detail-breadcrumb strong { color: #516159; font-weight: 500; }.batch-detail-hero { margin-bottom: 24px; }.batch-detail-kicker,.batch-kicker { color: var(--theme-color); font: 700 11px ui-monospace, monospace; letter-spacing: .14em; }.batch-detail-title-row { display: flex; align-items: flex-end; justify-content: space-between; gap: 25px; }.batch-detail-title-row h1 { margin: 12px 0 9px; color: #14231c; font-size: clamp(39px, 5vw, 62px); line-height: 1.06; letter-spacing: -.065em; }.batch-detail-title-row p { margin: 0; color: #809087; font-size: 13px; }.batch-detail-title-row code { margin-left: 8px; padding: 5px 9px; border: 1px solid #dce8df; border-radius: 8px; color: #5c7063; background: #f5faf6; font: 12px ui-monospace, monospace; }.status-tag { padding: 7px 12px; border-radius: 999px; font-size: 12px; }.batch-feedback { margin: 0 0 18px; border-radius: 13px; }.batch-summary-card,.batch-action-card { border: 1px solid #dfe9e2; border-radius: 20px; background: rgba(255,255,255,.88); box-shadow: 0 16px 40px rgba(64,96,75,.055); }.batch-summary-card { padding: 25px 28px 26px; }.batch-summary-heading { display: flex; align-items: center; justify-content: space-between; padding-bottom: 18px; border-bottom: 1px solid #e7efe9; }.batch-summary-heading span:first-child { color: #7a8980; font-size: 12px; }.batch-summary-heading h2 { margin: 7px 0 0; color: #21352a; font-size: 22px; }.summary-check { display: grid; width: 35px; height: 35px; place-items: center; border-radius: 50%; color: var(--theme-color); background: var(--theme-soft); font-size: 18px; }.batch-meta-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 20px; padding-top: 20px; }.batch-meta-grid div { min-width: 0; }.batch-meta-grid small,.batch-meta-grid strong { display: block; }.batch-meta-grid small { color: #8a988f; font-size: 11px; }.batch-meta-grid strong { margin-top: 7px; overflow: hidden; color: #3a5143; font-size: 14px; line-height: 1.5; text-overflow: ellipsis; }.batch-section { margin-top: 58px; }.batch-section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 22px; }.batch-section-heading h2 { margin: 8px 0 6px; color: #172a20; font-size: 32px; letter-spacing: -.05em; }.batch-section-heading p { margin: 0; color: #829087; font-size: 13px; }.auto-mark { padding: 7px 10px; border: 1px solid color-mix(in srgb, var(--theme-color) 24%, #dfe9e2); border-radius: 999px; color: var(--theme-color); background: var(--theme-soft); font: 700 10px ui-monospace, monospace; letter-spacing: .08em; }.batch-stat-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 13px; }.batch-stat-card { position: relative; min-height: 142px; padding: 20px; overflow: hidden; border: 1px solid #e0e9e2; border-radius: 17px; background: rgba(255,255,255,.9); box-shadow: 0 12px 30px rgba(64,96,75,.045); transition: transform .22s ease, box-shadow .22s ease; }.batch-stat-card:hover { transform: translateY(-3px); box-shadow: 0 18px 36px rgba(64,96,75,.09); }.batch-stat-card::after { content: ""; position: absolute; right: -28px; bottom: -32px; width: 85px; height: 85px; border-radius: 50%; background: currentColor; opacity: .045; }.batch-stat-card .stat-icon { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 9px; color: currentColor; background: color-mix(in srgb, currentColor 12%, #fff); }.batch-stat-card small { display: block; margin-top: 14px; color: #76877c; font-size: 12px; }.batch-stat-card strong { display: inline-block; margin-top: 4px; color: #20362a; font: 600 30px ui-monospace, monospace; }.batch-stat-card em { margin-left: 5px; color: #8c9991; font-size: 11px; font-style: normal; }.batch-stat-card.green { color: #16865f; }.batch-stat-card.gold { color: #b8771e; }.batch-stat-card.purple { color: #7046b6; }.batch-stat-card.blue { color: #3979a6; }.batch-stat-card.red { color: #c45c50; }.batch-merge-note { display: flex; align-items: center; gap: 8px; margin: 17px 0 0; padding: 13px 15px; border-left: 3px solid var(--theme-color); border-radius: 10px; color: #557061; background: color-mix(in srgb, var(--theme-color) 5%, #fff); font-size: 13px; }.batch-merge-note .arco-icon { color: var(--theme-color); }.batch-action-card { display: grid; grid-template-columns: .9fr 1.1fr; gap: 38px; margin-top: 30px; padding: 28px; }.action-copy h2,.active-action h2 { margin: 9px 0 8px; color: #21372a; font-size: 25px; letter-spacing: -.04em; }.action-copy p,.active-action p { margin: 0; color: #718178; font-size: 13px; line-height: 1.8; }.review-action form { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 0 14px; }.review-action form :deep(.arco-form-item:nth-child(2)) { grid-column: 1 / -1; }.review-action form :deep(.arco-btn) { width: max-content; min-width: 150px; height: 40px; border-radius: 999px; background: var(--theme-color); border-color: var(--theme-color); }.active-action { grid-template-columns: auto 1fr; align-items: center; }.active-action-icon { display: grid; width: 48px; height: 48px; place-items: center; border-radius: 15px; color: var(--theme-color); background: var(--theme-soft); font-size: 24px; }.active-action form { grid-column: 1 / -1; display: flex; align-items: center; gap: 15px; padding-top: 18px; border-top: 1px solid #e7efe9; }.active-action form label { color: #78887e; font-size: 12px; }.active-action form button { margin-left: auto; border-radius: 999px; }.batch-back-link { display: inline-flex; margin-top: 28px; color: var(--theme-color); font-size: 13px; font-weight: 600; }.batch-detail-loading { min-height: 70vh; display: grid; place-content: center; justify-items: center; gap: 12px; color: #829087; }.batch-detail-loading p { margin: 0; }.batch-detail-loading .arco-btn { border-radius: 999px; }
@media (max-width: 980px) { .batch-stat-grid { grid-template-columns: repeat(3, 1fr); }.batch-action-card { grid-template-columns: 1fr; gap: 22px; }.active-action { grid-template-columns: auto 1fr; }.review-action form { max-width: 700px; } }
@media (max-width: 680px) { .batch-detail-topbar-inner { padding: 0 16px; gap: 12px; }.batch-detail-topbar nav { display: none; }.batch-detail-actions { margin-left: auto; gap: 5px; }.batch-detail-actions :deep(.arco-btn) { padding: 0 9px !important; font-size: 12px; }.batch-detail-actions :deep(.arco-btn-primary) { display: none; }.batch-detail-page { padding: 25px 16px 65px; }.batch-detail-breadcrumb { margin-bottom: 22px; }.batch-detail-title-row { align-items: flex-start; flex-direction: column; gap: 15px; }.batch-detail-title-row h1 { font-size: 43px; }.batch-summary-card,.batch-action-card { padding: 21px 18px; border-radius: 17px; }.batch-meta-grid { grid-template-columns: repeat(2, minmax(0,1fr)); gap: 18px 12px; }.batch-section-heading h2 { font-size: 28px; }.batch-stat-grid { grid-template-columns: repeat(2, 1fr); }.batch-stat-card { min-height: 125px; padding: 16px; }.batch-stat-card strong { font-size: 26px; }.batch-action-card { display: block; }.review-action form { display: block; margin-top: 20px; }.review-action form :deep(.arco-form-item) { margin-bottom: 16px; }.active-action-icon { margin-bottom: 16px; }.active-action form { display: block; }.active-action form button { margin-top: 15px; }.batch-merge-note { align-items: flex-start; line-height: 1.6; } }
</style>
