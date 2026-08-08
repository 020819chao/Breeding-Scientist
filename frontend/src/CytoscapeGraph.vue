<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

declare global {
  interface Window {
    cytoscape?: any;
  }
}

const props = defineProps<{
  elements: any[];
  allElements?: any[];
  showIsolatedLabels?: boolean;
  selected: { kind: "node" | "edge"; data: any } | null;
  fitVersion: number;
  layoutVersion: number;
}>();

const emit = defineEmits<{
  select: [value: { kind: "node" | "edge"; data: any }];
  clear: [];
}>();

const container = ref<HTMLElement | null>(null);
const loading = ref(true);
const unavailable = ref(false);
let cy: any = null;
let scriptPromise: Promise<void> | null = null;

const typeColors: Record<string, string> = {
  germplasm: "#238b72",
  trait: "#bd7a1d",
  gene_qtl_marker: "#7661b7",
  environment_protocol: "#d4773e",
  rag_evidence: "#518ba0",
  risk: "#c14d4d",
  other: "#8b96a0",
};

function loadCytoscape() {
  if (window.cytoscape) return Promise.resolve();
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://unpkg.com/cytoscape@3.30.4/dist/cytoscape.min.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Cytoscape failed to load"));
    document.head.appendChild(script);
  });
  return scriptPromise;
}

function runLayout() {
  if (!cy || !cy.nodes().length) return;
  const visibleNodes = cy.nodes().filter((node: any) => node.visible());
  const visibleEdges = cy.edges().filter((edge: any) => edge.visible());
  if (!visibleNodes.length) return;
  visibleNodes.union(visibleEdges).layout({
    name: visibleEdges.length ? "cose" : "grid",
    animate: false,
    fit: true,
    padding: 54,
    avoidOverlap: true,
    nodeDimensionsIncludeLabels: true,
    nodeRepulsion: 7200,
    idealEdgeLength: 105,
    edgeElasticity: 0.25,
    componentSpacing: 90,
    nodeOverlap: 16,
    gravity: 1.1,
    numIter: 650,
    rows: Math.max(1, Math.ceil(Math.sqrt(visibleNodes.length))),
  }).run();
}

function syncVisuals() {
  if (!cy) return;
  const sourceElements = props.allElements?.length ? props.allElements : props.elements;
  const fullDegrees = new Map<string, number>();
  sourceElements.forEach((element: any) => {
    if (element.group !== "edges") return;
    const source = String(element.data?.source || "");
    const target = String(element.data?.target || "");
    if (source) fullDegrees.set(source, (fullDegrees.get(source) || 0) + 1);
    if (target) fullDegrees.set(target, (fullDegrees.get(target) || 0) + 1);
  });
  cy.nodes().forEach((node: any) => {
    const degree = fullDegrees.get(String(node.id())) || 0;
    const showIsolated = Boolean(props.showIsolatedLabels) && degree === 0;
    const size = degree === 0 ? (showIsolated ? 30 : 14) : Math.min(62, 34 + Math.min(10, degree) * 2.2);
    node.data("visualSize", size);
    node.toggleClass("is-isolated", degree === 0 && !showIsolated);
    node.style({
      "background-color": degree === 0 && !showIsolated ? "#c7d2cc" : (typeColors[node.data("type")] || typeColors.other),
      width: size,
      height: size,
      label: degree === 0 && !showIsolated ? "" : "data(label)",
    });
  });
}

function syncSelection() {
  if (!cy) return;
  cy.elements().removeClass("is-focused is-related is-faded");
  const selected = props.selected;
  if (!selected) return;
  const target = selected.kind === "node"
    ? cy.getElementById(String(selected.data.id))
    : cy.edges().filter((edge: any) => edge.data("source") === String(selected.data.source) && edge.data("target") === String(selected.data.target)).first();
  if (!target || !target.length) return;
  const related = selected.kind === "node" ? target.closedNeighborhood() : target.union(target.connectedNodes());
  cy.elements().addClass("is-faded");
  related.removeClass("is-faded").addClass("is-related");
  target.removeClass("is-faded").addClass("is-focused");
}

