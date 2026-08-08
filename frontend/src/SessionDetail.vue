<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";

type ThemeName = "green" | "gold" | "purple";
type Language = "zh" | "en";

const sessionId = window.location.pathname.split("/").filter(Boolean).pop() || "";
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
const controlLoading = ref("");
const eventSource = ref<EventSource | null>(null);
let refreshTimer: number | null = null;
let pollingTimer: number | null = null;
const agentRuntime = reactive<Record<string, { status: string; active: boolean; step: string }>>({});
const agentStreams = reactive<Record<string, string[]>>({});

const currentTheme = computed(() => themes[themeName.value]);
const themeStyles = computed(() => ({
  "--theme-color": currentTheme.value.color,
  "--theme-color-hover": currentTheme.value.hover,
  "--theme-color-pressed": currentTheme.value.pressed,
  "--theme-soft": `${currentTheme.value.color}12`,
}));
const isEnglish = computed(() => language.value === "en");
const copy = computed(() => isEnglish.value ? {
  brandSubtitle: "Breeding Scientist", knowledge: "Knowledge Base", sessions: "Research Sessions", newSession: "New breeding session", theme: "Theme",
  eyebrow: "BREEDING SCIENTIST  /  SESSION WORKSPACE", session: "Breeding session", goal: "Breeding goal", budget: "Budget usage", acceptance: "Result acceptance",
  result: "Research conclusion", resultDescription: "A concise view of the routes that are ready to move into validation.", priorityRoute: "Priority route", nextValidation: "Next validation", routeCount: "Candidate routes", readyRoutes: "Ready to advance", pendingRoutes: "Need more evidence", viewPriorityRoute: "Open priority route", viewRunInfo: "View run information", hideRunInfo: "Hide run information",
  agents: "Six-agent execution", currentWork: "Current work", noWork: "No agent is currently running", overview: "View final overview", evidence: "View evidence graph", revision: "View route revision", outputs: "Review agent outputs",
  ranked: "Recommended breeding routes", rankedDescription: "Candidate routes currently worth prioritizing and validating.", pending: "Routes requiring further work", resources: "Reference germplasm resources", route: "Breeding route", decision: "Current recommendation", next: "Next step", evidenceLink: "Route evidence", status: "Status", source: "Source", risk: "Risk / evidence gap", use: "Use / trait clue", material: "Material",
  noRoutes: "The system is still organizing evidence and candidate routes.", pause: "Pause analysis", resume: "Resume analysis", abort: "Stop analysis", done: "Completed", running: "Running", paused: "Paused", failed: "Failed", pendingStatus: "Queued", notStarted: "Not started", loading: "Loading session...", retry: "Retry", language: "中文",
} : {
  brandSubtitle: "育种科学家", knowledge: "知识库", sessions: "研究会话", newSession: "新建育种会话", theme: "色调",
  eyebrow: "BREEDING SCIENTIST  /  SESSION WORKSPACE", session: "育种会话", goal: "育种目标", budget: "预算使用", acceptance: "结果验收",
  result: "研究结论", resultDescription: "先看本次分析形成的优先路线，再查看证据和研究过程。", priorityRoute: "当前优先路线", nextValidation: "下一步验证", routeCount: "候选路线", readyRoutes: "可推进路线", pendingRoutes: "待补证据路线", viewPriorityRoute: "查看优先路线", viewRunInfo: "查看运行信息", hideRunInfo: "收起运行信息",
  agents: "六智能体执行状态", currentWork: "当前工作", noWork: "当前没有正在执行的智能体", overview: "查看最终综述", evidence: "查看总证据图谱", revision: "查看路线修订图", outputs: "六智能体成果审阅",
  ranked: "推荐育种路线", rankedDescription: "当前最值得优先关注和验证的候选方案。", pending: "需要进一步处理的路线", resources: "可参考的种质资源", route: "育种路线", decision: "当前建议", next: "下一步", evidenceLink: "路线证据", status: "状态", source: "来源", risk: "风险 / 证据缺口", use: "用途 / 性状线索", material: "材料",
  noRoutes: "系统正在整理证据和候选路线，请稍后查看。", pause: "暂停分析", resume: "继续分析", abort: "终止分析", done: "已完成", running: "运行中", paused: "已暂停", failed: "失败", pendingStatus: "排队中", notStarted: "未开始", loading: "正在加载会话……", retry: "重试", language: "EN",
});

const session = computed(() => detail.value?.session || {});
const hypotheses = computed(() => detail.value?.hypotheses || []);
const agents = computed(() => detail.value?.six_agent_summary || []);
const rankedHypotheses = computed(() => detail.value?.ranked_hypotheses || []);
const pendingHypotheses = computed(() => detail.value?.pending_hypotheses || []);
const germplasmResources = computed(() => detail.value?.germplasm_resources || []);
const termination = computed(() => detail.value?.termination_summary || {});
const acceptance = computed(() => detail.value?.acceptance || {});
const evidenceGraph = computed(() => detail.value?.evidence_graph || {});
const routeRevisionGraph = computed(() => detail.value?.route_revision_graph || {});
const priorityRoute = computed(() => rankedHypotheses.value[0] || null);
const priorityRouteNextStep = computed(() => {
  if (!priorityRoute.value) return isEnglish.value ? "More evidence is needed before a route can be prioritized." : "当前还没有可以优先推进的路线，请先补充证据。";
  return directionFor(priorityRoute.value);
});
const resultSummary = computed(() => ({
  total: hypotheses.value.length,
  ready: rankedHypotheses.value.length,
  pending: pendingHypotheses.value.length,
}));
const resultDescriptionText = computed(() => {
  if (termination.value.stop_reason === "pairwise_calibration_stable") {
    return isEnglish.value
      ? "The priority route has remained stable through repeated comparisons and is ready for validation review."
      : "经过多轮比较，当前优先路线已经保持稳定，可以进入后续验证。";
  }
  return copy.value.resultDescription;
});
const percentage = computed(() => {
  const budget = Number(session.value.budget_usd || 0);
  const used = Number(session.value.budget_used_usd || 0);
  return budget > 0 ? Math.min(100, Math.max(0, (used / budget) * 100)) : 0;
});

