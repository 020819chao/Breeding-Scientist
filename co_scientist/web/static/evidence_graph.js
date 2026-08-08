(function () {
    "use strict";

    const TYPE_LABELS = {
        germplasm: "种质材料",
        trait: "目标性状",
        gene_qtl_marker: "基因 / QTL / 标记",
        environment_protocol: "环境 / 验证方案",
        rag_evidence: "资料证据",
        risk: "风险与缺口",
        other: "其他证据",
    };

    const TYPE_COLORS = {
        germplasm: "#238b72",
        trait: "#bd7a1d",
        gene_qtl_marker: "#7661b7",
        environment_protocol: "#d4773e",
        rag_evidence: "#518ba0",
        risk: "#c14d4d",
        other: "#8b96a0",
    };

    function readElements(container) {
        const id = container.getAttribute("data-elements-id");
        const source = id ? document.getElementById(id) : null;
        if (!source) return [];
        try {
            return JSON.parse(source.textContent || "[]");
        } catch (_err) {
            return [];
        }
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function detailRow(label, value, className) {
        if (!value) return "";
        return `<div class="graph-detail-row ${className || ""}"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;
    }

    function detailsHtml(data, group) {
        if (group === "edges") {
            return [
                '<div class="graph-detail-kicker">证据关系</div>',
                `<h3>${escapeHtml(data.predicate || "关联关系")}</h3>`,
                '<dl class="graph-detail-list">',
                detailRow("起点", data.source_label || data.source),
                detailRow("终点", data.target_label || data.target),
                detailRow("证据等级", data.evidence_level),
                detailRow("状态", data.status),
                detailRow("来源", data.provenance),
                "</dl>",
            ].join("");
        }
        const type = TYPE_LABELS[data.type] || data.type || "证据节点";
        return [
            '<div class="graph-detail-kicker">证据节点</div>',
            `<h3>${escapeHtml(data.full_label || data.label || "未命名节点")}</h3>`,
            `<span class="graph-detail-type graph-type-${escapeHtml(data.type || "other")}">${escapeHtml(type)}</span>`,
            '<dl class="graph-detail-list">',
            detailRow("证据等级", data.evidence_level),
            detailRow("状态", data.status),
            "</dl>",
            '<p class="graph-detail-help">该节点连接到当前育种路线的相关证据，可继续查看关联材料和验证记录。</p>',
        ].join("");
    }

    function runLayout(cy) {
        const nodes = cy.nodes().filter((node) => node.visible());
        if (!nodes.length) return;
        const edges = nodes.connectedEdges().filter((edge) => edge.visible());
        const layout = nodes.union(edges).layout({
            name: "cose",
            animate: false,
            fit: true,
            padding: 54,
            avoidOverlap: true,
            nodeDimensionsIncludeLabels: true,
            nodeRepulsion: 7200,
            idealEdgeLength: 105,
            edgeElasticity: 0.25,
            nestingFactor: 1.1,
            gravity: 1.1,
            numIter: 650,
            componentSpacing: 90,
            nodeOverlap: 16,
            randomize: true,
        });
        layout.run();
    }

    function nodeType(node) {
        return node.data("type") || Object.keys(TYPE_COLORS).find((type) => node.hasClass(type)) || "other";
    }

    function applyNodeVisuals(cy, search) {
        cy.nodes().forEach((node) => {
            const type = nodeType(node);
            const degree = node.degree();
            const isMatch = Boolean(search) && node.hasClass("is-search-match");
            const isIsolated = degree === 0;
            node.style({
                "background-color": TYPE_COLORS[type],
                width: isIsolated ? 30 : (isMatch && degree === 0 ? 28 : node.data("visualSize")),
                height: isIsolated ? 30 : (isMatch && degree === 0 ? 28 : node.data("visualSize")),
                label: "data(label)",
            });
        });
    }

    function visibleElements(cy) {
        return cy.elements().filter((element) => element.visible());
    }

    function announce(browser, message) {
        if (!browser) return;
        const feedback = browser.querySelector("[data-cy-feedback]");
        if (!feedback) return;
        feedback.textContent = message;
        feedback.hidden = false;
    }

    function applyVisibility(cy, state, reflow = false) {
        const search = state.search.trim().toLowerCase();
        const typeNodes = cy.nodes().filter((node) => {
            const typeMatch = state.filter === "all" || node.hasClass(state.filter);
            if (!typeMatch) return false;
            return true;
        });
        const matchingNodes = typeNodes.filter((node) => {
            if (!search) return true;
            const haystack = [node.data("label"), node.data("full_label"), node.data("id")]
                .filter(Boolean)
                .join(" ")
                .toLowerCase();
            return haystack.includes(search);
        });
        const visibleNodes = search
            ? matchingNodes.union(matchingNodes.closedNeighborhood().nodes())
            : typeNodes;

        cy.batch(() => {
            cy.nodes().hide();
            cy.nodes().removeClass("is-search-match");
            visibleNodes.show();
            matchingNodes.addClass("is-search-match");
            cy.edges().hide();
            cy.edges().filter((edge) => edge.source().visible() && edge.target().visible()).show();
        });
        applyNodeVisuals(cy, search);
        const visible = visibleElements(cy);
        if (visible.length) {
            if (reflow) runLayout(cy);
            else cy.fit(visible, 48);
        }
    }

    function clearFocus(cy) {
        cy.elements().removeClass("is-faded is-related is-focused");
    }

    function focusTarget(cy, target) {
        clearFocus(cy);
        const related = target.group() === "nodes"
            ? target.closedNeighborhood()
            : target.union(target.connectedNodes());
        cy.elements().addClass("is-faded");
        related.removeClass("is-faded").addClass("is-related");
        target.removeClass("is-faded").addClass("is-focused");
    }

    function defaultDetails(detailsContent) {
        if (!detailsContent) return;
        detailsContent.innerHTML = '<div class="graph-detail-empty"><span class="graph-detail-empty-icon">＋</span><strong>选择一个节点</strong><p>点击图谱中的节点或关系，查看它对当前育种路线的意义。</p></div>';
    }

    function initGraph(container) {
        if (!window.cytoscape) {
            container.innerHTML = '<p class="muted">图谱组件暂时不可用，请使用下方备用视图。</p>';
            return;
        }
        const elements = readElements(container);
        const browser = container.closest(".graph-browser");
        const details = browser ? browser.querySelector("[data-cy-details]") : null;
        const detailsContent = details ? details.querySelector("[data-cy-detail-content]") : null;
        let selectedTarget = null;
        if (!elements.length) {
            container.innerHTML = '<p class="muted">当前还没有可展示的证据关系。</p>';
            return;
        }

        const cy = window.cytoscape({
            container,
            elements,
            minZoom: 0.18,
            maxZoom: 3,
            wheelSensitivity: 0.16,
            style: [
                {
                    selector: "node",
                    style: {
                        "background-color": "#8b96a0",
                        "border-width": 2,
                        "border-color": "#ffffff",
                        label: "data(label)",
                        color: "#405248",
                        "font-size": 10,
                        "font-weight": 600,
                        "text-wrap": "wrap",
                        "text-max-width": 128,
                        "text-valign": "bottom",
                        "text-margin-y": 9,
                        width: "data(visualSize)",
                        height: "data(visualSize)",
                        "text-opacity": 0.9,
                    },
                },
                { selector: "node.germplasm", style: { "background-color": "#238b72" } },
                { selector: "node.trait", style: { "background-color": "#bd7a1d", "border-color": "#fff3d9" } },
                { selector: "node.gene_qtl_marker", style: { "background-color": "#7661b7" } },
                { selector: "node.environment_protocol", style: { "background-color": "#d4773e" } },
                { selector: "node.rag_evidence", style: { "background-color": "#518ba0" } },
                { selector: "node.risk", style: { "background-color": "#c14d4d" } },
                { selector: 'node[type = "germplasm"]', style: { "background-color": "#238b72" } },
                { selector: 'node[type = "trait"]', style: { "background-color": "#bd7a1d", "border-color": "#fff3d9" } },
                { selector: 'node[type = "gene_qtl_marker"]', style: { "background-color": "#7661b7" } },
                { selector: 'node[type = "environment_protocol"]', style: { "background-color": "#d4773e" } },
                { selector: 'node[type = "rag_evidence"]', style: { "background-color": "#518ba0" } },
                { selector: 'node[type = "risk"]', style: { "background-color": "#c14d4d" } },
                {
                    selector: "node.is-isolated",
                    style: {
                        "background-color": "#c7d2cc",
                        "border-color": "#eef3ef",
                        "border-width": 1,
                        label: "",
                        width: 14,
                        height: 14,
                        "text-opacity": 0.25,
                    },
                },
                {
                    selector: "node.is-isolated.is-search-match",
                    style: {
                        "background-color": "#238b72",
                        "border-color": "#ffffff",
                        "border-width": 3,
                        label: "data(label)",
                        width: 28,
                        height: 28,
                        "text-opacity": 1,
                    },
                },
                {
                    selector: "edge",
                    style: {
                        width: 1.1,
                        "line-color": "#c5d0cb",
                        "target-arrow-color": "#c5d0cb",
                        "target-arrow-shape": "triangle",
                        "curve-style": "bezier",
                        label: "",
                        opacity: 0.7,
                    },
                },
                { selector: "edge.is-focused", style: { width: 3, "line-color": "#bd7a1d", "target-arrow-color": "#bd7a1d", label: "data(label)", opacity: 1 } },
                { selector: "edge.is-related", style: { width: 2, "line-color": "#86a89b", "target-arrow-color": "#86a89b", opacity: 1 } },
                { selector: ".is-faded", style: { opacity: 0.12, "text-opacity": 0.08 } },
                { selector: "node.is-related", style: { "border-color": "#ffffff", "border-width": 3 } },
                { selector: "node.is-focused", style: { "border-color": "#bd7a1d", "border-width": 5, "text-opacity": 1 } },
            ],
        });

        cy.nodes().forEach((node) => {
            const degree = node.degree();
            node.data("visualSize", degree === 0 ? 14 : Math.min(62, 34 + Math.min(10, degree) * 2.2));
            if (degree === 0) node.addClass("is-isolated");
        });
        applyNodeVisuals(cy, "");
        runLayout(cy);

        const state = { filter: "all", search: "" };
        const showDetails = (target) => {
            selectedTarget = target;
            if (detailsContent) detailsContent.innerHTML = detailsHtml(target.data(), target.group());
            focusTarget(cy, target);
        };

        cy.on("tap", "node, edge", (event) => showDetails(event.target));
        cy.on("tap", (event) => {
            if (event.target !== cy) return;
            clearFocus(cy);
            defaultDetails(detailsContent);
        });

        if (browser) {
            const search = browser.querySelector("[data-cy-search]");
            if (search) {
                search.addEventListener("input", () => {
                    state.search = search.value || "";
                    applyVisibility(cy, state);
                    if (selectedTarget && !selectedTarget.visible()) {
                        selectedTarget = null;
                        clearFocus(cy);
                        defaultDetails(detailsContent);
                    }
                });
            }
            browser.querySelectorAll("[data-cy-filter]").forEach((button) => {
                button.addEventListener("click", () => {
                    state.filter = button.getAttribute("data-cy-filter") || "all";
                    browser.querySelectorAll("[data-cy-filter]").forEach((item) => item.classList.remove("is-active"));
                    button.classList.add("is-active");
                    applyVisibility(cy, state, true);
                    if (selectedTarget && !selectedTarget.visible()) {
                        selectedTarget = null;
                        clearFocus(cy);
                        defaultDetails(detailsContent);
                    }
                    announce(browser, `已切换到“${button.textContent.trim()}”，当前显示 ${cy.nodes().filter((node) => node.visible()).length} 个节点、${cy.edges().filter((edge) => edge.visible()).length} 条关系。`);
                });
            });
            browser.querySelectorAll("[data-cy-action]").forEach((button) => {
                button.addEventListener("click", () => {
                    const action = button.getAttribute("data-cy-action");
                    if (action === "fit") cy.fit(visibleElements(cy), 48);
                    if (action === "fit") announce(browser, `图谱已聚焦到当前显示内容（${cy.nodes().filter((node) => node.visible()).length} 个节点）。`);
                    if (action === "layout") {
                        runLayout(cy);
                        announce(browser, "当前图谱已重新布局。");
                    }
                    if (action === "clear") {
                        const hadSelection = Boolean(selectedTarget);
                        selectedTarget = null;
                        clearFocus(cy);
                        defaultDetails(detailsContent);
                        announce(browser, hadSelection ? "已清除当前选择。" : "当前没有选中的节点或关系。");
                    }
                });
            });
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-cytoscape-graph]").forEach(initGraph);
    });
})();
