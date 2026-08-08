<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { IconArrowLeft, IconCheck, IconClose, IconSearch, IconZoomIn, IconZoomOut } from "@arco-design/web-vue/es/icon";
import CytoscapeGraph from "./CytoscapeGraph.vue";
import StaticEvidenceGraph from "./StaticEvidenceGraph.vue";
import SiteHeader from "./SiteHeader.vue";

const pathParts = window.location.pathname.split("/");
const sessionId = pathParts[2] || "";
const isHypothesisGraph = pathParts[3] === "hypotheses" && pathParts[5] === "evidence-subgraph";
const hypothesisId = isHypothesisGraph ? pathParts[4] || "" : "";
const graphEndpoint = isHypothesisGraph
  ? `/api/sessions/${sessionId}/hypotheses/${hypothesisId}/evidence-subgraph`
  : `/api/sessions/${sessionId}/evidence-graph`;
const backHref = isHypothesisGraph
  ? `/sessions/${sessionId}/hypotheses/${hypothesisId}`
  : `/sessions/${sessionId}`;
const loading = ref(true);
const error = ref("");
const payload = ref<any>(null);
const search = ref("");
const activeFilter = ref("all");
const selected = ref<{ kind: "node" | "edge"; data: any } | null>(null);
const zoom = ref(1);
const pan = ref({ x: 0, y: 0 });
const dragging = ref(false);
const dragStart = ref({ x: 0, y: 0 });
const language = ref<"zh" | "en">("zh");
const layoutPositions = ref<Record<string, { x: number; y: number }>>({});
const fitVersion = ref(0);
const layoutVersion = ref(0);
const actionFeedback = ref("");

const copy = computed(() => language.value === "en" ? {
  home: "Breeding sessions", back: "Back to session", title: "Evidence graph", subtitle: "Explore the materials, traits, genes, and validation evidence behind the breeding routes.",
  workspace: "Evidence relationship workspace", workspaceDesc: "Follow how breeding materials, traits, mechanisms, environments, and evidence connect.", search: "Search materials, traits, genes, or evidence", all: "All", germplasm: "Germplasm", trait: "Trait", gene: "Gene / marker", environment: "Environment / protocol", evidence: "Sources", risk: "Risk", fit: "Fit graph", layout: "Re-layout", clear: "Clear selection", details: "Node details", empty: "Select a node or relationship", emptyDesc: "Click a graph item to inspect its meaning for the current breeding route.", node: "Evidence node", relation: "Evidence relationship", source: "Source", target: "Target", status: "Status", level: "Evidence level", provenance: "Provenance", allNodes: "View all nodes and relationships", nodes: "Nodes", edges: "Relationships", truncated: "This view shows the key evidence subgraph; the complete knowledge base remains available in the backend.", loading: "Loading evidence graph…", retry: "Retry", unavailable: "The evidence graph is not available yet.", language: "中文",
} : {
  home: "育种会话", back: "返回育种会话", title: "育种证据图谱", subtitle: "查看当前育种路线背后的材料、性状、基因和验证证据。", workspace: "证据关系工作台", workspaceDesc: "追踪材料、性状、机制、环境与证据之间如何共同支撑育种路线。", search: "输入材料、性状、基因或证据名称", all: "全部", germplasm: "种质", trait: "性状", gene: "基因 / 标记", environment: "环境 / 方案", evidence: "资料", risk: "风险", fit: "聚焦图谱", layout: "重新布局", clear: "清除选择", details: "节点详情", empty: "选择一个节点或关系", emptyDesc: "点击图谱中的节点或关系，查看它对当前育种路线的意义。", node: "证据节点", relation: "证据关系", source: "起点", target: "终点", status: "状态", level: "证据等级", provenance: "来源", allNodes: "查看全部节点和关系明细", nodes: "节点", edges: "关系", truncated: "当前展示的是关键证据子图，完整知识库仍保留在后台。", loading: "正在加载证据图谱…", retry: "重试", unavailable: "当前还没有可展示的证据图谱。", language: "English",
});

const pageTitle = computed(() => isHypothesisGraph
  ? (language.value === "en" ? "Route evidence graph" : "路线证据图谱")
  : copy.value.title);
const pageSubtitle = computed(() => isHypothesisGraph
  ? (language.value === "en"
    ? "Inspect the materials, traits, genes, and validation evidence directly connected to this route."
    : "围绕当前育种路线，查看与它直接关联的材料、性状、基因和验证证据。")
  : copy.value.subtitle);
const pageWorkspace = computed(() => isHypothesisGraph
  ? (language.value === "en" ? "Route evidence workspace" : "路线证据工作台")
  : copy.value.workspace);
