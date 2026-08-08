<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { IconTranslate } from "@arco-design/web-vue/es/icon";

type ThemeName = "green" | "gold" | "purple";
type Language = "zh" | "en";

interface SessionSummary {
  id: string;
  status: string;
  research_goal: string;
  created_at: string;
  updated_at: string;
  budget_usd: number;
  budget_used_usd: number;
  n_hyps: number;
}

const themes: Record<ThemeName, { label: string; color: string; hover: string; pressed: string }> = {
  green: { label: "绿色", color: "#16865f", hover: "#2a9d76", pressed: "#0f6848" },
  gold: { label: "金色", color: "#b8771e", hover: "#ca8c35", pressed: "#8e5b12" },
  purple: { label: "紫色", color: "#7046b6", hover: "#855fc3", pressed: "#57358f" },
};

const themeName = ref<ThemeName>((localStorage.getItem("co-scientist-theme") as ThemeName) || "green");
const language = ref<Language>((localStorage.getItem("co-scientist-language") as Language) || "zh");
const sessions = ref<SessionSummary[]>([]);
const loading = ref(true);
const loadError = ref("");
const deletingId = ref("");
const deleteError = ref("");
const deleteDialogVisible = ref(false);
const pendingDelete = ref<SessionSummary | null>(null);
const isWorkspace = window.location.pathname === "/sessions";