function toggleLanguage() {
  language.value = language.value === "zh" ? "en" : "zh";
  localStorage.setItem("co-scientist-language", language.value);
}

function selectTheme(value: string | number | Record<string, any> | undefined) {
  if (typeof value !== "string" || !(value in themes)) return;
  themeName.value = value as ThemeName;
  localStorage.setItem("co-scientist-theme", themeName.value);
}

function statusLabel(status: string) {
  const labels: Record<string, string> = { done: copy.value.done, running: copy.value.running, in_progress: copy.value.running, paused: copy.value.paused, failed: copy.value.failed, aborted: isEnglish.value ? "Aborted" : "已终止", draft: isEnglish.value ? "Draft" : "草稿" };
  return labels[status] || status;
}

function statusClass(status: string) {
  if (["running", "in_progress"].includes(status)) return "arcoblue";
  if (status === "done") return "green";
  if (status === "paused") return "orange";
  if (status === "failed") return "red";
  return "gray";
}

function formatMoney(value: unknown) {
  return `$${Number(value || 0).toFixed(2)}`;
}

function terminationTitle() {
  const reason = termination.value.stop_reason;
  const map: Record<string, string> = {
    pairwise_calibration_stable: isEnglish.value ? "Priority route stabilized" : "优先路线已趋于稳定",
    breeding_success_ready: isEnglish.value ? "A promotable breeding route is ready" : "已形成可推进的育种路线",
    breeding_evidence_blocked: isEnglish.value ? "More evidence is needed" : "需要补充证据后再推进",
    breeding_max_hypotheses_reached: isEnglish.value ? "Exploration limit reached" : "已达到探索上限",
    budget: isEnglish.value ? "Budget limit reached" : "已达到预算限制",
    wall_clock: isEnglish.value ? "Time limit reached" : "已达到运行时间限制",
    external: isEnglish.value ? "Run stopped" : "运行已停止",
  };
  return map[reason] || (isEnglish.value ? "Research run completed" : "研究分析已结束");
}

function terminationDescription() {
  const reason = termination.value.stop_reason;
  if (reason === "pairwise_calibration_stable") return isEnglish.value ? "The priority route has remained stable through repeated comparisons. Review the overview and continue to validation." : "经过多轮比较，当前优先路线已经保持稳定，可以查看最终综述并进入后续验证。";
  if (reason === "breeding_success_ready") return isEnglish.value ? "A route is ready for final review and validation planning." : "系统已经筛选出可以进入最终审核和验证规划的育种路线。";
  if (reason === "breeding_evidence_blocked") return isEnglish.value ? "The route still has evidence gaps or conflicts. Add validation material before proceeding." : "当前路线仍存在证据缺口或冲突，请先补充验证材料。";
  if (reason === "budget") return isEnglish.value ? "The budget limit was reached. Current results remain available." : "本次分析已达到预算限制，当前结果仍可查看。";
  if (reason === "wall_clock") return isEnglish.value ? "The time limit was reached. Current results remain available." : "本次分析已达到运行时间限制，当前结果仍可查看。";
  return isEnglish.value ? "The current results remain available for review." : "本次分析已经结束，当前结果仍可查看。";
}

function acceptanceDescription() {
  return acceptance.value.status === "pass"
    ? (isEnglish.value ? "Automatic acceptance passed. You can continue reviewing and using this breeding result." : "自动验收已通过，可以继续查看和使用本次育种结果。")
    : (isEnglish.value ? "Automatic acceptance found issues. Review the final overview for details." : "自动验收发现待处理问题，建议先查看最终综述中的说明。");
}

function decisionFor(hypothesis: any) {
  return detail.value?.latest_iteration_decisions?.[hypothesis.id] || null;
}

function displayDecisionFor(hypothesis: any) {
  return detail.value?.display_iteration_decisions?.[hypothesis.id] || null;
}

function decisionLabel(hypothesis: any) {
  const display = displayDecisionFor(hypothesis);
  const action = display?.display?.action_label || decisionFor(hypothesis)?.action;
  if (!action) return isEnglish.value ? "Pending review" : "待评估";
  return action;
}

function directionFor(hypothesis: any) {
  const decision = decisionFor(hypothesis);
  const display = displayDecisionFor(hypothesis);
  return display?.display_route_revision_intent?.direction_label
    || decision?.new_hypothesis_direction
    || display?.display?.reasons?.[0]
    || decision?.reason_summary
    || (isEnglish.value ? "Continue validation based on route evidence." : "根据路线详情继续确认验证条件");
}

function hasEvidence(hypothesis: any) {
  return Boolean(decisionFor(hypothesis)?.has_evidence_package);
}

function routeAdmission(hypothesis: any) {
  return detail.value?.route_admissions?.[hypothesis.id] || {};
}

function agentStatus(agent: any) {
  const runtime = agentRuntime[agent.name];
  if (["done", "failed", "aborted"].includes(session.value.status) && runtime?.active) {
    return session.value.status === "failed" ? "failed" : "done";
  }
  return runtime?.status || (agent.active ? "active" : agent.failed ? "failed" : agent.pending ? "pending" : agent.done ? "done" : "cancelled");
}

function isAgentWorking(agent: any) {
  if (!["running", "in_progress"].includes(session.value.status)) return false;
  return Boolean(agentRuntime[agent.name]?.active || agent.active);
}

function agentStatusLabel(status: string) {
  const labels: Record<string, string> = { active: isEnglish.value ? "Working" : "工作中", done: copy.value.done, failed: copy.value.failed, pending: copy.value.pendingStatus, cancelled: copy.value.notStarted };
  return labels[status] || status;
}