const pageWorkspaceDesc = computed(() => isHypothesisGraph
  ? (language.value === "en" ? "Follow the evidence chain behind this route and inspect each relationship without leaving the page." : "沿着这条路线查看证据链，并在当前页面直接检查每一条关系。")
  : copy.value.workspaceDesc);
const contextCopy = computed(() => language.value === "en"
  ? { summary: "View route context and iteration history", heading: "Route context and iteration", action: "Current recommendation", parents: "Parent routes", children: "Follow-up routes", direction: "Iteration direction", noDirection: "No additional iteration direction recorded." }
  : { summary: "查看路线背景与迭代信息", heading: "路线背景与迭代信息", action: "当前建议", parents: "关联父路线", children: "后续路线", direction: "迭代方向", noDirection: "暂无额外的迭代方向记录。" });

const graph = computed(() => payload.value?.graph || {});
const nodes = computed<any[]>(() => graph.value.nodes || []);
const edges = computed<any[]>(() => graph.value.edges || []);
const typeLabels = computed<Record<string, string>>(() => ({ germplasm: copy.value.germplasm, trait: copy.value.trait, gene_qtl_marker: copy.value.gene, environment_protocol: copy.value.environment, rag_evidence: copy.value.evidence, risk: copy.value.risk }));
const typeColors: Record<string, string> = { germplasm: "#238b72", trait: "#bd7a1d", gene_qtl_marker: "#7661b7", environment_protocol: "#d4773e", rag_evidence: "#518ba0", risk: "#c14d4d", other: "#8b96a0" };
const filterItems = computed(() => [
  { key: "all", label: copy.value.all },
  { key: "germplasm", label: copy.value.germplasm },
  { key: "trait", label: copy.value.trait },
  { key: "gene_qtl_marker", label: copy.value.gene },
  { key: "environment_protocol", label: copy.value.environment },
  { key: "rag_evidence", label: copy.value.evidence },
  { key: "risk", label: copy.value.risk },
]);

const visibleNodes = computed(() => {
  const needle = search.value.trim().toLowerCase();
  const typeNodes = nodes.value.filter((node) => activeFilter.value === "all" || node.type === activeFilter.value);
  if (!needle) return typeNodes;
  const matches = typeNodes.filter((node) => [node.label, node.full_label, node.id].filter(Boolean).join(" ").toLowerCase().includes(needle));
  const ids = new Set(matches.map((node) => String(node.id)));
  edges.value.forEach((edge) => { if (ids.has(String(edge.source)) || ids.has(String(edge.target))) { ids.add(String(edge.source)); ids.add(String(edge.target)); } });
  return nodes.value.filter((node) => ids.has(String(node.id)));
});
const visibleIds = computed(() => new Set(visibleNodes.value.map((node) => String(node.id))));
const visibleEdges = computed(() => edges.value.filter((edge) => visibleIds.value.has(String(edge.source)) && visibleIds.value.has(String(edge.target))));
const dynamicElements = computed(() => {
  const visible = visibleIds.value;
  return (graph.value.cy_elements || []).filter((element: any) => {
    if (element.group === "nodes") return visible.has(String(element.data?.id));
    return visible.has(String(element.data?.source)) && visible.has(String(element.data?.target));
  });
});
const shownNodeCount = computed(() => visibleNodes.value.length);
const shownEdgeCount = computed(() => visibleEdges.value.length);
const graphHeight = computed(() => Math.max(760, ...nodes.value.map((node) => Number(node.y || 0) + 100)));