const currentTheme = computed(() => themes[themeName.value]);
const copy = computed(() => language.value === "en" ? {
  brandSubtitle: "Breeding Scientist",
  navScientist: "Breeding Scientist",
  navKnowledge: "Knowledge Base",
    navSessions: "Breeding Plans",
  themeColor: "Theme",
  switchLanguage: "Switch language",
  newSession: "New Breeding Session",
  heroEyebrow: "BREEDING SCIENTIST · GOAL TO PLAN",
  heroTitle: "Turn breeding goals into",
  heroTitleAccent: "executable breeding plans",
  heroDescription: "Start from a breeding goal, connect constraints, evidence, and multi-agent reasoning to produce a plan that can be reviewed, validated, and carried into field work.",
  startResearch: "Design a breeding plan",
  exploreKnowledge: "Browse supporting evidence",
  assistantEyebrow: "BREEDING SCIENTIST · READY TO WORK",
  assistantTitle: "What breeding goal are you working toward?",
  assistantPrompt: "Describe a crop, target trait, and constraint to start designing a plan.",
  assistantHint: "Goal-to-plan workspace",
  assistantTags: ["Crop knowledge", "Literature", "Germplasm"],
  assistantSteps: ["Interpret the goal", "Assemble evidence", "Build the plan"],
  coreEyebrow: "BREEDING WORKFLOW · TWO PILLARS",
  coreTitle: "From breeding goal to executable plan",
  coreDescription: "The knowledge base provides the evidence; the breeding scientist turns it into a plan you can act on.",
  knowledgeKicker: "KNOWLEDGE BASE · EVIDENCE FOUNDATION",
  knowledgeTitle: "Knowledge Base",
  knowledgeDescription: "Preserve crop knowledge graphs, literature, germplasm, markers, QTLs, phenotyping protocols, and field validation records so every piece of evidence is searchable and traceable.",
  knowledgeItems: ["Crop knowledge graph", "Local RAG evidence", "Germplasm & marker resources"],
  knowledgeAction: "Enter Knowledge Base",
  scientistKicker: "BREEDING SCIENTIST · SCIENTIFIC REASONING",
  scientistTitle: "Breeding Scientist",
  scientistDescription: "Give a breeding goal to a multi-agent team for evidence integration, hypothesis design, route evaluation, risk review, and plan validation.",
  scientistItems: ["Evidence-driven reasoning", "Candidate route design", "Traceable breeding reports"],
  scientistAction: "Launch Breeding Scientist",
  workspaceEyebrow: "ACTIVE WORKSPACE · PLAN WORKSPACE",
  workspaceTitle: "Recent breeding plans",
  workspaceDescription: "Every session turns a breeding goal into a traceable plan that can be reviewed, revised, and advanced toward field validation.",
  planTableTitle: "Plan registry",
  planTableDescription: "Traceable sessions ready for review and revision",
  planCountLabel: "plans",
  previousPage: "Previous page",
  nextPage: "Next page",
    researchSessions: "Breeding plans",
  running: "Running",
  hypotheses: "Candidate hypotheses",
  budgetSpent: "Total budget spent",
  actions: "Actions",
  delete: "Delete",
  deleteTitle: "Delete breeding session",
  deleteWarning: "This action cannot be undone. Session data, hypotheses, and outputs will be removed.",
  deleteAction: "Delete session",
  deleteTarget: "Session to remove",
  confirm: "Delete",
  cancel: "Cancel",
  deleteFailed: "Delete failed",
  reload: "Reload",
  unavailable: "Session data is temporarily unavailable",
  noSessions: "No breeding sessions yet",
  createFirst: "Create the first session",
  workflowEyebrow: "BREEDING WORKFLOW · BREEDING WORKFLOW",
  workflowTitle: "From breeding goal to a verifiable plan",
  workflowSteps: [
    { title: "Clarify the goal", description: "Turn the target trait, constraints, and priorities into a clear design brief." },
    { title: "Organize evidence", description: "Connect literature, germplasm, markers, and phenotyping protocols into traceable evidence." },
    { title: "Build the plan", description: "Compare candidate hypotheses, identify risks, and generate an executable crossing and validation plan." },
    { title: "Continuously revise", description: "Bring feedback and new observations back into the loop as the research route evolves." },
  ],
  empty: "—",
} : {
  brandSubtitle: "育种科学家",
  navScientist: "育种科学家",
  navKnowledge: "知识库",
    navSessions: "育种方案",
  themeColor: "主题色",
  switchLanguage: "切换语言",
  newSession: "新建育种会话",
  heroEyebrow: "BREEDING SCIENTIST · 从目标到方案",
  heroTitle: "把育种目标，变成",
  heroTitleAccent: "可执行的育种方案",
  heroDescription: "从育种目标出发，连接约束条件、知识库证据和多智能体推理，形成可复核、可验证、能够推进到田间的育种方案。",
  startResearch: "开始设计育种方案",
  exploreKnowledge: "查看支撑证据",
  assistantEyebrow: "BREEDING SCIENTIST · 随时开始",
  assistantTitle: "你要解决什么育种目标？",
  assistantPrompt: "描述作物、目标性状和约束条件，开始设计育种方案。",
  assistantHint: "从目标到方案的工作台",
  assistantTags: ["作物知识", "文献证据", "种质资源"],
  assistantSteps: ["解析目标", "组织证据", "生成方案"],
  coreEyebrow: "BREEDING WORKFLOW · 两个支点",
  coreTitle: "从育种目标到可执行方案",
  coreDescription: "知识库提供证据，育种科学家负责把证据组织成能够执行和验证的方案。",
  knowledgeKicker: "KNOWLEDGE BASE · 知识基础",
  knowledgeTitle: "知识库",
  knowledgeDescription: "沉淀作物知识图谱、文献、种质、标记、QTL、表型协议和田间验证记录，让每条依据都可检索、可追踪。",
  knowledgeItems: ["作物知识图谱", "本地 RAG 证据", "种质与标记资源"],
  knowledgeAction: "进入知识库",
  scientistKicker: "BREEDING SCIENTIST · 科学推理",
  scientistTitle: "育种科学家",
  scientistDescription: "把育种目标交给多智能体协作，完成证据整合、假设设计、方案评估、风险评审和验证规划。",
  scientistItems: ["证据驱动推理", "候选路线设计", "可追溯育种报告"],
  scientistAction: "启动育种科学家",
  workspaceEyebrow: "ACTIVE WORKSPACE · 方案工作台",
  workspaceTitle: "最近的育种方案",
  workspaceDescription: "每个会话都是一份可以复核、修订并推进到田间验证的育种方案。",
  planTableTitle: "育种方案列表",
  planTableDescription: "可复核、可修订的方案会话",
  planCountLabel: "条方案",
  previousPage: "上一页",
  nextPage: "下一页",
    researchSessions: "育种方案",
  running: "正在运行",
  hypotheses: "候选假设",
  budgetSpent: "累计预算消耗",
  actions: "操作",
  delete: "删除",
  deleteTitle: "删除育种会话",
  deleteWarning: "此操作无法撤销，会话数据、假设和相关成果将被删除。",
  deleteAction: "删除会话",
  deleteTarget: "即将删除的会话",
  confirm: "删除",
  cancel: "取消",
  deleteFailed: "删除失败",
  reload: "重新加载",
  unavailable: "会话数据暂时不可用",
  noSessions: "还没有育种会话",
  createFirst: "创建第一个会话",
  workflowEyebrow: "BREEDING WORKFLOW · 育种工作流",
  workflowTitle: "从育种目标出发，形成可验证的方案",
  workflowSteps: [
    { title: "解析目标", description: "把目标性状、约束与优先级转化为清晰的方案设计任务。" },
    { title: "组织证据", description: "连接文献、种质、标记和表型协议，建立可追溯依据。" },
    { title: "生成方案", description: "比较候选假设，识别风险，生成可执行的杂交与验证方案。" },
    { title: "持续修订", description: "将反馈和新观察带回闭环，让研究路线随证据共同成长。" },
  ],
  empty: "—",
} as const);
const themeStyles = computed(() => ({
  "--theme-color": currentTheme.value.color,
  "--theme-color-hover": currentTheme.value.hover,
  "--theme-color-pressed": currentTheme.value.pressed,
  "--color-primary-5": currentTheme.value.hover,
  "--color-primary-6": currentTheme.value.color,
  "--color-primary-7": currentTheme.value.pressed,
  "--color-primary-light-1": `${currentTheme.value.color}18`,
  "--color-primary-light-2": `${currentTheme.value.color}28`,
  "--color-primary-light-3": `${currentTheme.value.color}38`,
}));