function syncGraph(shouldLayout = true) {
  if (!cy) return;
  cy.elements().remove();
  cy.add(props.elements);
  syncVisuals();
  if (shouldLayout) runLayout();
  syncSelection();
}

async function init() {
  try {
    await loadCytoscape();
    if (!container.value || !window.cytoscape) throw new Error("Cytoscape is unavailable");
    cy = window.cytoscape({
      container: container.value,
      minZoom: 0.18,
      maxZoom: 3,
      wheelSensitivity: 0.16,
      style: [
        { selector: "node", style: { "background-color": "#8b96a0", "border-width": 2, "border-color": "#fff", label: "data(label)", color: "#405248", "font-size": 10, "font-weight": 600, "text-wrap": "wrap", "text-max-width": 128, "text-valign": "bottom", "text-margin-y": 9, width: "data(visualSize)", height: "data(visualSize)", "text-opacity": 0.9 } },
        { selector: "edge", style: { width: 1.1, "line-color": "#c5d0cb", "target-arrow-color": "#c5d0cb", "target-arrow-shape": "triangle", "curve-style": "bezier", label: "", opacity: 0.7 } },
        { selector: "node.is-isolated", style: { "background-color": "#c7d2cc", "border-color": "#eef3ef", "border-width": 1, label: "", width: 14, height: 14 } },
        { selector: "edge.is-focused", style: { width: 3, "line-color": "#bd7a1d", "target-arrow-color": "#bd7a1d", label: "data(label)", opacity: 1 } },
        { selector: "edge.is-related", style: { width: 2, "line-color": "#86a89b", "target-arrow-color": "#86a89b", opacity: 1 } },
        { selector: ".is-faded", style: { opacity: 0.12, "text-opacity": 0.08 } },
        { selector: "node.is-related", style: { "border-color": "#fff", "border-width": 3 } },
        { selector: "node.is-focused", style: { "border-color": "#bd7a1d", "border-width": 5, "text-opacity": 1 } },
      ],
    });
    cy.on("tap", "node, edge", (event: any) => {
      emit("select", { kind: event.target.group() === "nodes" ? "node" : "edge", data: event.target.data() });
    });
    cy.on("tap", (event: any) => { if (event.target === cy) emit("clear"); });
    syncGraph(true);
    loading.value = false;
  } catch (_error) {
    unavailable.value = true;
    loading.value = false;
  }
}

function fit() { if (cy) cy.fit(cy.elements().filter((element: any) => element.visible()), 48); }

watch(() => [props.elements, props.allElements], () => syncGraph(true), { deep: true });
watch(() => props.selected, syncSelection, { deep: true });
watch(() => props.fitVersion, fit);
watch(() => props.layoutVersion, runLayout);
onMounted(init);
onBeforeUnmount(() => { if (cy) cy.destroy(); cy = null; });
</script>

<template>
  <div class="cytoscape-stage">
    <div ref="container" class="cytoscape-graph-vue" role="img" aria-label="动态证据图谱"></div>
    <div v-if="loading" class="cytoscape-state">正在加载动态图谱…</div>
    <div v-if="unavailable" class="cytoscape-state cytoscape-state-error">动态图谱组件暂时不可用，请展开下方静态图谱查看。</div>
    <div class="cytoscape-hint">节点和关系可拖动、点击；滚轮缩放</div>
  </div>
</template>

<style scoped>
.cytoscape-stage { position: relative; min-height: 700px; overflow: hidden; background: radial-gradient(circle at 50% 46%, #fff, #f8fbf9 75%); }
.cytoscape-graph-vue { min-height: 700px; width: 100%; }
.cytoscape-state { position: absolute; inset: 0; display: grid; place-items: center; color: #7d9083; font-size: 14px; pointer-events: none; }
.cytoscape-state-error { padding: 24px; color: #9a6b3a; text-align: center; }
.cytoscape-hint { position: absolute; right: 16px; bottom: 16px; padding: 8px 11px; border: 1px solid #e1e9e4; border-radius: 9px; color: #849089; background: rgba(255,255,255,.93); font-size: 11px; pointer-events: none; }
</style>