function position(node: any) { return layoutPositions.value[String(node.id)] || { x: Number(node.x || 0), y: Number(node.y || 0) }; }
function nodeById(id: string) { return nodes.value.find((node) => String(node.id) === String(id)); }
function colorFor(type: string) { return typeColors[type] || typeColors.other; }
function typeLabel(type: string) { return typeLabels.value[type] || type || (language.value === "en" ? "Other" : "其他证据"); }
function selectNode(node: any) { selected.value = { kind: "node", data: node }; }
function selectEdge(edge: any) { selected.value = { kind: "edge", data: edge }; }
function announce(message: string) {
  actionFeedback.value = message;
}
function selectFilter(key: string) {
  activeFilter.value = key;
  if (selected.value) {
    const selectedId = selected.value.kind === "node"
      ? String(selected.value.data.id)
      : `${selected.value.data.source}->${selected.value.data.target}`;
    const stillVisible = selected.value.kind === "node"
      ? visibleIds.value.has(selectedId)
      : visibleEdges.value.some((edge) => `${edge.source}->${edge.target}` === selectedId);
    if (!stillVisible) selected.value = null;
  }
  const label = filterItems.value.find((item) => item.key === key)?.label || copy.value.all;
  announce(language.value === "en" ? `Showing ${label}: ${shownNodeCount.value} nodes, ${shownEdgeCount.value} relationships.` : `已切换到“${label}”，当前显示 ${shownNodeCount.value} 个节点、${shownEdgeCount.value} 条关系。`);
}
function clearSelection() {
  const hadSelection = Boolean(selected.value);
  selected.value = null;
  announce(language.value === "en" ? (hadSelection ? "Selection cleared." : "No node or relationship is selected.") : (hadSelection ? "已清除当前选择。" : "当前没有选中的节点或关系。"));
}
function fitGraph() {
  fitVersion.value += 1;
  zoom.value = 1;
  pan.value = { x: 0, y: 0 };
  announce(language.value === "en" ? "The graph has been fitted to the visible elements." : "图谱已聚焦到当前显示内容。");
}
function zoomIn() { zoom.value = Math.min(2.5, Number((zoom.value + .15).toFixed(2))); }
function zoomOut() { zoom.value = Math.max(.45, Number((zoom.value - .15).toFixed(2))); }
function relayout() {
  const list = visibleNodes.value;
  const columns = Math.max(1, Math.ceil(Math.sqrt(list.length)));
  const next: Record<string, { x: number; y: number }> = {};
  list.forEach((node, index) => { next[String(node.id)] = { x: 120 + (index % columns) * 180, y: 100 + Math.floor(index / columns) * 145 }; });
  layoutPositions.value = next;
  layoutVersion.value += 1;
  fitGraph();
  announce(language.value === "en" ? "The visible graph has been re-laid out." : "当前图谱已重新布局。");
}
function selectDynamic(item: { kind: "node" | "edge"; data: any }) { selected.value = item; }
function switchLanguage() { language.value = language.value === "zh" ? "en" : "zh"; }
function onWheel(event: WheelEvent) { zoom.value = Math.max(.45, Math.min(2.5, Number((zoom.value + (event.deltaY < 0 ? .1 : -.1)).toFixed(2)))); }
function onPointerDown(event: PointerEvent) { dragging.value = true; dragStart.value = { x: event.clientX - pan.value.x, y: event.clientY - pan.value.y }; }
function onPointerMove(event: PointerEvent) { if (dragging.value) pan.value = { x: event.clientX - dragStart.value.x, y: event.clientY - dragStart.value.y }; }
function onPointerUp() { dragging.value = false; }
async function loadGraph() {
  loading.value = true; error.value = "";
  try { const response = await fetch(graphEndpoint, { headers: { Accept: "application/json" } }); if (!response.ok) throw new Error(`HTTP ${response.status}`); payload.value = await response.json(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "Unable to load graph"; }
  finally { loading.value = false; }
}
watch(search, () => {
  if (!selected.value) return;
  const selectedId = selected.value.kind === "node"
    ? String(selected.value.data.id)
    : `${selected.value.data.source}->${selected.value.data.target}`;
  const stillVisible = selected.value.kind === "node"
    ? visibleIds.value.has(selectedId)
    : visibleEdges.value.some((edge) => `${edge.source}->${edge.target}` === selectedId);
  if (!stillVisible) selected.value = null;
});
onMounted(loadGraph);
</script>

<template>
  <div class="evidence-vue-app">
    <a-layout>
      <SiteHeader active="sessions" :language="language" @toggle-language="switchLanguage" />
      <a-layout-content><main class="evidence-page">
        <div v-if="loading" class="evidence-loading"><a-spin :size="32" /><p>{{ copy.loading }}</p></div>
        <a-result v-else-if="error" status="error" :title="copy.unavailable" :sub-title="error"><template #extra><a-button type="primary" @click="loadGraph">{{ copy.retry }}</a-button></template></a-result>
        <template v-else-if="graph.available">
          <nav class="evidence-breadcrumb"><a href="/sessions"><IconArrowLeft />{{ copy.home }}</a><span>/</span><a :href="backHref">{{ copy.back }}</a><span>/</span><strong>{{ pageTitle }}</strong></nav>
          <header class="evidence-hero"><div><div class="evidence-kicker"><span></span>{{ isHypothesisGraph ? "BREEDING ROUTE EVIDENCE" : "BREEDING EVIDENCE GRAPH" }}</div><h1>{{ pageTitle }}</h1><p>{{ pageSubtitle }}</p></div></header>
          <div v-if="graph.truncated" class="evidence-notice"><IconCheck />{{ copy.truncated }}</div>
          <details v-if="isHypothesisGraph && graph.closed_loop?.available" class="evidence-context" open>
            <summary><span>{{ contextCopy.summary }}</span><span class="details-chevron"></span></summary>
            <div class="evidence-context-body">
              <h3>{{ contextCopy.heading }}</h3>
              <div class="evidence-context-cards">
                <article class="evidence-context-card"><span>{{ contextCopy.action }}</span><strong>{{ graph.closed_loop.action || "—" }}</strong></article>
                <article class="evidence-context-card"><span>{{ contextCopy.parents }}</span><strong>{{ graph.closed_loop.parents?.length || 0 }}</strong></article>
                <article class="evidence-context-card"><span>{{ contextCopy.children }}</span><strong>{{ graph.closed_loop.children?.length || 0 }}</strong></article>
              </div>
              <p class="evidence-context-direction"><strong>{{ contextCopy.direction }}：</strong>{{ graph.closed_loop.direction || contextCopy.noDirection }}</p>
              <div v-if="graph.closed_loop.children?.length" class="evidence-context-links"><a v-for="child in graph.closed_loop.children" :key="child.id" :href="child.href">{{ child.title }}</a></div>
            </div>
          </details>
          <section class="evidence-workspace"><div class="evidence-workspace-heading"><div><div class="evidence-kicker">{{ pageWorkspace }}</div><h2>{{ pageWorkspace }}</h2><p>{{ pageWorkspaceDesc }}</p></div><div class="evidence-counts"><strong>{{ shownNodeCount }}</strong><span>{{ language === "en" ? "visible nodes" : "当前节点" }} / {{ graph.node_count }}</span><strong>{{ shownEdgeCount }}</strong><span>{{ language === "en" ? "visible relationships" : "当前关系" }} / {{ graph.edge_count }}</span></div></div>
          <div class="evidence-browser"><div class="evidence-toolbar"><label class="evidence-search"><IconSearch /><input v-model="search" type="search" :placeholder="copy.search" /></label><div class="evidence-filters"><button v-for="item in filterItems" :key="item.key" :class="{ active: activeFilter === item.key }" :aria-pressed="activeFilter === item.key" type="button" @click="selectFilter(item.key)">{{ item.label }}</button></div><div class="evidence-actions"><button type="button" @click="fitGraph">{{ copy.fit }}</button><button type="button" @click="relayout">{{ copy.layout }}</button><button type="button" @click="clearSelection">{{ copy.clear }}</button></div></div><div v-if="actionFeedback" class="evidence-feedback" role="status"><IconCheck />{{ actionFeedback }}</div><div class="evidence-legend"><span v-for="item in ['germplasm','trait','gene_qtl_marker','environment_protocol','rag_evidence','risk']" :key="item"><i :style="{ background: colorFor(item) }"></i>{{ typeLabel(item) }}</span></div><div class="evidence-graph-grid"><CytoscapeGraph :elements="dynamicElements" :all-elements="graph.cy_elements || []" :show-isolated-labels="true" :selected="selected" :fit-version="fitVersion" :layout-version="layoutVersion" @select="selectDynamic" @clear="clearSelection" /><aside class="evidence-detail"><div class="evidence-detail-head"><strong>{{ copy.details }}</strong><button type="button" @click="clearSelection"><IconClose /></button></div><div v-if="!selected" class="evidence-detail-empty"><span>+</span><strong>{{ copy.empty }}</strong><p>{{ copy.emptyDesc }}</p></div><div v-else class="evidence-detail-content"><div class="detail-kicker">{{ selected.kind === 'node' ? copy.node : copy.relation }}</div><h3>{{ selected.kind === 'node' ? (selected.data.full_label || selected.data.label || selected.data.id) : (selected.data.predicate || copy.relation) }}</h3><span v-if="selected.kind === 'node'" class="detail-type" :style="{ color: colorFor(selected.data.type), background: `${colorFor(selected.data.type)}18` }">{{ typeLabel(selected.data.type) }}</span><dl><template v-if="selected.kind === 'node'"><dt>{{ copy.level }}</dt><dd>{{ selected.data.evidence_level || '—' }}</dd><dt>{{ copy.status }}</dt><dd>{{ selected.data.status || '—' }}</dd></template><template v-else><dt>{{ copy.source }}</dt><dd>{{ selected.data.source_label || selected.data.source }}</dd><dt>{{ copy.target }}</dt><dd>{{ selected.data.target_label || selected.data.target }}</dd><dt>{{ copy.level }}</dt><dd>{{ selected.data.evidence_level || '—' }}</dd><dt>{{ copy.status }}</dt><dd>{{ selected.data.status || '—' }}</dd><dt>{{ copy.provenance }}</dt><dd>{{ selected.data.provenance || '—' }}</dd></template></dl></div></aside></div></div></section>
          <details class="evidence-static-view"><summary><span>备用静态图谱</span><span class="details-chevron"></span></summary><StaticEvidenceGraph :nodes="nodes" :edges="edges" /></details><details class="evidence-data"><summary><span>{{ copy.allNodes }}</span><span class="details-chevron"></span></summary><div class="evidence-data-body"><h3>{{ copy.nodes }} ({{ nodes.length }})</h3><div class="evidence-table-scroll"><table><thead><tr><th>Type</th><th>ID</th><th>Label</th><th>{{ copy.status }}</th><th>{{ copy.level }}</th></tr></thead><tbody><tr v-for="node in nodes" :key="`row-${node.id}`"><td><span class="table-type" :style="{ color: colorFor(node.type) }">{{ typeLabel(node.type) }}</span></td><td><code>{{ node.id }}</code></td><td>{{ node.full_label || node.label }}</td><td>{{ node.status || '—' }}</td><td>{{ node.evidence_level || '—' }}</td></tr></tbody></table></div><h3>{{ copy.edges }} ({{ edges.length }})</h3><div class="evidence-table-scroll"><table><thead><tr><th>{{ copy.source }}</th><th>Predicate</th><th>{{ copy.target }}</th><th>{{ copy.status }}</th><th>{{ copy.provenance }}</th></tr></thead><tbody><tr v-for="edge in edges" :key="`edge-row-${edge.source}-${edge.target}-${edge.predicate}`"><td><code>{{ edge.source }}</code></td><td>{{ edge.predicate }}</td><td><code>{{ edge.target }}</code></td><td>{{ edge.status || '—' }}</td><td>{{ edge.provenance || '—' }}</td></tr></tbody></table></div></div></details>
        </template>
        <a-result v-else status="info" :title="copy.unavailable" />
      </main></a-layout-content>
    </a-layout>
  </div>
</template>

<style scoped>
.evidence-vue-app { min-height: 100vh; color: #17241f; background: radial-gradient(circle at 8% 0%, color-mix(in srgb, var(--theme-color) 8%, transparent), transparent 34rem), #f7faf8; }.evidence-topbar { height: 76px; display: flex; align-items: center; justify-content: space-between; padding: 0 42px; border-bottom: 1px solid #e1ebe4; background: rgba(255,255,255,.9); backdrop-filter: blur(18px); }.evidence-brand { display: inline-flex; align-items: center; gap: 12px; color: #17241f; text-decoration: none; }.evidence-brand > span { display: grid; width: 44px; height: 44px; place-items: center; border-radius: 13px; color: #fff; background: var(--theme-color); font: 700 13px Georgia,serif; box-shadow: 0 9px 18px color-mix(in srgb, var(--theme-color) 20%, transparent); }.evidence-brand strong,.evidence-brand small { display: block; }.evidence-brand strong { font-size: 18px; letter-spacing: -.03em; }.evidence-brand small { margin-top: 2px; color: #87968e; font-size: 11px; font-weight: 400; }.evidence-nav { display: flex; align-items: center; gap: 20px; }.evidence-nav a { color: var(--theme-color); text-decoration: none; font-size: 15px; }.evidence-new-session { padding: 11px 17px; border-radius: 12px; color: #fff!important; background: var(--theme-color); }.evidence-page { width: min(1320px, calc(100% - 48px)); margin: 0 auto; padding: 38px 0 80px; }.evidence-breadcrumb { display: flex; align-items: center; gap: 10px; margin-bottom: 22px; color: #849188; font-size: 13px; }.evidence-breadcrumb a { display: inline-flex; align-items: center; gap: 5px; color: #b8771e; text-decoration: none; }.evidence-breadcrumb strong { color: #33493c; }.evidence-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 32px 38px 36px; border: 1px solid #deebe2; border-radius: 22px; background: linear-gradient(135deg,#fff,color-mix(in srgb,var(--theme-color) 5%,#fff)); box-shadow: 0 18px 42px rgba(54,82,64,.05); }.evidence-kicker { color: #7661b7; font: 700 11px ui-monospace,monospace; letter-spacing: .13em; }.evidence-hero h1 { margin: 13px 0 9px; color: #162b21; font-size: clamp(38px,5vw,60px); letter-spacing: -.06em; line-height: 1.03; }.evidence-hero p,.evidence-workspace-heading p { margin: 0; color: #72847a; font-size: 16px; line-height: 1.7; }.evidence-language { display: inline-flex; align-items: center; gap: 7px; padding: 9px 14px; border: 1px solid #dfe9e2; border-radius: 999px; color: var(--theme-color); background: #fff; cursor: pointer; }.evidence-notice { margin: 18px 0; padding: 14px 18px; border: 1px solid #f0dfbe; border-left: 4px solid #b8771e; border-radius: 12px; color: #866b43; background: #fffaf1; font-size: 13px; }.evidence-notice svg { margin-right: 7px; color: #b8771e; }.evidence-workspace { margin-top: 28px; }.evidence-workspace-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 16px; padding: 0 4px; }.evidence-workspace-heading h2 { margin: 8px 0 5px; color: #193128; font-size: clamp(30px,4vw,44px); letter-spacing: -.06em; }.evidence-counts { display: grid; grid-template-columns: auto auto; gap: 2px 8px; min-width: 170px; padding: 14px 16px; border: 1px solid #e6e3f5; border-radius: 16px; background: #fcfbff; }.evidence-counts strong { color: #7661b7; font-size: 26px; text-align: right; }.evidence-counts span { color: #8a918e; font-size: 12px; }.evidence-browser { overflow: hidden; border: 1px solid #dfe9e2; border-radius: 22px; background: #fff; box-shadow: 0 20px 48px rgba(53,74,63,.075); }.evidence-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; padding: 16px; border-bottom: 1px solid #e9efeb; background: #fbfdfc; }.evidence-search { display: flex; align-items: center; gap: 8px; min-width: 270px; flex: 1 1 270px; padding: 0 13px; border: 1px solid #dfe9e2; border-radius: 12px; color: #9aa9a0; background: #fff; }.evidence-search input { min-height: 40px; margin: 0; padding: 0; border: 0; outline: 0; box-shadow: none; background: transparent; }.evidence-filters,.evidence-actions { display: flex; gap: 7px; overflow-x: auto; }.evidence-filters button,.evidence-actions button { min-height: 40px; padding: 7px 12px; border: 1px solid #dfe9e2; border-radius: 11px; color: #5d7165; background: #fff; font-size: 12px; font-weight: 650; white-space: nowrap; cursor: pointer; }.evidence-filters button.active,.evidence-filters button:hover,.evidence-actions button:hover { border-color: var(--theme-color); color: var(--theme-color); background: var(--theme-soft); }.evidence-legend { display: flex; flex-wrap: wrap; gap: 16px; padding: 13px 18px; border-bottom: 1px solid #e9efeb; color: #718178; font-size: 12px; }.evidence-legend span { display: inline-flex; align-items: center; gap: 6px; }.evidence-legend i { width: 10px; height: 10px; border-radius: 999px; }.evidence-graph-grid { display: grid; grid-template-columns: minmax(0,1fr) 330px; min-height: 700px; }.evidence-canvas { position: relative; min-width: 0; min-height: 700px; overflow: hidden; touch-action: none; cursor: grab; background: radial-gradient(circle at 50% 46%,#fff,#f8fbf9 75%); }.evidence-canvas:active { cursor: grabbing; }.evidence-canvas svg { display: block; width: 100%; height: 100%; min-height: 700px; }.evidence-edge { stroke: #bdcbc2; stroke-width: 2; opacity: .75; cursor: pointer; }.evidence-edge:hover,.evidence-edge.selected { stroke: #b8771e; stroke-width: 4; opacity: 1; }.evidence-node { cursor: pointer; }.evidence-node circle { stroke: #fff; stroke-width: 3; filter: drop-shadow(0 5px 8px rgba(40,61,49,.12)); }.evidence-node text { fill: #42574b; font-size: 11px; font-weight: 650; pointer-events: none; }.evidence-node.selected circle { stroke: #b8771e; stroke-width: 6; }.evidence-canvas-hint { position: absolute; right: 16px; bottom: 16px; display: flex; align-items: center; gap: 12px; padding: 7px 10px; border: 1px solid #e1e9e4; border-radius: 10px; color: #849089; background: rgba(255,255,255,.93); font-size: 11px; pointer-events: none; }.zoom-controls { display: inline-flex; align-items: center; gap: 6px; pointer-events: auto; }.zoom-controls button { display: grid; width: 24px; height: 24px; place-items: center; padding: 0; border: 0; border-radius: 6px; color: #687f70; background: #f3f7f4; cursor: pointer; }.zoom-controls b { min-width: 36px; color: #52695b; font-size: 10px; text-align: center; }.evidence-detail { border-left: 1px solid #e5ede7; background: rgba(255,255,255,.94); }.evidence-detail-head { display: flex; align-items: center; justify-content: space-between; padding: 18px 20px; border-bottom: 1px solid #e8efea; color: #294536; font-size: 16px; }.evidence-detail-head button { display: grid; width: 30px; height: 30px; place-items: center; padding: 0; border: 1px solid #dfe9e2; border-radius: 999px; color: #829188; background: #fff; cursor: pointer; }.evidence-detail-empty { display: grid; place-items: center; padding: 100px 34px; text-align: center; }.evidence-detail-empty > span { display: grid; width: 46px; height: 46px; place-items: center; margin-bottom: 18px; border: 1px solid #dfd9f5; border-radius: 999px; color: #7661b7; font-size: 27px; }.evidence-detail-empty strong { color: #395244; font-size: 16px; }.evidence-detail-empty p { margin: 8px 0 0; color: #88968e; font-size: 12px; line-height: 1.6; }.evidence-detail-content { padding: 25px 22px; }.detail-kicker { color: #b8771e; font: 700 10px ui-monospace,monospace; letter-spacing: .1em; }.evidence-detail-content h3 { margin: 10px 0 13px; color: #294536; font-size: 19px; line-height: 1.45; }.detail-type { display: inline-block; padding: 5px 9px; border-radius: 8px; font-size: 11px; font-weight: 650; }.evidence-detail-content dl { margin: 23px 0 0; }.evidence-detail-content dt { margin-top: 13px; color: #94a198; font-size: 11px; }.evidence-detail-content dd { margin: 4px 0 0; color: #526a5b; font-size: 13px; line-height: 1.55; word-break: break-word; }.evidence-data { margin-top: 18px; border: 1px solid #dfe9e2; border-radius: 16px; background: rgba(255,255,255,.78); }.evidence-data > summary { display: flex; justify-content: space-between; padding: 16px 19px; color: #536b5d; cursor: pointer; list-style: none; }.evidence-data > summary::-webkit-details-marker { display: none; }.evidence-data-body { padding: 0 19px 22px; }.evidence-data-body h3 { margin: 20px 0 11px; color: #294536; font-size: 17px; }.evidence-table-scroll { overflow-x: auto; }.evidence-data table { width: 100%; min-width: 760px; border-collapse: collapse; font-size: 12px; }.evidence-data th,.evidence-data td { padding: 11px 12px; border-bottom: 1px solid #e7efe9; text-align: left; vertical-align: top; line-height: 1.55; }.evidence-data th { color: #75877b; background: #f7fbf8; }.evidence-data td { color: #5d7165; }.evidence-data code { padding: 3px 5px; border-radius: 5px; color: #718379; background: #f3f7f4; }.table-type { font-weight: 650; }.details-chevron { width: 9px; height: 9px; border-right: 1.5px solid #8ea095; border-bottom: 1.5px solid #8ea095; transform: rotate(45deg) translateY(-2px); }.evidence-loading { display: grid; min-height: 60vh; place-items: center; align-content: center; gap: 12px; color: #7d9083; }.evidence-loading p { margin: 0; }
@media (max-width: 820px) { .evidence-topbar { padding: 0 20px; }.evidence-nav a:first-child { display: none; }.evidence-page { width: min(100% - 28px, 720px); padding-top: 24px; }.evidence-hero { display: block; padding: 28px 24px; }.evidence-language { margin-top: 20px; }.evidence-workspace-heading { align-items: flex-start; flex-direction: column; }.evidence-counts { width: 100%; }.evidence-toolbar { align-items: stretch; flex-direction: column; }.evidence-search { min-width: 0; }.evidence-graph-grid { grid-template-columns: 1fr; }.evidence-canvas { min-height: 540px; }.evidence-canvas svg { min-height: 540px; }.evidence-detail { min-height: 300px; border-top: 1px solid #e5ede7; border-left: 0; } }
.evidence-detail-content { background: linear-gradient(180deg, rgba(248,251,249,.72), #fff 38%); }.evidence-detail-content h3 { overflow-wrap: anywhere; }.evidence-detail-content dl { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; padding-top: 6px; border-top: 1px solid #e8efea; }.evidence-detail-content dt { margin-top: 14px; }.evidence-detail-content dd { margin-bottom: 2px; padding: 8px 9px; border-radius: 8px; background: #f7faf8; }.evidence-detail-content dt:nth-of-type(odd),.evidence-detail-content dd:nth-of-type(odd) { grid-column: 1 / -1; }.evidence-detail-content dt:nth-of-type(even),.evidence-detail-content dd:nth-of-type(even) { grid-column: 1 / -1; }.evidence-data[open] { box-shadow: 0 14px 30px rgba(53,74,63,.06); }.evidence-data > summary { align-items: center; font-size: 14px; font-weight: 650; background: #fbfdfc; }.evidence-data[open] > summary { border-bottom: 1px solid #e8efea; color: #294536; background: #f5faf6; }.evidence-data > summary::after { content: ""; width: 9px; height: 9px; border-right: 1.5px solid #8ea095; border-bottom: 1.5px solid #8ea095; transform: rotate(45deg) translateY(-2px); transition: transform .2s ease; }.evidence-data[open] > summary::after { transform: rotate(225deg) translate(-1px,-1px); }.evidence-data-body { padding: 4px 22px 28px; }.evidence-data-body h3 { display: flex; align-items: center; justify-content: space-between; margin: 24px 0 12px; padding-bottom: 9px; border-bottom: 1px solid #e8efea; color: #294536; font-size: 17px; }.evidence-data-body h3::after { content: ""; width: 28px; height: 4px; border-radius: 999px; background: var(--theme-color); opacity: .55; }.evidence-table-scroll { border: 1px solid #e3ece5; border-radius: 12px; }.evidence-data table { font-size: 13px; }.evidence-data tbody tr { transition: background .16s ease; }.evidence-data tbody tr:hover { background: #f8fbf9; }.evidence-data th { padding: 13px 12px; font-size: 11px; letter-spacing: .04em; }.evidence-data td { padding: 13px 12px; }.evidence-data td:first-child { white-space: nowrap; }.evidence-data td:nth-child(3) { min-width: 220px; color: #3f594a; font-weight: 600; }.evidence-data code { font-size: 11px; }.table-type { display: inline-flex; padding: 4px 7px; border-radius: 7px; background: color-mix(in srgb, currentColor 9%, #fff); }.evidence-detail-head { background: #fbfdfc; }.evidence-detail-head button:hover { color: var(--theme-color); border-color: var(--theme-color); background: var(--theme-soft); }.evidence-detail-empty { min-height: 340px; padding: 50px 34px; }.evidence-detail-empty > span { background: #faf8ff; }.details-chevron { display: inline-block; }
.evidence-context { margin: 18px 0 26px; border: 1px solid #dfe9e2; border-radius: 16px; background: rgba(255,255,255,.8); box-shadow: 0 12px 28px rgba(53,74,63,.045); }
.evidence-context > summary { display: flex; align-items: center; justify-content: space-between; padding: 16px 19px; color: #536b5d; cursor: pointer; list-style: none; font-size: 14px; font-weight: 650; }
.evidence-context > summary::-webkit-details-marker { display: none; }
.evidence-context[open] > summary { border-bottom: 1px solid #e8efea; color: #294536; background: #f5faf6; }
.evidence-context-body { padding: 18px 20px 22px; }
.evidence-context-body h3 { margin: 0 0 14px; color: #294536; font-size: 20px; }
.evidence-context-cards { display: grid; grid-template-columns: 1.35fr .8fr .8fr; gap: 12px; }
.evidence-context-card { min-height: 86px; padding: 15px 16px; border: 1px solid #e4ece6; border-radius: 12px; background: #fff; }
.evidence-context-card span { display: block; color: #8a998f; font-size: 11px; }
.evidence-context-card strong { display: block; margin-top: 8px; color: #294536; font-size: 20px; line-height: 1.35; overflow-wrap: anywhere; }
.evidence-context-direction { margin: 16px 0 0; padding: 13px 15px; border-left: 3px solid #b8771e; border-radius: 8px; color: #6d7d73; background: #fffaf1; line-height: 1.65; }
.evidence-context-direction strong { color: #866b43; }
.evidence-context-links { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.evidence-context-links a { padding: 7px 10px; border: 1px solid #dfe9e2; border-radius: 999px; color: var(--theme-color); background: #fff; text-decoration: none; transition: border-color .16s ease, background .16s ease, transform .16s ease; }
.evidence-context-links a:hover { border-color: var(--theme-color); background: var(--theme-soft); transform: translateY(-1px); }
@media (max-width: 820px) { .evidence-context-cards { grid-template-columns: 1fr; } }
.evidence-static-view { margin-top: 18px; overflow: hidden; border: 1px solid #dfe9e2; border-radius: 16px; background: rgba(255,255,255,.8); box-shadow: 0 12px 28px rgba(53,74,63,.045); }
.evidence-static-view > summary { display: flex; align-items: center; justify-content: space-between; padding: 16px 19px; color: #536b5d; cursor: pointer; list-style: none; font-size: 14px; font-weight: 650; background: #fbfdfc; }
.evidence-static-view > summary::-webkit-details-marker { display: none; }
.evidence-static-view[open] > summary { border-bottom: 1px solid #e8efea; color: #294536; background: #f5faf6; }
.evidence-feedback { display: flex; align-items: center; gap: 8px; min-height: 42px; padding: 0 18px; border-bottom: 1px solid #e9efeb; color: #3f6953; background: color-mix(in srgb, var(--theme-soft) 58%, #fff); font-size: 12px; font-weight: 650; animation: evidence-feedback-in .18s ease-out; }
.evidence-feedback svg { color: var(--theme-color); }
@keyframes evidence-feedback-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
</style>