const runningCount = computed(() => sessions.value.filter((session) => ["running", "in_progress"].includes(session.status)).length);
const hypothesisCount = computed(() => sessions.value.reduce((total, session) => total + Number(session.n_hyps || 0), 0));
const totalSpent = computed(() => sessions.value.reduce((total, session) => total + Number(session.budget_used_usd || 0), 0));
const themeOptions = computed(() => Object.entries(themes) as [ThemeName, (typeof themes)[ThemeName]][]);
const pageSize = 8;
const currentPage = ref(1);
const totalPages = computed(() => Math.max(1, Math.ceil(sessions.value.length / pageSize)));
const pagedSessions = computed(() => {
  const page = Math.min(currentPage.value, totalPages.value);
  const start = (page - 1) * pageSize;
  return sessions.value.slice(start, start + pageSize);
});

watch(() => sessions.value.length, () => {
  if (currentPage.value > totalPages.value) currentPage.value = totalPages.value;
});

const sessionColumns = computed(() => [
  { title: language.value === "en" ? "Status" : "状态", dataIndex: "status", slotName: "status", width: 110 },
  { title: language.value === "en" ? "Breeding goal" : "育种目标", dataIndex: "research_goal", slotName: "goal", width: 560 },
  { title: language.value === "en" ? "Candidate routes" : "候选路线", dataIndex: "n_hyps", slotName: "hypotheses", align: "right" as const, width: 110 },
  { title: language.value === "en" ? "Budget used" : "预算使用", dataIndex: "budget_used_usd", slotName: "budget", align: "right" as const, width: 150 },
  { title: language.value === "en" ? "Updated" : "更新时间", dataIndex: "updated_at", slotName: "updated", width: 135 },
  { title: language.value === "en" ? "Actions" : "操作", dataIndex: "actions", slotName: "actions", width: 90, align: "right" as const },
]);

function selectTheme(value: string | number | Record<string, any> | undefined) {
  if (typeof value !== "string" || !(value in themes)) return;
  themeName.value = value as ThemeName;
  localStorage.setItem("co-scientist-theme", themeName.value);
}

function toggleLanguage() {
  language.value = language.value === "zh" ? "en" : "zh";
  localStorage.setItem("co-scientist-language", language.value);
}

function themeLabel(key: ThemeName) {
  const labels: Record<Language, Record<ThemeName, string>> = {
    zh: { green: "绿色", gold: "金色", purple: "紫色" },
    en: { green: "Green", gold: "Gold", purple: "Purple" },
  };
  return labels[language.value][key];
}

function navigate(path: string) {
  window.location.href = path;
}

function changePage(direction: number) {
  currentPage.value = Math.max(1, Math.min(totalPages.value, currentPage.value + direction));
}

