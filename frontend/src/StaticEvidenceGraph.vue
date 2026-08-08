<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ nodes: any[]; edges: any[] }>();
const nodeMap = computed(() => new Map(props.nodes.map((node) => [String(node.id), node])));
const height = computed(() => Math.max(760, ...props.nodes.map((node) => Number(node.y || 0) + 100)));
</script>

<template>
  <div class="static-graph-shell">
    <svg class="static-graph-svg" :viewBox="`0 0 1120 ${height}`" preserveAspectRatio="xMidYMin meet" role="img" aria-label="静态证据图谱">
      <g v-for="(edge, index) in edges" :key="`static-edge-${index}`" class="static-edge">
        <line v-if="nodeMap.get(String(edge.source)) && nodeMap.get(String(edge.target))" :x1="nodeMap.get(String(edge.source))?.x" :y1="nodeMap.get(String(edge.source))?.y" :x2="nodeMap.get(String(edge.target))?.x" :y2="nodeMap.get(String(edge.target))?.y" />
        <text v-if="nodeMap.get(String(edge.source)) && nodeMap.get(String(edge.target))" :x="((nodeMap.get(String(edge.source))?.x || 0) + (nodeMap.get(String(edge.target))?.x || 0)) / 2" :y="((nodeMap.get(String(edge.source))?.y || 0) + (nodeMap.get(String(edge.target))?.y || 0)) / 2 - 6">{{ edge.predicate }}</text>
      </g>
      <g v-for="node in nodes" :key="`static-node-${node.id}`" class="static-node" :class="`static-node-${node.type || 'other'}`">
        <circle :cx="node.x" :cy="node.y" :r="Math.max(18, Number(node.visualSize || 32) / 2)" />
        <text :x="node.x" :y="Number(node.y || 0) + Math.max(31, Number(node.visualSize || 32) / 2 + 16)" text-anchor="middle">{{ node.label || node.full_label || node.id }}</text>
        <title>{{ node.full_label || node.label || node.id }} | {{ node.type }} | {{ node.status }}</title>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.static-graph-shell { overflow: auto; border-top: 1px solid #e8efea; background: #fbfdfc; }
.static-graph-svg { display: block; min-width: 980px; min-height: 620px; padding: 18px; }
.static-edge line { stroke: #c5d0cb; stroke-width: 1.5; opacity: .72; }
.static-edge text { fill: #91a097; font-size: 9px; }
.static-node circle { stroke: #fff; stroke-width: 3; filter: drop-shadow(0 4px 7px rgba(40,61,49,.1)); }
.static-node text { fill: #53695b; font-size: 10px; font-weight: 600; }
.static-node-germplasm circle { fill: #238b72; }
.static-node-trait circle { fill: #bd7a1d; }
.static-node-gene_qtl_marker circle { fill: #7661b7; }
.static-node-environment_protocol circle { fill: #d4773e; }
.static-node-rag_evidence circle { fill: #518ba0; }
.static-node-risk circle { fill: #c14d4d; }
.static-node-other circle { fill: #8b96a0; }
</style>