function agentStep(agent: any) {
  return agentRuntime[agent.name]?.step || agent.steps?.join(isEnglish.value ? ", " : "、") || (isEnglish.value ? "Waiting for a task" : "等待任务进入队列");
}

function agentOutput(agent: any) {
  return agent.outputs?.[0] || null;
}

function parseEvent(event: MessageEvent) {
  try {
    const raw = JSON.parse(event.data || "{}");
    return raw.payload || raw;
  } catch {
    return {};
  }
}

function appendAgentStream(agent: string, message: string) {
  if (!message) return;
  if (!agentStreams[agent]) agentStreams[agent] = [];
  agentStreams[agent].push(message);
  if (agentStreams[agent].length > 8) agentStreams[agent].splice(0, agentStreams[agent].length - 8);
}

function handleAgentEvent(eventName: string, event: MessageEvent) {
  const payload = parseEvent(event);
  if (["session_done", "session_completed", "session_aborted"].includes(eventName)) {
    Object.values(agentRuntime).forEach((state) => {
      state.active = false;
      state.status = eventName === "session_aborted" ? "failed" : "done";
    });
    scheduleDetailRefresh();
    return;
  }
  if (eventName === "session_paused") {
    Object.values(agentRuntime).forEach((state) => { state.active = false; state.status = "pending"; });
    scheduleDetailRefresh();
    return;
  }
  const agent = payload.agent || payload.core_agent;
  if (!agent) return;
  if (!agentRuntime[agent]) agentRuntime[agent] = { status: "cancelled", active: false, step: "" };
  const state = agentRuntime[agent];
  const step = payload.agent_step || payload.public_action || "";
  if (step) state.step = step;
  const taskText = payload.message || step || (isEnglish.value ? "Processing current task" : "正在处理当前任务");
  if (eventName === "task_started" || eventName === "agent_progress") {
    state.status = "active"; state.active = true; appendAgentStream(agent, taskText);
  } else if (eventName === "task_completed") {
    state.status = "done"; state.active = false; appendAgentStream(agent, taskText);
  } else if (eventName === "task_failed") {
    state.status = "failed"; state.active = false; appendAgentStream(agent, payload.err || taskText);
  } else if (eventName === "task_deferred_budget") {
    state.status = "pending"; state.active = false; appendAgentStream(agent, isEnglish.value ? "Deferred because of budget limit" : "因预算限制暂缓处理");
  }
  scheduleDetailRefresh();
}

function scheduleDetailRefresh() {
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(() => {
    refreshTimer = null;
    loadDetail(false);
  }, 350);
}

function syncRuntimeFromSummary(summary: any[]) {
  for (const agent of summary || []) {
    if (!agentRuntime[agent.name] || ["done", "failed", "aborted"].includes(session.value.status)) {
      agentRuntime[agent.name] = {
        status: agent.active ? "active" : agent.failed ? "failed" : agent.pending ? "pending" : agent.done ? "done" : "cancelled",
        active: Boolean(agent.active),
        step: agent.steps?.[agent.steps.length - 1] || "",
      };
    }
  }
}

function connectEvents() {
  if (!sessionId || !window.EventSource) return;
  eventSource.value = new EventSource(`/api/sessions/${encodeURIComponent(sessionId)}/events`);
  ["task_started", "agent_progress", "task_completed", "task_failed", "task_deferred_budget", "session_done", "session_completed", "session_paused", "session_aborted"].forEach((name) => {
    eventSource.value?.addEventListener(name, (event) => handleAgentEvent(name, event as MessageEvent));
  });
}

async function loadDetail(connect = true) {
  loading.value = true; error.value = "";
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/detail`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    detail.value = await response.json();
    syncRuntimeFromSummary(detail.value.six_agent_summary || []);
    if (connect) connectEvents();
  } catch (err) {
    error.value = isEnglish.value ? "Unable to load this session." : "暂时无法加载这个会话。";
  } finally {
    loading.value = false;
  }
}

async function controlSession(action: "pause" | "resume" | "abort") {
  controlLoading.value = action;
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/${action}`, { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await loadDetail();
  } catch {
    error.value = isEnglish.value ? "The session action failed." : "会话操作未成功，请稍后重试。";
  } finally {
    controlLoading.value = "";
  }
}

onMounted(() => {
  loadDetail();
  pollingTimer = window.setInterval(() => {
    if (["running", "in_progress"].includes(session.value.status)) loadDetail(false);
  }, 4000);
});
onBeforeUnmount(() => {
  eventSource.value?.close();
  if (refreshTimer !== null) window.clearTimeout(refreshTimer);
  if (pollingTimer !== null) window.clearInterval(pollingTimer);
});
</script>

