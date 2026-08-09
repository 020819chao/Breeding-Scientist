<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import SiteHeader from "./SiteHeader.vue";
import { appPathname } from "./path";

type Language = "zh" | "en";

const parts = appPathname().split("/").filter(Boolean);
const sessionId = parts[1] || "";
const focusId = parts[2] === "hypotheses" ? parts[3] || "" : "";
const language = ref<Language>((localStorage.getItem("co-scientist-language") as Language) || "zh");
const payload = ref<any>(null);
const loading = ref(true);
const error = ref("");

const isEnglish = computed(() => language.value === "en");
const copy = computed(() => isEnglish.value ? {
  sessions: "Research sessions", back: "Back to current session", page: "Route evolution", kicker: "BREEDING SCIENTIST / ROUTE EVOLUTION",
  subtitle: "See how candidate routes are adjusted step by step according to evidence gaps and review conclusions.",
  panelKicker: "ROUTE EVOLUTION", panelTitle: "From the original route to the current route", help: "Click a route name to open its breeding plan.",
  recordsKicker: "REVISION RECORDS", recordsTitle: "Route revision records", original: "Original route", action: "Revision", current: "Current route",
  direction: "Revision direction", gaps: "Evidence to add", evidence: "Evidence", openEvidence: "View evidence subgraph", none: "None recorded",
  advanced: "View all route nodes", route: "Route", status: "Status", loading: "Loading route evolution…", retry: "Retry", unavailable: "No route evolution records yet",
  empty: "No route revision relationships are available yet.", actionLabels: { keep: "Keep", revise: "Revise", expand: "Expand", pause: "Pause", reject: "Reject", pending: "Pending", evolved: "Evolved" },
} : {
  sessions: "育种会话", back: "返回当前会话", page: "路线演化", kicker: "BREEDING SCIENTIST / 路线演化",
  subtitle: "查看候选路线如何根据证据缺口和评审结论逐步调整。",
  panelKicker: "ROUTE EVOLUTION", panelTitle: "从原始路线到当前路线", help: "点击路线名称可查看对应的育种方案。",
  recordsKicker: "REVISION RECORDS", recordsTitle: "路线修订记录", original: "原始路线", action: "修订动作", current: "当前路线",
  direction: "修订方向", gaps: "需要补充的证据", evidence: "证据", openEvidence: "查看证据子图", none: "暂无记录",
  advanced: "查看完整路线节点", route: "路线", status: "状态", loading: "正在加载路线演化…", retry: "重试", unavailable: "暂无路线演化记录",
  empty: "当前还没有可展示的路线修订关系。", actionLabels: { keep: "保留", revise: "修订", expand: "扩展", pause: "暂停", reject: "淘汰", pending: "待处理", evolved: "演化" },
});

const graph = computed(() => payload.value?.graph || {});
const nodes = computed<any[]>(() => graph.value.nodes || []);
const edges = computed<any[]>(() => graph.value.edges || []);
const nodeMap = computed(() => new Map(nodes.value.map((node) => [String(node.id), node])));
const viewBox = computed(() => `0 0 ${graph.value.svg_width || 1120} ${graph.value.svg_height || 620}`);

function toggleLanguage() {
  language.value = language.value === "zh" ? "en" : "zh";
  localStorage.setItem("co-scientist-language", language.value);
}

function actionLabel(action: string) {
  return copy.value.actionLabels[action as keyof typeof copy.value.actionLabels] || action;
}

function nodeById(id: string) {
  return nodeMap.value.get(String(id));
}

function edgePath(edge: any) {
  const source = nodeById(edge.source);
  const target = nodeById(edge.target);
  if (!source || !target) return "";
  const startX = Number(source.x) + 26;
  const startY = Number(source.y);
  const endX = Number(target.x) - 28;
  const endY = Number(target.y);
  const curveX = (startX + endX) / 2;
  return `M ${startX} ${startY} C ${curveX} ${startY}, ${curveX} ${endY}, ${endX} ${endY}`;
}

function formatGaps(values: unknown[]) {
  return values?.length ? values.join(isEnglish.value ? ", " : "、") : copy.value.none;
}