function statusLabel(status: string) {
  const labels: Record<Language, Record<string, string>> = {
    zh: { running: "运行中", paused: "已暂停", done: "已完成", failed: "失败", aborted: "已终止", draft: "草稿" },
    en: { running: "Running", paused: "Paused", done: "Completed", failed: "Failed", aborted: "Aborted", draft: "Draft" },
  };
  return labels[language.value][status] || status;
}

function statusColor(status: string) {
  if (["running", "in_progress"].includes(status)) return "arcoblue";
  if (status === "done") return "green";
  if (status === "paused") return "orange";
  if (status === "failed") return "red";
  if (status === "aborted") return "gray";
  return "gray";
}

function formatDate(value: string) {
  return value ? value.replace("T", " ").slice(0, 16) : copy.value.empty;
}

function formatMoney(value: number) {
  return `$${Number(value || 0).toFixed(2)}`;
}

async function loadSessions() {
  loading.value = true;
  loadError.value = "";
  try {
    const response = await fetch("/api/sessions");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    sessions.value = await response.json();
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : (language.value === "en" ? "Unable to load session data" : "无法加载会话数据");
  } finally {
    loading.value = false;
  }
}

function openDeleteDialog(session: SessionSummary) {
  pendingDelete.value = session;
  deleteError.value = "";
  deleteDialogVisible.value = true;
}

function closeDeleteDialog() {
  if (deletingId.value) return;
  deleteDialogVisible.value = false;
  pendingDelete.value = null;
  deleteError.value = "";
}