<template>
  <div class="session-detail-app" :style="themeStyles">
    <a-layout>
      <a-layout-header class="session-topbar">
        <div class="session-topbar-inner">
          <a class="session-brand" href="/">
            <span class="session-brand-mark">BS</span>
            <span><strong>Breeding Scientist</strong><small>{{ copy.brandSubtitle }}</small></span>
          </a>
          <nav class="session-nav">
            <a href="/knowledge">{{ copy.knowledge }}</a>
            <a href="/">{{ copy.sessions }}</a>
          </nav>
          <a-button type="primary" class="session-new-button" href="/sessions/new">{{ copy.newSession }}</a-button>
        </div>
      </a-layout-header>

      <a-layout-content>
        <main class="session-page">
          <div v-if="loading" class="session-loading"><a-spin :size="32" /><p>{{ copy.loading }}</p></div>
          <a-result v-else-if="error" status="error" :title="error"><template #extra><a-button type="primary" @click="loadDetail()">{{ copy.retry }}</a-button></template></a-result>
          <template v-else>
            <header class="session-hero">
              <div class="session-hero-eyebrow"><span></span>{{ copy.eyebrow }}</div>
              <div class="session-hero-grid">
                <div>
                  <h1>{{ copy.session }}</h1>
                  <div class="session-goal"><a-tag :color="statusClass(session.status)">{{ statusLabel(session.status) }}</a-tag><span>{{ copy.goal }}</span><p>{{ session.research_goal }}</p></div>
                </div>
                <div class="session-hero-meta"><span>{{ isEnglish ? "Session status" : "会话状态" }}</span><strong>{{ statusLabel(session.status) }}</strong></div>
              </div>
            </header>

            <div v-if="termination.available && !['success', 'keep'].includes(termination.state)" class="session-alert session-alert-termination" :class="`session-alert-${termination.state}`"><strong>{{ terminationTitle() }}</strong><p>{{ terminationDescription() }}</p></div>
            <div v-if="acceptance.available && acceptance.status !== 'pass'" class="session-alert session-alert-acceptance needs-review"><strong>{{ copy.acceptance }}</strong><p>{{ acceptanceDescription() }}</p></div>

            <section class="session-result-summary">
              <div class="session-result-heading">
                <div>
                  <span>{{ copy.eyebrow }}</span>
                  <h2>{{ copy.result }}</h2>
                  <p>{{ resultDescriptionText }}</p>
                </div>
                <a-tag :color="priorityRoute ? 'green' : 'orange'">{{ priorityRoute ? copy.readyRoutes : copy.pendingRoutes }}</a-tag>
              </div>
              <div class="session-result-metrics">
                <div><strong>{{ resultSummary.total }}</strong><span>{{ copy.routeCount }}</span></div>
                <div class="is-ready"><strong>{{ resultSummary.ready }}</strong><span>{{ copy.readyRoutes }}</span></div>
                <div class="is-pending"><strong>{{ resultSummary.pending }}</strong><span>{{ copy.pendingRoutes }}</span></div>
              </div>
              <article class="session-priority-route" :class="{ 'is-empty': !priorityRoute }">
                <div>
                  <span class="session-result-label">{{ copy.priorityRoute }}</span>
                  <h3 v-if="priorityRoute"><a :href="`/sessions/${session.id}/hypotheses/${priorityRoute.id}`">{{ priorityRoute.title || (isEnglish ? "Unnamed route" : "未命名路线") }}</a></h3>
                  <h3 v-else>{{ isEnglish ? "No route is ready yet" : "暂未形成可推进路线" }}</h3>
                  <p><strong>{{ copy.nextValidation }}：</strong>{{ priorityRouteNextStep }}</p>
                </div>
                <a-button v-if="priorityRoute" type="primary" :href="`/sessions/${session.id}/hypotheses/${priorityRoute.id}`">{{ copy.viewPriorityRoute }} <span>→</span></a-button>
              </article>
            </section>

            <div class="session-actions-vue">
              <a-button v-if="['running','in_progress'].includes(session.status)" type="primary" :loading="controlLoading === 'pause'" @click="controlSession('pause')">{{ copy.pause }}</a-button>
              <a-button v-if="session.status === 'paused'" type="primary" :loading="controlLoading === 'resume'" @click="controlSession('resume')">{{ copy.resume }}</a-button>
              <a-button v-if="['running','in_progress','paused'].includes(session.status)" class="danger-action" :loading="controlLoading === 'abort'" @click="controlSession('abort')">{{ copy.abort }}</a-button>
              <a-button v-if="session.final_overview" type="primary" :href="`/sessions/${session.id}/overview`">{{ copy.overview }} <span>→</span></a-button>
              <a-button v-if="evidenceGraph.available" :href="`/sessions/${session.id}/evidence-graph`">{{ copy.evidence }}</a-button>
              <a-button v-if="routeRevisionGraph.available" :href="`/sessions/${session.id}/route-revision-graph`">{{ copy.revision }}</a-button>
              <a-button :href="`/sessions/${session.id}/agent-outputs`">{{ copy.outputs }} <span>→</span></a-button>
            </div>

            <details class="session-run-info">
              <summary><span>{{ copy.viewRunInfo }}</span><b>{{ copy.hideRunInfo }}</b><i></i></summary>
              <a-card class="session-budget-card" :bordered="false">
                <div class="session-card-heading"><div><span>{{ copy.budget }}</span><strong>{{ formatMoney(session.budget_used_usd) }} <em>/ {{ formatMoney(session.budget_usd) }}</em></strong></div><b>{{ Math.round(percentage) }}%</b></div>
                <a-progress :percent="percentage / 100" :show-text="false" :stroke-width="9" />
              </a-card>
              <section class="session-agents-section">
                <div class="session-section-heading"><div><span>{{ copy.eyebrow }}</span><h2>{{ copy.agents }}</h2></div><a-tag color="arcoblue">{{ agents.length }} {{ isEnglish ? "agents" : "个智能体" }}</a-tag></div>
                <div class="session-current-work"><strong>{{ copy.currentWork }}</strong><span v-if="!agents.some((agent: any) => isAgentWorking(agent))" class="muted">{{ copy.noWork }}</span><a-tag v-for="agent in agents.filter((item: any) => isAgentWorking(item))" :key="agent.name" color="green">{{ agent.label || agent.name }}</a-tag></div>
                <div class="session-agent-grid">
                  <a-card v-for="agent in agents" :key="agent.name" class="session-agent-card" :class="{ 'is-active': agentStatus(agent) === 'active' }" :bordered="false">
                    <details>
                      <summary><div><strong>{{ agent.label || agent.name }}</strong><small>{{ agentStatusLabel(agentStatus(agent)) }}</small></div><span class="session-chevron"></span></summary>
                      <div class="session-agent-body">
                        <p class="session-agent-step">{{ agentStep(agent) }}</p>
                        <div v-if="agentStreams[agent.name]?.length" class="session-agent-stream"><p v-for="(line, index) in agentStreams[agent.name]" :key="`${agent.name}-${index}`">{{ line }}</p></div>
                        <div v-else class="session-agent-empty">{{ isEnglish ? "Live progress will appear here." : "智能体工作时，实时进度会显示在这里。" }}</div>
                        <div v-if="agentOutput(agent)" class="session-agent-output"><small>{{ isEnglish ? "Latest result" : "最近一次结果" }}</small><strong>{{ agentOutput(agent).title }}</strong><p>{{ agentOutput(agent).summary }}</p><a v-if="agentOutput(agent).url" :href="agentOutput(agent).url">{{ isEnglish ? "View full result" : "查看完整结果" }} →</a></div>
                      </div>
                    </details>
                  </a-card>
                </div>
              </section>
            </details>

            <section v-if="rankedHypotheses.length" class="session-data-section">
              <div class="session-section-heading"><div><span>{{ copy.eyebrow }}</span><h2>{{ copy.ranked }}</h2><p>{{ copy.rankedDescription }}</p></div></div>
              <div class="session-table-wrap"><table><thead><tr><th>{{ isEnglish ? "Rank" : "优先级" }}</th><th>{{ copy.route }}</th><th>{{ copy.decision }}</th><th>{{ copy.next }}</th><th>{{ copy.evidenceLink }}</th></tr></thead><tbody><tr v-for="(hypothesis, index) in rankedHypotheses" :key="hypothesis.id"><td><strong class="route-rank">{{ String(index + 1).padStart(2, "0") }}</strong></td><td><a :href="`/sessions/${session.id}/hypotheses/${hypothesis.id}`">{{ hypothesis.title || (isEnglish ? "Unnamed route" : "未命名路线") }}</a></td><td><a-tag color="green">{{ decisionLabel(hypothesis) }}</a-tag></td><td>{{ directionFor(hypothesis) }}</td><td><a v-if="hasEvidence(hypothesis)" class="route-evidence-pill" :href="`/sessions/${session.id}/hypotheses/${hypothesis.id}/evidence-subgraph`">{{ isEnglish ? "View evidence" : "查看证据" }}</a><span v-else class="muted">{{ isEnglish ? "Not built" : "暂未建立" }}</span></td></tr></tbody></table></div>
            </section>
            <section v-else-if="['running','in_progress','paused'].includes(session.status)" class="session-data-section"><div class="session-section-heading"><div><span>{{ copy.eyebrow }}</span><h2>{{ copy.ranked }}</h2><p>{{ copy.noRoutes }}</p></div></div></section>

            <section v-if="pendingHypotheses.length" class="session-data-section"><div class="session-section-heading"><div><span>{{ copy.eyebrow }}</span><h2>{{ copy.pending }}</h2></div></div><div class="session-table-wrap session-pending-table"><table><colgroup><col style="width: 29%" /><col style="width: 34%" /><col style="width: 29%" /><col style="width: 8%" /></colgroup><thead><tr><th>{{ copy.route }}</th><th>{{ isEnglish ? "Current situation" : "当前情况" }}</th><th>{{ copy.next }}</th><th>{{ copy.evidenceLink }}</th></tr></thead><tbody><tr v-for="hypothesis in pendingHypotheses" :key="hypothesis.id"><td><a :href="`/sessions/${session.id}/hypotheses/${hypothesis.id}`">{{ hypothesis.title || (isEnglish ? "Unnamed route" : "未命名路线") }}</a></td><td>{{ routeAdmission(hypothesis).reasons?.join(isEnglish ? "; " : "；") || (isEnglish ? "Still under evaluation" : "仍在评估中") }}</td><td>{{ routeAdmission(hypothesis).next_step || (isEnglish ? "Review route evidence" : "查看路线详情并补充验证") }}</td><td><a v-if="hasEvidence(hypothesis)" class="route-evidence-pill" :href="`/sessions/${session.id}/hypotheses/${hypothesis.id}/evidence-subgraph`">{{ isEnglish ? "View evidence" : "查看证据" }}</a><span v-else class="muted">{{ isEnglish ? "Not built" : "暂未建立" }}</span></td></tr></tbody></table></div></section>

            <section v-if="germplasmResources.length" class="session-data-section"><div class="session-section-heading"><div><span>{{ copy.eyebrow }}</span><h2>{{ copy.resources }}</h2></div></div><div class="session-table-wrap"><table><thead><tr><th>{{ copy.material }}</th><th>{{ copy.use }}</th><th>{{ copy.source }}</th><th>{{ copy.risk }}</th></tr></thead><tbody><tr v-for="row in germplasmResources" :key="`${row.Material}-${row.Source}`"><td>{{ row.Material }}</td><td>{{ row['Use / trait clue'] }}</td><td><template v-for="source in String(row.Source || '').split(';').map((item: string) => item.trim()).filter(Boolean)" :key="source"><a :href="source" target="_blank" rel="noopener">{{ isEnglish ? "View source" : "查看来源" }}</a><br /></template></td><td>{{ row['Risk / evidence gap'] }}</td></tr></tbody></table></div></section>
          </template>
        </main>
      </a-layout-content>
    </a-layout>
  </div>