function loadUrl() {
  const query = focusId ? `?focus_id=${encodeURIComponent(focusId)}` : "";
  return `/api/sessions/${encodeURIComponent(sessionId)}/route-revision-graph${query}`;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(loadUrl(), { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(isEnglish.value ? "Unable to load route evolution" : "路线演化加载失败");
    payload.value = await response.json();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="route-revision-app">
    <SiteHeader active="sessions" :language="language" @toggle-language="toggleLanguage" />
    <main class="route-revision-page">
      <nav class="route-revision-breadcrumb" aria-label="breadcrumb">
        <a href="/sessions">{{ copy.sessions }}</a><span>/</span>
        <a :href="`/sessions/${sessionId}`">{{ copy.back }}</a><span>/</span>
        <strong>{{ copy.page }}</strong>
      </nav>

      <header class="route-revision-hero">
        <div>
          <p class="route-revision-kicker">{{ copy.kicker }}</p>
          <h1>{{ copy.page }}</h1>
          <p>{{ copy.subtitle }}</p>
        </div>
        <div v-if="!loading && graph.available" class="route-revision-summary">
          <span><strong>{{ graph.node_count }}</strong>{{ isEnglish ? " candidate routes" : " 条候选路线" }}</span>
          <span><strong>{{ graph.edge_count }}</strong>{{ isEnglish ? " revisions" : " 次路线修订" }}</span>
        </div>
      </header>

      <div v-if="loading" class="route-revision-state">{{ copy.loading }}</div>
      <div v-else-if="error" class="route-revision-state error-state"><p>{{ error }}</p><button type="button" @click="load">{{ copy.retry }}</button></div>
      <template v-else-if="graph.available">
        <section class="route-revision-panel">
          <div class="route-revision-panel-heading">
            <div><p class="route-revision-kicker">{{ copy.panelKicker }}</p><h2>{{ copy.panelTitle }}</h2></div>
            <p>{{ copy.help }}</p>
          </div>
          <div class="route-revision-canvas-wrap">
            <svg class="route-revision-graph-svg" :viewBox="viewBox" role="img" :aria-label="copy.panelTitle">
              <defs><marker id="route-revision-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path class="route-revision-arrow-head" d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
              <g v-for="edge in edges" :key="`${edge.source}-${edge.target}`">
                <path class="route-revision-edge" :class="`route-revision-edge-${edge.action_class}`" :d="edgePath(edge)" marker-end="url(#route-revision-arrow)" />
                <text class="graph-edge-label" :x="((nodeById(edge.source)?.x || 0) + (nodeById(edge.target)?.x || 0)) / 2" :y="((nodeById(edge.source)?.y || 0) + (nodeById(edge.target)?.y || 0)) / 2 - 8">{{ actionLabel(edge.action) }}</text>
              </g>
              <a v-for="node in nodes" :key="node.id" :href="node.href">
                <g class="route-revision-node" :class="`route-revision-node-${node.action_class}`">
                  <circle :cx="node.x" :cy="node.y" r="26" /><text :x="node.x" :y="node.y + 45" text-anchor="middle" class="route-revision-node-action">{{ actionLabel(node.action) }}</text><text :x="node.x" :y="node.y + 63" text-anchor="middle" class="route-revision-node-label">{{ node.label }}</text><title>{{ node.full_label }} · {{ actionLabel(node.action) }}</title>
                </g>
              </a>
            </svg>
          </div>
        </section>

        <section class="route-revision-records">
          <header><p class="route-revision-kicker">{{ copy.recordsKicker }}</p><h2>{{ copy.recordsTitle }}</h2></header>
          <div v-if="edges.length" class="route-revision-table-wrap">
            <table><thead><tr><th>{{ copy.original }}</th><th>{{ copy.action }}</th><th>{{ copy.current }}</th><th>{{ copy.direction }}</th><th>{{ copy.gaps }}</th><th>{{ copy.evidence }}</th></tr></thead>
              <tbody><tr v-for="edge in edges" :key="`record-${edge.source}-${edge.target}`"><td><a :href="nodeById(edge.source)?.href">{{ nodeById(edge.source)?.full_label || edge.source }}</a></td><td><span class="decision-badge">{{ actionLabel(edge.action) }}</span></td><td><a :href="nodeById(edge.target)?.href">{{ nodeById(edge.target)?.full_label || edge.target }}</a></td><td>{{ edge.direction || copy.none }}</td><td>{{ formatGaps(edge.evidence_gap_to_resolve) }}</td><td><a v-if="edge.evidence_subgraph_href" :href="edge.evidence_subgraph_href">{{ copy.openEvidence }}</a><span v-else>{{ copy.none }}</span></td></tr></tbody>
            </table>
          </div>
          <p v-else class="route-revision-empty-copy">{{ copy.empty }}</p>
        </section>

        <details class="route-revision-advanced"><summary>{{ copy.advanced }}</summary><div class="route-revision-table-wrap"><table><thead><tr><th>{{ copy.route }}</th><th>{{ copy.action }}</th><th>{{ copy.status }}</th></tr></thead><tbody><tr v-for="node in nodes" :key="`node-${node.id}`"><td><a :href="node.href">{{ node.full_label }}</a></td><td>{{ actionLabel(node.action) }}</td><td>{{ node.state }}</td></tr></tbody></table></div></details>
      </template>
      <div v-else class="route-revision-state"><strong>{{ copy.unavailable }}</strong><p>{{ copy.empty }}</p></div>
    </main>
  </div>
</template>

<style scoped>
.route-revision-app { min-height: 100vh; color: #17241f; background: radial-gradient(circle at 8% 0%, color-mix(in srgb, var(--theme-color, #16865f) 8%, transparent), transparent 34rem), #f7faf8; }
.route-revision-page { max-width: 1280px; margin: 0 auto; padding: 34px 28px 90px; }
.route-revision-breadcrumb { display: flex; gap: 10px; margin-bottom: 24px; color: #829188; font-size: 13px; }.route-revision-breadcrumb a { color: var(--theme-color, #16865f); }.route-revision-breadcrumb strong { color: #53675b; }
.route-revision-hero, .route-revision-panel, .route-revision-records, .route-revision-advanced { border: 1px solid #dfe9e2; border-radius: 22px; background: rgba(255,255,255,.9); box-shadow: 0 18px 42px rgba(54,82,64,.055); }
.route-revision-hero { display: flex; align-items: end; justify-content: space-between; gap: 30px; padding: 34px 38px; background: linear-gradient(135deg, rgba(255,255,255,.96), color-mix(in srgb, var(--theme-color, #16865f) 5%, #fff)); }.route-revision-kicker { margin: 0; color: var(--theme-color, #16865f); font: 700 11px ui-monospace, monospace; letter-spacing: .14em; }.route-revision-hero h1 { margin: 15px 0 8px; color: #14251d; font-size: clamp(42px, 5vw, 64px); letter-spacing: -.065em; line-height: 1; }.route-revision-hero p:last-child { margin: 0; color: #74847b; font-size: 15px; line-height: 1.7; }.route-revision-summary { display: flex; gap: 20px; padding: 13px 17px; border: 1px solid color-mix(in srgb, var(--theme-color, #16865f) 18%, #dfe9e2); border-radius: 999px; color: #78877e; font-size: 12px; white-space: nowrap; }.route-revision-summary strong { margin-right: 4px; color: var(--theme-color, #16865f); font-size: 22px; }
.route-revision-panel { margin-top: 26px; overflow: hidden; }.route-revision-panel-heading, .route-revision-records > header { display: flex; align-items: end; justify-content: space-between; gap: 20px; padding: 28px 30px 22px; border-bottom: 1px solid #e8efea; }.route-revision-panel-heading h2, .route-revision-records h2 { margin: 8px 0 0; color: #193128; font-size: 27px; letter-spacing: -.045em; }.route-revision-panel-heading > p { margin: 0; color: #84938a; font-size: 12px; }.route-revision-canvas-wrap { overflow: auto; min-height: 620px; padding: 30px; background: radial-gradient(circle at 50% 40%, #fff, #f8fbf9 78%); }.route-revision-graph-svg { display: block; width: 100%; min-width: 1120px; height: auto; }.route-revision-edge { fill: none; stroke: #b9c5bd; stroke-width: 2.5; }.route-revision-edge-revise { stroke: #b8771e; }.route-revision-edge-keep { stroke: #29935b; }.route-revision-edge-pending { stroke: #a8b3ac; stroke-dasharray: 6 5; }.route-revision-node { cursor: pointer; }.route-revision-node circle { fill: var(--theme-color, #16865f); stroke: #fff; stroke-width: 5; filter: drop-shadow(0 7px 10px rgba(50,80,58,.16)); transition: transform .18s ease, filter .18s ease; transform-box: fill-box; transform-origin: center; }.route-revision-node:hover circle { transform: scale(1.12); filter: drop-shadow(0 10px 15px color-mix(in srgb, var(--theme-color, #16865f) 28%, transparent)); }.route-revision-node-revise circle { fill: #b8771e; }.route-revision-node-action { fill: #74847b; font: 600 12px "Microsoft YaHei", sans-serif; }.route-revision-node-label { fill: #385246; font: 600 12px "Microsoft YaHei", sans-serif; }.graph-edge-label { fill: #78877e; font: 600 12px "Microsoft YaHei", sans-serif; }
.route-revision-records { margin-top: 26px; overflow: hidden; }.route-revision-table-wrap { overflow-x: auto; }.route-revision-table-wrap table { width: 100%; min-width: 980px; border-collapse: collapse; }.route-revision-table-wrap th, .route-revision-table-wrap td { padding: 17px 20px; border-bottom: 1px solid #edf2ee; color: #5d7065; font-size: 13px; line-height: 1.6; text-align: left; vertical-align: top; }.route-revision-table-wrap th { color: #7c8b82; background: #fbfdfc; font-size: 12px; font-weight: 700; }.route-revision-table-wrap tr:last-child td { border-bottom: 0; }.route-revision-table-wrap a { color: var(--theme-color, #16865f); font-weight: 650; }.decision-badge { display: inline-flex; padding: 5px 10px; border-radius: 999px; color: var(--theme-color, #16865f); background: var(--theme-soft, #eaf7ef); font-size: 12px; font-weight: 700; white-space: nowrap; }.route-revision-empty-copy { margin: 0; padding: 24px 30px 30px; color: #84938a; }.route-revision-advanced { margin-top: 26px; overflow: hidden; }.route-revision-advanced summary { padding: 20px 24px; color: #53675b; cursor: pointer; font-size: 14px; font-weight: 700; list-style: none; }.route-revision-advanced summary::-webkit-details-marker { display: none; }.route-revision-advanced summary::after { float: right; color: var(--theme-color, #16865f); content: "+"; font-size: 19px; font-weight: 400; }.route-revision-advanced[open] summary::after { content: "−"; }
.route-revision-state { display: grid; min-height: 420px; place-content: center; justify-items: center; gap: 12px; color: #7e8d84; }.route-revision-state p { margin: 0; }.error-state button { padding: 9px 16px; border: 0; border-radius: 999px; color: #fff; background: var(--theme-color, #16865f); cursor: pointer; }
@media (max-width: 760px) { .route-revision-page { padding: 24px 16px 60px; }.route-revision-hero { align-items: flex-start; flex-direction: column; padding: 26px 22px; }.route-revision-summary { white-space: normal; }.route-revision-panel-heading, .route-revision-records > header { align-items: flex-start; flex-direction: column; padding: 24px 22px 18px; }.route-revision-canvas-wrap { padding: 18px; } }
.route-revision-edge { fill: none; stroke: color-mix(in srgb, var(--theme-color, #16865f) 58%, #b9c5bd); stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; opacity: .82; vector-effect: non-scaling-stroke; transition: stroke .2s ease, opacity .2s ease; }
.route-revision-edge-revise { stroke: color-mix(in srgb, var(--theme-color, #16865f) 78%, #8e5b12); }
.route-revision-edge-keep { stroke: var(--theme-color, #16865f); }
.route-revision-edge-pending { stroke: color-mix(in srgb, var(--theme-color, #16865f) 36%, #a8b3ac); stroke-dasharray: 6 5; }
.route-revision-arrow-head { fill: var(--theme-color, #16865f); }
.route-revision-node circle { fill: var(--theme-color, #16865f); transition: fill .2s ease, transform .18s ease, filter .18s ease; }
.route-revision-node-revise circle { fill: color-mix(in srgb, var(--theme-color, #16865f) 78%, #8e5b12); }
.route-revision-node-keep circle { fill: var(--theme-color, #16865f); }
.route-revision-node-pending circle { fill: color-mix(in srgb, var(--theme-color, #16865f) 38%, #a8b3ac); }
.route-revision-node-reject circle { fill: color-mix(in srgb, var(--theme-color, #16865f) 62%, #b34e52); }
.route-revision-node-action { fill: color-mix(in srgb, var(--theme-color, #16865f) 58%, #74847b); }
</style>