async function confirmDelete() {
  const session = pendingDelete.value;
  if (!session) return;
  deletingId.value = session.id;
  deleteError.value = "";
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(session.id)}`, { method: "DELETE" });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || copy.value.deleteFailed);
    sessions.value = sessions.value.filter((item) => item.id !== session.id);
    deleteDialogVisible.value = false;
    pendingDelete.value = null;
  } catch (error) {
    deleteError.value = error instanceof Error ? error.message : copy.value.deleteFailed;
  } finally {
    deletingId.value = "";
  }
}

onMounted(() => {
  if (isWorkspace) loadSessions();
});
</script>

<template>
  <div class="app-shell" :class="{ 'workspace-mode': isWorkspace }" :style="themeStyles">
    <a-layout>
      <a-layout-header class="topbar">
        <div class="topbar-inner">
          <a class="brand" href="/">
            <span class="brand-mark">BS</span>
            <span><strong>Breeding Scientist</strong><small>{{ copy.brandSubtitle }}</small></span>
          </a>
          <nav class="main-nav" aria-label="主导航">
            <a :class="{ active: !isWorkspace }" href="/">{{ copy.navScientist }}</a>
            <a href="#knowledge">{{ copy.navKnowledge }}</a>
            <a :class="{ active: isWorkspace }" href="/sessions">{{ copy.navSessions }}</a>
          </nav>
          <a-space :size="12">
            <a-button type="text" class="language-button" :aria-label="copy.switchLanguage" @click="toggleLanguage"><IconTranslate /> <span>{{ language === "zh" ? "中文" : "English" }}</span></a-button>
            <a-dropdown @select="selectTheme">
              <a-button type="text" class="theme-button">
                <span class="theme-dot" :style="{ background: currentTheme.color }"></span>
                {{ copy.themeColor }} <span class="chevron">›</span>
              </a-button>
              <template #content>
                <a-doption v-for="([key, value]) in themeOptions" :key="key" :value="key">
                  <span class="theme-option"><span class="theme-dot" :style="{ background: value.color }"></span>{{ themeLabel(key) }}<b v-if="themeName === key">✓</b></span>
                </a-doption>
              </template>
            </a-dropdown>
            <a-button type="primary" @click="navigate('/sessions/new')">{{ copy.newSession }}</a-button>
          </a-space>
        </div>
      </a-layout-header>

      <a-layout-content>
        <main class="page-container">
          <template v-if="!isWorkspace">
          <section class="hero-section">
            <div class="hero-copy">
              <div class="eyebrow"><span></span> {{ copy.heroEyebrow }}</div>
              <h1>{{ copy.heroTitle }}<br /><em>{{ copy.heroTitleAccent }}</em></h1>
              <p>{{ copy.heroDescription }}</p>
              <a-space :size="12">
                <a-button type="primary" size="large" @click="navigate('/sessions/new')">{{ copy.startResearch }} <span>→</span></a-button>
                <a-button size="large" type="text" href="#knowledge">{{ copy.exploreKnowledge }}</a-button>
              </a-space>
            </div>
            <div class="hero-assistant-card" aria-label="Breeding Scientist workspace preview">
              <div class="assistant-card-top"><span class="assistant-status"><i></i>{{ copy.assistantEyebrow }}</span><span class="assistant-mark">BS</span></div>
              <div class="assistant-card-main"><div class="assistant-kicker">CO-SCIENTIST</div><h3>{{ copy.assistantTitle }}</h3><p>{{ copy.assistantPrompt }}</p></div>
              <div class="assistant-prompt"><span class="prompt-dot"></span><span>{{ copy.assistantHint }}</span><b>↗</b></div>
              <div class="assistant-tags"><span v-for="tag in copy.assistantTags" :key="tag">{{ tag }}</span></div>
              <div class="assistant-steps"><div v-for="(step, index) in copy.assistantSteps" :key="step" class="assistant-step"><span>{{ String(index + 1).padStart(2, "0") }}</span><b>{{ step }}</b></div></div>
            </div>
          </section>

          <section id="knowledge" class="entry-section">
            <div class="section-heading"><div><div class="eyebrow"><span></span> {{ copy.coreEyebrow }}</div><h2>{{ copy.coreTitle }}</h2><p>{{ copy.coreDescription }}</p></div></div>
            <div class="entry-grid">
              <a-card class="entry-card knowledge-entry" hoverable @click="navigate('/knowledge')">
                <div class="entry-icon">▦</div><div class="entry-kicker">{{ copy.knowledgeKicker }}</div><h3>{{ copy.knowledgeTitle }}</h3><p>{{ copy.knowledgeDescription }}</p><div class="entry-items"><span v-for="item in copy.knowledgeItems" :key="item">{{ item }}</span></div><span class="entry-link">{{ copy.knowledgeAction }} <b>→</b></span>
              </a-card>
              <a-card class="entry-card scientist-entry" hoverable>
                <div class="entry-icon">✦</div><div class="entry-kicker">{{ copy.scientistKicker }}</div><h3>{{ copy.scientistTitle }}</h3><p>{{ copy.scientistDescription }}</p><div class="entry-items"><span v-for="item in copy.scientistItems" :key="item">{{ item }}</span></div><span class="entry-link">{{ copy.scientistAction }} <b>→</b></span>
                <a class="entry-card-hit-area" href="/sessions" :aria-label="copy.scientistAction"></a>
              </a-card>
            </div>
          </section>
          </template>

          <section v-if="isWorkspace" id="sessions" class="content-section">
            <div class="section-heading section-heading-row"><div><div class="eyebrow"><span></span> {{ copy.workspaceEyebrow }}</div><h2>{{ copy.workspaceTitle }}</h2><p>{{ copy.workspaceDescription }}</p></div><a-button type="primary" @click="navigate('/sessions/new')">＋ {{ copy.newSession }}</a-button></div>
            <div class="metrics-strip"><div class="metric-card metric-card-total"><span class="metric-code">01</span><strong>{{ sessions.length }}</strong><span>{{ copy.researchSessions }}</span></div><div class="metric-card metric-card-running"><span class="metric-code">02</span><strong>{{ runningCount }}</strong><span>{{ copy.running }}</span></div><div class="metric-card metric-card-hypotheses"><span class="metric-code">03</span><strong>{{ hypothesisCount }}</strong><span>{{ copy.hypotheses }}</span></div><div class="metric-card metric-card-budget"><span class="metric-code">04</span><strong>{{ formatMoney(totalSpent) }}</strong><span>{{ copy.budgetSpent }}</span></div></div>
            <div v-if="deleteError" class="session-delete-error"><span>{{ deleteError }}</span></div>
            <div v-if="loading" class="table-loading"><a-skeleton animation :rows="6" /></div>
            <a-card v-else-if="loadError" class="state-card"><a-empty :description="copy.unavailable"><template #extra><a-button @click="loadSessions">{{ copy.reload }}</a-button></template></a-empty></a-card>
            <a-card v-else-if="sessions.length === 0" class="state-card"><a-empty :description="copy.noSessions"><template #extra><a-button type="primary" @click="navigate('/sessions/new')">{{ copy.createFirst }}</a-button></template></a-empty></a-card>
            <a-card v-else class="session-table-card" :bordered="false"><div class="table-card-heading"><div><span class="table-card-kicker">ACTIVE PLAN SET</span><strong>{{ copy.planTableTitle }}</strong><small>{{ copy.planTableDescription }}</small></div><span class="table-card-count">{{ sessions.length }} {{ copy.planCountLabel }}</span></div><a-table :columns="sessionColumns" :data="pagedSessions" row-key="id" :pagination="false" stripe>
              <template #status="{ record }"><a-tag :class="`status-tag status-${record.status}`" :color="statusColor(record.status)" bordered>{{ statusLabel(record.status) }}</a-tag></template>
              <template #goal="{ record }"><a class="table-goal" :href="`/sessions/${record.id}`"><strong>{{ record.research_goal }}</strong></a></template>
              <template #hypotheses="{ record }"><span class="table-hypotheses">{{ record.n_hyps }} <small>条</small></span></template>
              <template #budget="{ record }"><span class="table-money">{{ formatMoney(record.budget_used_usd) }}</span><small> / {{ formatMoney(record.budget_usd) }}</small></template>
              <template #updated="{ record }"><span class="table-date">{{ formatDate(record.updated_at) }}</span></template>
              <template #actions="{ record }"><a-button type="text" status="danger" size="small" class="table-delete" :loading="deletingId === record.id" :aria-label="copy.delete" :title="copy.delete" @click.stop="openDeleteDialog(record)"><svg class="delete-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 7.2v8.1c0 .8.6 1.4 1.4 1.4h6.2c.8 0 1.4-.6 1.4-1.4V7.2M4 5.2h12M8 5.2V3.8h4v1.4M8.4 9.2v4.5M11.6 9.2v4.5" /></svg></a-button></template>
            </a-table><div class="plan-pagination"><div class="plan-pagination-actions"><a-button type="text" class="plan-page-button" :disabled="currentPage <= 1" :aria-label="copy.previousPage" @click="changePage(-1)">‹</a-button><span class="plan-page-current">{{ currentPage }}</span><span class="plan-page-total">/ {{ totalPages }}</span><a-button type="text" class="plan-page-button" :disabled="currentPage >= totalPages" :aria-label="copy.nextPage" @click="changePage(1)">›</a-button></div></div></a-card>
          </section>

          <template v-if="!isWorkspace">
          <section class="workflow-section"><div class="eyebrow"><span></span> {{ copy.workflowEyebrow }}</div><h2>{{ copy.workflowTitle }}</h2><div class="workflow-grid"><div v-for="(step, index) in copy.workflowSteps" :key="step.title" class="workflow-step"><small>{{ String(index + 1).padStart(2, "0") }}</small><strong>{{ step.title }}</strong><p>{{ step.description }}</p></div></div></section>
          </template>
        </main>
      </a-layout-content>
    </a-layout>
    <a-modal v-model:visible="deleteDialogVisible" :footer="false" :width="460" :closable="!deletingId" :mask-closable="!deletingId" :esc-to-close="!deletingId" @cancel="closeDeleteDialog">
      <template #title><div class="delete-modal-heading"><div class="delete-modal-icon"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 7.2v8.1c0 .8.6 1.4 1.4 1.4h6.2c.8 0 1.4-.6 1.4-1.4V7.2M4 5.2h12M8 5.2V3.8h4v1.4M8.4 9.2v4.5M11.6 9.2v4.5" /></svg></div><span>{{ copy.deleteTitle }}</span></div></template>
      <div class="delete-modal-body">
        <p class="delete-modal-lead">{{ copy.deleteWarning }}</p>
        <div class="delete-target"><span>{{ copy.deleteTarget }}</span><code>{{ pendingDelete ? pendingDelete.id.slice(-12) : "" }}</code></div>
        <p v-if="deleteError" class="delete-modal-error">{{ deleteError }}</p>
        <div class="delete-modal-actions"><a-button type="secondary" :disabled="Boolean(deletingId)" @click="closeDeleteDialog">{{ copy.cancel }}</a-button><a-button type="primary" status="danger" :loading="Boolean(deletingId)" @click="confirmDelete">{{ copy.deleteAction }}</a-button></div>
      </div>
    </a-modal>
  </div>
</template>