</template>

<style scoped>
.session-detail-app { min-height: 100vh; color: #17241f; background: radial-gradient(circle at 7% 0%, color-mix(in srgb, var(--theme-color) 9%, transparent), transparent 28rem), #f7faf8; }
.session-topbar { height: 72px; background: rgba(255,255,255,.9); border-bottom: 1px solid #e1ebe4; backdrop-filter: blur(18px); }
.session-topbar-inner { max-width: 1600px; height: 100%; margin: auto; padding: 0 24px; display: flex; align-items: center; gap: 42px; }
.session-brand { display: flex; align-items: center; gap: 10px; color: #17241f; text-decoration: none; }
.session-brand-mark { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 11px; color: #fff; background: var(--theme-color); box-shadow: 0 8px 20px color-mix(in srgb, var(--theme-color) 25%, transparent); font: 700 12px ui-monospace, monospace; }
.session-brand strong, .session-brand small { display: block; }
.session-brand strong { font-size: 15px; letter-spacing: -.025em; }
.session-brand small { margin-top: 2px; color: #84928a; font-size: 10px; }
.session-new-button { min-height: 40px; padding: 0 20px; border: 0; border-radius: 999px; color: #fff; background: var(--theme-color); box-shadow: 0 9px 22px color-mix(in srgb, var(--theme-color) 22%, transparent); font-weight: 650; }
.session-new-button:hover { color: #fff; border-color: var(--theme-color-hover); background: var(--theme-color-hover); transform: translateY(-1px); }
.session-nav { display: flex; gap: 25px; margin-right: auto; }
.session-nav a { color: #65736b; font-size: 13px; text-decoration: none; }
.session-nav a:hover { color: var(--theme-color); }
.session-language, .session-theme-button { border-radius: 999px; color: #65736b; }
.session-language { color: var(--theme-color); }
.session-theme-dot, .session-theme-option i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 7px; }
.session-theme-option { display: flex; align-items: center; min-width: 82px; }
.session-theme-option b { margin-left: auto; color: var(--theme-color); }
.session-page { max-width: 1600px; margin: auto; padding: 54px 24px 100px; }
.session-loading { display: grid; min-height: 50vh; place-items: center; align-content: center; gap: 15px; color: #7b8981; }
.session-hero { padding-bottom: 27px; border-bottom: 1px solid #dfeae3; }
.session-hero-eyebrow, .session-section-heading > div > span { color: var(--theme-color); font: 700 10px ui-monospace, monospace; letter-spacing: .15em; }
.session-hero-eyebrow span { display: inline-block; width: 19px; height: 1px; margin: 0 8px 3px 0; background: var(--theme-color); }
.session-hero-grid { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 30px; align-items: end; margin-top: 16px; }
.session-hero h1 { margin: 0; color: #17241f; font-size: clamp(38px, 4vw, 58px); line-height: 1.05; letter-spacing: -.065em; }
.session-hero h1 code { display: inline-block; margin-left: 9px; padding: 7px 10px; border: 1px solid #dfe9e3; border-radius: 11px; color: #64736a; background: #f4f8f5; font-size: .36em; letter-spacing: .02em; vertical-align: .25em; }
.session-goal { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin-top: 17px; color: #8b9890; font-size: 14px; }
.session-goal p { flex: 1 1 100%; margin: 2px 0 0; color: #63746a; font-size: 16px; line-height: 1.75; }
.session-hero-meta { padding: 15px 17px; border: 1px solid color-mix(in srgb, var(--theme-color) 15%, #e1ebe4); border-radius: 16px; background: color-mix(in srgb, var(--theme-color) 5%, white); }
.session-hero-meta span, .session-hero-meta strong { display: block; }
.session-hero-meta span { color: #89968e; font-size: 11px; }
.session-hero-meta strong { margin-top: 7px; color: var(--theme-color); font-size: 19px; }
.session-alert { margin-top: 19px; padding: 18px 22px; border: 1px solid #e1ebe4; border-left: 5px solid #a8b4ad; border-radius: 16px; background: rgba(255,255,255,.9); box-shadow: 0 12px 28px rgba(56,89,70,.05); }
.session-alert strong, .session-alert p { display: block; }
.session-alert strong { color: #26362e; font-size: 17px; }
.session-alert p { margin: 7px 0 0; color: #738078; font-size: 14px; line-height: 1.7; }
.session-alert-termination.session-alert-success, .session-alert-termination.session-alert-keep { border-left-color: #2a8a4f; background: #f4fbf5; }
.session-alert-termination.session-alert-capped { border-left-color: #b8771e; background: #fffaf0; }
.session-alert-termination.session-alert-blocked { border-left-color: #b53636; background: #fff5f5; }
.session-alert-acceptance.passed { border-left-color: #2a8a4f; background: #f4fbf5; }
.session-alert-acceptance.needs-review { border-left-color: #b8771e; background: #fffaf0; }
.session-result-summary { margin-top: 22px; padding: 26px; border: 1px solid color-mix(in srgb, var(--theme-color) 16%, #e0eae3); border-radius: 20px; background: #fff; box-shadow: 0 16px 38px rgba(56,89,70,.07); }
.session-result-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.session-result-heading > div > span { color: var(--theme-color); font: 700 10px ui-monospace, monospace; letter-spacing: .15em; }
.session-result-heading h2 { margin: 8px 0 0; color: #17241f; font-size: 30px; letter-spacing: -.055em; }
.session-result-heading p { margin: 7px 0 0; color: #718078; font-size: 14px; line-height: 1.7; }
.session-result-heading :deep(.arco-tag) { margin-top: 2px; border-radius: 999px; padding: 5px 11px; font-weight: 650; }
.session-result-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 23px; }
.session-result-metrics > div { padding: 15px 17px; border: 1px solid #e4ece7; border-radius: 13px; background: #fbfdfb; }
.session-result-metrics strong, .session-result-metrics span { display: block; }
.session-result-metrics strong { color: #2d4236; font-size: 25px; letter-spacing: -.04em; }
.session-result-metrics span { margin-top: 3px; color: #7e8d84; font-size: 12px; }
.session-result-metrics .is-ready { border-color: #cfe8d7; background: #f4fbf5; }
.session-result-metrics .is-ready strong { color: #21804d; }
.session-result-metrics .is-pending { border-color: #f0e1c5; background: #fffaf0; }
.session-result-metrics .is-pending strong { color: #a66719; }
.session-priority-route { display: flex; align-items: center; justify-content: space-between; gap: 22px; margin-top: 14px; padding: 18px 19px; border-left: 4px solid var(--theme-color); border-radius: 12px; background: color-mix(in srgb, var(--theme-color) 5%, white); }
.session-priority-route.is-empty { border-left-color: #c58a32; background: #fffaf0; }
.session-result-label { color: #7a8980; font-size: 11px; }
.session-priority-route h3 { margin: 5px 0 0; color: #253a2e; font-size: 18px; line-height: 1.45; }
.session-priority-route h3 a { color: var(--theme-color); text-decoration: none; }
.session-priority-route h3 a:hover { text-decoration: underline; }
.session-priority-route p { margin: 7px 0 0; color: #65766c; font-size: 13px; line-height: 1.7; }
.session-priority-route p strong { color: #394d40; }
.session-priority-route :deep(.arco-btn) { flex: 0 0 auto; min-height: 42px; border-radius: 10px; }
.session-run-info { margin-top: 16px; }
.session-run-info > summary { display: flex; align-items: center; gap: 9px; width: fit-content; cursor: pointer; list-style: none; color: #728078; font-size: 12px; }
.session-run-info > summary::-webkit-details-marker, .session-run-info > summary::marker { display: none; content: ""; }
.session-run-info > summary b { display: none; color: #9aa69e; font-weight: 500; }
.session-run-info[open] > summary b { display: inline; }
.session-run-info[open] > summary > span { display: none; }
.session-run-info > summary i { width: 7px; height: 7px; border-top: 1px solid #829088; border-right: 1px solid #829088; transform: rotate(45deg); transition: transform .2s ease; }
.session-run-info[open] > summary i { transform: rotate(135deg); }
.session-budget-card { margin-top: 20px; border: 1px solid #e0eae3; border-radius: 20px; box-shadow: 0 16px 38px rgba(56,89,70,.07); }
.session-budget-card :deep(.arco-card-body) { padding: 0; }
.session-card-heading { display: flex; align-items: center; justify-content: space-between; padding: 17px 22px; border-bottom: 1px solid #e6eee9; background: #fbfdfb; }
.session-card-heading span, .session-card-heading strong { display: block; }
.session-card-heading span { color: #748179; font-size: 13px; }
.session-card-heading strong { margin-top: 4px; color: #35483d; font-size: 21px; }
.session-card-heading strong em { color: #9aa69e; font-size: 15px; font-style: normal; }
.session-card-heading > b { color: var(--theme-color); font-size: 19px; }
.session-budget-card :deep(.arco-progress-line) { margin: 22px; width: calc(100% - 44px); }
.session-run-info .session-agents-section { margin-top: 32px; padding-top: 28px; border-top: 1px solid #e4ede7; }
.session-actions-vue { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 13px; margin: 18px 0 50px; }
.session-actions-vue :deep(.arco-btn) { min-height: 50px; border-radius: 13px; color: #40564a; border-color: #dce8df; background: #fff; box-shadow: 0 9px 22px rgba(56,89,70,.06); font-weight: 650; }
.session-actions-vue :deep(.arco-btn-primary) { color: #fff; border-color: var(--theme-color); background: var(--theme-color); box-shadow: 0 11px 25px color-mix(in srgb, var(--theme-color) 22%, transparent); }
.session-actions-vue :deep(.arco-btn-primary:hover) { background: var(--theme-color-hover); border-color: var(--theme-color-hover); }
.session-actions-vue :deep(.arco-btn:hover) { color: var(--theme-color); border-color: color-mix(in srgb, var(--theme-color) 32%, #dce8df); transform: translateY(-1px); }
.session-actions-vue :deep(.danger-action) { color: #a83838; border-color: #f0d6d6; background: #fff7f7; }
.session-section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 15px; }
.session-section-heading h2 { margin: 8px 0 0; color: #17241f; font-size: 32px; letter-spacing: -.055em; }
.session-section-heading p { margin: 7px 0 0; color: #718078; font-size: 14px; line-height: 1.7; }
.session-current-work { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; padding: 12px 14px; border: 1px solid #e2ebe5; border-radius: 13px; color: #66756d; background: rgba(255,255,255,.75); font-size: 13px; }
.session-current-work strong { color: #3c4d43; }
.session-agent-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.session-agent-card { border: 1px solid #e0eae3; border-radius: 16px; box-shadow: 0 12px 26px rgba(56,89,70,.055); }
.session-agent-card :deep(.arco-card-body) { padding: 0; }
.session-agent-card.is-active { border-color: color-mix(in srgb, var(--theme-color) 42%, #e0eae3); box-shadow: 0 14px 30px color-mix(in srgb, var(--theme-color) 12%, transparent); }
.session-agent-card summary { display: flex; align-items: center; gap: 12px; min-height: 72px; padding: 17px 18px; cursor: pointer; list-style: none; }
.session-agent-card summary::-webkit-details-marker, .session-agent-card summary::marker { display: none; content: ""; }
.session-agent-card summary > div { min-width: 0; flex: 1; }
.session-agent-card summary strong, .session-agent-card summary small { display: block; }
.session-agent-card summary strong { color: #2a3a31; font-size: 15px; }
.session-agent-card summary small { margin-top: 5px; color: #23824e; font-size: 11px; }
.session-agent-card:not(.is-active) summary small { color: #89968e; }
.session-chevron { width: 9px; height: 9px; flex: 0 0 9px; border-top: 1.5px solid #8f9e96; border-right: 1.5px solid #8f9e96; transform: rotate(45deg); transition: transform .2s ease; }
.session-agent-card details[open] summary { border-bottom: 1px solid #e8efea; background: #fbfdfb; }
.session-agent-card details[open] .session-chevron { border-color: var(--theme-color); transform: rotate(135deg); }
.session-agent-body { padding: 15px 18px 18px; }
.session-agent-step, .session-agent-empty, .session-agent-output p { margin: 0; color: #718078; font-size: 12px; line-height: 1.65; }
.session-agent-stream { max-height: 145px; overflow: auto; margin: 12px 0; padding: 9px 11px; border-radius: 10px; background: #f6faf7; }
.session-agent-stream p { margin: 0 0 5px; padding-bottom: 5px; border-bottom: 1px solid #e5eee8; color: #687870; font-size: 11px; line-height: 1.55; }
.session-agent-stream p:last-child { margin-bottom: 0; border-bottom: 0; }
.session-agent-output { margin-top: 13px; padding-top: 12px; border-top: 1px solid #e5eee8; }
.session-agent-output small, .session-agent-output strong { display: block; }
.session-agent-output small { color: #8b9890; font-size: 10px; }
.session-agent-output strong { margin: 4px 0; color: #33473b; font-size: 13px; }
.session-agent-output a, .session-data-section a { color: var(--theme-color); font-size: 12px; font-weight: 650; text-decoration: none; }
.session-agent-output a:hover, .session-data-section a:hover { color: var(--theme-color-pressed); text-decoration: underline; }
.session-data-section { margin-top: 52px; }
.session-table-wrap { overflow-x: auto; border: 1px solid #e0eae3; border-radius: 21px; background: rgba(255,255,255,.92); box-shadow: 0 15px 34px rgba(56,89,70,.055); }
.session-table-wrap table { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.session-table-wrap th { padding: 18px 22px; border-bottom: 1px solid #e1ebe4; color: #748179; background: #fbfdfb; font-size: 11px; font-weight: 700; letter-spacing: .04em; text-align: left; }
.session-table-wrap td { padding: 24px 22px; border-bottom: 1px solid #edf2ee; color: #4c5d53; font-size: 14px; line-height: 1.8; vertical-align: top; overflow-wrap: anywhere; }
.session-table-wrap tr:last-child td { border-bottom: 0; }
.session-table-wrap tbody tr:nth-child(even) td { background: #fcfefc; }
.session-table-wrap tbody tr:hover td { background: color-mix(in srgb, var(--theme-color) 5%, white); }
.session-table-wrap td:first-child { color: #2e4437; font-weight: 650; vertical-align: middle; }
.session-table-wrap .route-rank { display: inline-grid; width: 34px; height: 34px; place-items: center; border: 1px solid color-mix(in srgb, var(--theme-color) 20%, #dce8df); border-radius: 11px; color: var(--theme-color); background: var(--theme-soft); font: 700 12px ui-monospace, monospace; }
.session-table-wrap td:nth-child(2) a { display: inline-block; color: var(--theme-color); font-size: 15px; line-height: 1.55; }
.session-table-wrap td small { display: block; margin-top: 4px; color: #9aa69e; font-weight: 400; }
.session-table-wrap td:nth-child(2) small { margin-top: 8px; font-size: 11px; }
.session-table-wrap :deep(.arco-tag) { border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 650; }
.session-table-wrap .route-evidence-pill { display: inline-flex; align-items: center; padding: 6px 11px; border: 1px solid color-mix(in srgb, var(--theme-color) 28%, transparent); border-radius: 999px; color: var(--theme-color); background: var(--theme-soft); font-size: 12px; font-weight: 650; line-height: 1.2; white-space: nowrap; text-decoration: none; }
.session-table-wrap .route-evidence-pill:hover { border-color: var(--theme-color); color: var(--theme-color-pressed); background: color-mix(in srgb, var(--theme-color) 10%, white); text-decoration: none; }
.session-pending-table { width: 100%; }
.session-pending-table td { padding-top: 16px; padding-bottom: 16px; line-height: 1.55; }
.session-pending-table th:nth-child(1), .session-pending-table td:nth-child(1) { width: 30%; }
.session-pending-table th:nth-child(2), .session-pending-table td:nth-child(2) { width: 32%; }
.session-pending-table th:nth-child(3), .session-pending-table td:nth-child(3) { width: 29%; }
.session-pending-table th:nth-child(4), .session-pending-table td:nth-child(4) { width: 8%; }
.session-pending-table td:nth-child(1) a { display: inline-block; color: var(--theme-color); font-size: 15px; font-weight: 650; line-height: 1.55; }
.session-table-wrap th:nth-child(1), .session-table-wrap td:nth-child(1) { width: 7%; }
.session-table-wrap th:nth-child(2), .session-table-wrap td:nth-child(2) { width: 31%; }
.session-table-wrap th:nth-child(3), .session-table-wrap td:nth-child(3) { width: 14%; }
.session-table-wrap th:nth-child(4), .session-table-wrap td:nth-child(4) { width: 30%; }
.session-table-wrap th:nth-child(5), .session-table-wrap td:nth-child(5) { width: 18%; }
@media (max-width: 980px) { .session-nav { display: none; } .session-actions-vue { grid-template-columns: repeat(2, minmax(0, 1fr)); } .session-agent-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .session-hero-grid { grid-template-columns: 1fr; } .session-hero-meta { max-width: 220px; } }
@media (max-width: 620px) { .session-topbar-inner { padding: 0 15px; } .session-topbar-inner > :last-child > :not(:last-child) { display: none; } .session-page { padding: 35px 15px 65px; } .session-actions-vue, .session-agent-grid { grid-template-columns: 1fr; } .session-hero h1 { font-size: 38px; } .session-section-heading h2, .session-result-heading h2 { font-size: 27px; } .session-result-summary { padding: 19px; border-radius: 16px; } .session-result-heading, .session-priority-route { align-items: stretch; flex-direction: column; } .session-result-metrics { gap: 8px; } .session-result-metrics > div { padding: 12px; } .session-result-metrics strong { font-size: 21px; } .session-priority-route :deep(.arco-btn) { width: 100%; } .session-table-wrap table { min-width: 800px; } }
</style>
