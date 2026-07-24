import SwiftUI

// MARK: - Layout constants
private let nodeW:    CGFloat = 198
private let nodeH:    CGFloat = 63
private let hGap:     CGFloat = 56
private let vGap:     CGFloat = 88
private let padding:  CGFloat = 48
private let gridSize: CGFloat = 20

// MARK: - Persistent position codec

private struct CodablePoint: Codable {
    let x: Double, y: Double
    init(_ p: CGPoint) { x = p.x; y = p.y }
    var cgPoint: CGPoint { CGPoint(x: x, y: y) }
}

// MARK: - Drag mode

private enum DragMode {
    case undetermined, pan, node(String), group(String, [String: CGPoint])
}

// MARK: - Node action

enum NodeAction {
    case include   // add step to includedSteps (require in journeys)
    case exclude   // add step to excludedSteps (exclude from journeys)
}

// MARK: - Graph layout engine

struct GraphLayout {
    let nodePositions: [String: CGPoint]
    let canvasSize: CGSize

    static func compute(graph: ProcessGraph, nodeHeight: CGFloat = nodeH, optimised: Bool = true) -> GraphLayout {
        let nodes = Set(graph.steps.keys)
        guard !nodes.isEmpty else {
            return GraphLayout(nodePositions: [:], canvasSize: CGSize(width: 400, height: 300))
        }

        let allEdges = graph.transitions.filter { $0.fromStep != $0.toStep }

        // Build a cycle-free DAG by greedily adding edges in descending frequency order.
        // Back-edges (rare loops) are skipped for layout but still drawn visually.
        var dagSucc: [String: [String]] = Dictionary(uniqueKeysWithValues: nodes.map { ($0, []) })

        func wouldCreateCycle(_ u: String, _ v: String) -> Bool {
            var visited = Set<String>()
            var stack = [v]
            while let top = stack.popLast() {
                if top == u { return true }
                if visited.insert(top).inserted {
                    for s in dagSucc[top, default: []] { stack.append(s) }
                }
            }
            return false
        }

        for edge in allEdges.sorted(by: { $0.occurrences > $1.occurrences }) {
            if !wouldCreateCycle(edge.fromStep, edge.toStep) {
                dagSucc[edge.fromStep, default: []].append(edge.toStep)
            }
        }

        // Longest-path layer assignment via Kahn's topological sort on the DAG
        var inDeg: [String: Int] = Dictionary(uniqueKeysWithValues: nodes.map { ($0, 0) })
        for (_, succs) in dagSucc { for v in succs { inDeg[v, default: 0] += 1 } }

        var layers: [String: Int] = [:]
        var queue: [String] = nodes.filter { (inDeg[$0] ?? 0) == 0 }.sorted()
        for n in queue { layers[n] = 0 }

        var qi = 0
        while qi < queue.count {
            let u = queue[qi]; qi += 1
            let ul = layers[u] ?? 0
            for v in dagSucc[u, default: []] {
                let c = ul + 1
                if c > (layers[v] ?? 0) { layers[v] = c }
                inDeg[v, default: 0] -= 1
                if inDeg[v] == 0 { queue.append(v) }
            }
        }

        // Nodes not reachable via topological sort (isolated or in unresolved sub-cycles)
        for n in nodes where layers[n] == nil { layers[n] = 0 }

        // Group nodes by layer; alphabetical sort gives a stable, deterministic baseline.
        var layerGroups: [Int: [String]] = [:]
        for (node, layer) in layers { layerGroups[layer, default: []].append(node) }
        for key in layerGroups.keys { layerGroups[key]?.sort() }

        // Build reverse adjacency (predecessors) for the crossing-minimisation pass.
        var dagPred: [String: [String]] = Dictionary(uniqueKeysWithValues: nodes.map { ($0, []) })
        for (u, succs) in dagSucc { for v in succs { dagPred[v, default: []].append(u) } }

        // Crossing minimisation: reorder nodes within each layer using the barycenter
        // heuristic so that connected nodes land near each other, dramatically reducing
        // edge crossings in dense graphs (Sugiyama framework, phase 3).
        if optimised {
            layerGroups = applyCrossingMin(layerGroups: layerGroups,
                                           dagSucc: dagSucc, dagPred: dagPred,
                                           layers: layers)
        }

        let maxLayer = layers.values.max() ?? 0
        let maxCount = layerGroups.values.map(\.count).max() ?? 1

        let canvasW = CGFloat(maxCount) * nodeW + CGFloat(max(maxCount - 1, 0)) * hGap + 2 * padding
        let canvasH = CGFloat(maxLayer + 1) * nodeHeight + CGFloat(maxLayer) * vGap + 2 * padding

        // Position each node centred within its layer row
        var positions: [String: CGPoint] = [:]
        for (layer, nodesInLayer) in layerGroups {
            let y = padding + CGFloat(layer) * (nodeHeight + vGap) + nodeHeight / 2
            let groupW = CGFloat(nodesInLayer.count) * nodeW + CGFloat(max(nodesInLayer.count - 1, 0)) * hGap
            let startX = (canvasW - groupW) / 2
            for (i, node) in nodesInLayer.enumerated() {
                let x = startX + CGFloat(i) * (nodeW + hGap) + nodeW / 2
                positions[node] = CGPoint(x: x, y: y)
            }
        }

        // Resolve group bounding-box overlaps by nudging groups apart
        resolveGroupOverlaps(positions: &positions, graph: graph, nodeH: nodeHeight)

        // Expand canvas to fit any repositioned nodes
        let allX = positions.values.map(\.x)
        let allY = positions.values.map(\.y)
        let finalW = max(canvasW, (allX.max() ?? 0) + nodeW / 2 + padding)
        let finalH = max(canvasH, (allY.max() ?? 0) + nodeHeight / 2 + padding)

        return GraphLayout(
            nodePositions: positions,
            canvasSize:    CGSize(width: finalW, height: finalH)
        )
    }

    // Sugiyama barycenter heuristic — 3 alternating top-down/bottom-up sweeps.
    // Each node is sorted by the average normalised position of its neighbours in
    // the adjacent layer; stable across equal barycenters (preserves prior order).
    private static func applyCrossingMin(layerGroups: [Int: [String]],
                                         dagSucc: [String: [String]],
                                         dagPred: [String: [String]],
                                         layers:  [String: Int],
                                         passes:  Int = 3) -> [Int: [String]] {
        var lg = layerGroups
        let sortedKeys = lg.keys.sorted()
        guard sortedKeys.count > 1 else { return lg }

        // Normalised position of `node` within its current layer (0 … 1).
        func virtualPos(_ node: String) -> Double {
            let l = layers[node] ?? 0
            guard let vs = lg[l], !vs.isEmpty else { return 0.5 }
            let idx = vs.firstIndex(of: node) ?? 0
            return vs.count > 1 ? Double(idx) / Double(vs.count - 1) : 0.5
        }

        // Average virtual position of a node's predecessors (top-down) or successors
        // (bottom-up).  Falls back to the node's own position when it has no relevant
        // neighbours, preserving the existing order for isolated nodes.
        func barycenter(_ node: String, predecessors: Bool) -> Double {
            let nl = layers[node] ?? 0
            let nbrs = predecessors ? dagPred[node, default: []] : dagSucc[node, default: []]
            var sum = 0.0; var cnt = 0
            for v in nbrs {
                let vl = layers[v] ?? 0
                guard predecessors ? vl < nl : vl > nl else { continue }
                sum += virtualPos(v); cnt += 1
            }
            return cnt > 0 ? sum / Double(cnt) : virtualPos(node)
        }

        for _ in 0..<passes {
            // Top-down: each layer is sorted relative to the layer above it.
            for l in sortedKeys.dropFirst() {
                if let nodes = lg[l] {
                    lg[l] = nodes.sorted { barycenter($0, predecessors: true) < barycenter($1, predecessors: true) }
                }
            }
            // Bottom-up: each layer is sorted relative to the layer below it.
            for l in sortedKeys.dropLast().reversed() {
                if let nodes = lg[l] {
                    lg[l] = nodes.sorted { barycenter($0, predecessors: false) < barycenter($1, predecessors: false) }
                }
            }
        }
        return lg
    }

    // Iteratively push overlapping BELONGS_TO group boxes apart until they all have a
    // minimum gap between them. Mirrors the padding used in FlowChartView.groupRects.
    private static func resolveGroupOverlaps(positions: inout [String: CGPoint],
                                             graph: ProcessGraph, nodeH: CGFloat) {
        let pad:      CGFloat = 20   // matches FlowChartView.groupRects
        let labelPad: CGFloat = 18   // extra top space for group label
        let minGap:   CGFloat = 24   // required clear space between group boxes

        var groups: [String: [String]] = [:]
        for (name, step) in graph.steps {
            guard let g = step.belongsTo, !g.isEmpty else { continue }
            groups[g, default: []].append(name)
        }
        guard groups.count > 1 else { return }

        let groupNames = groups.keys.sorted()

        func rect(for nodeList: [String]) -> CGRect {
            let xs = nodeList.compactMap { positions[$0]?.x }
            let ys = nodeList.compactMap { positions[$0]?.y }
            guard !xs.isEmpty else { return .zero }
            let minX = xs.min()! - nodeW / 2 - pad
            let minY = ys.min()! - nodeH / 2 - pad - labelPad
            let maxX = xs.max()! + nodeW / 2 + pad
            let maxY = ys.max()! + nodeH / 2 + pad
            return CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)
        }

        for _ in 0..<30 {
            var anyOverlap = false
            for i in 0..<groupNames.count {
                for j in (i + 1)..<groupNames.count {
                    let nA = groupNames[i], nB = groupNames[j]
                    guard let nodesA = groups[nA], let nodesB = groups[nB] else { continue }

                    let rA = rect(for: nodesA)
                    let rB = rect(for: nodesB)
                    let expanded = rA.insetBy(dx: -minGap / 2, dy: -minGap / 2)
                    guard expanded.intersects(rB.insetBy(dx: -minGap / 2, dy: -minGap / 2)) else { continue }
                    anyOverlap = true

                    let overlapX = min(rA.maxX, rB.maxX) - max(rA.minX, rB.minX) + minGap
                    let overlapY = min(rA.maxY, rB.maxY) - max(rA.minY, rB.minY) + minGap

                    if overlapX <= overlapY {
                        // Resolve horizontally
                        let shift = overlapX / 2 + 1
                        let aGoesLeft = rA.midX <= rB.midX
                        for n in nodesA { positions[n]?.x += aGoesLeft ? -shift : shift }
                        for n in nodesB { positions[n]?.x += aGoesLeft ?  shift : -shift }
                    } else {
                        // Resolve vertically
                        let shift = overlapY / 2 + 1
                        let aGoesUp = rA.midY <= rB.midY
                        for n in nodesA { positions[n]?.y += aGoesUp ? -shift : shift }
                        for n in nodesB { positions[n]?.y += aGoesUp ?  shift : -shift }
                    }
                }
            }
            if !anyOverlap { break }
        }
    }
}

// MARK: - FlowChartView

struct FlowChartView: View {
    let graph: ProcessGraph
    let projectId: String
    let chartMode: String   // unique identifier included in the UserDefaults key
    let forExport: Bool
    let metric: TransitionMetric
    let isLoading: Bool     // true while parent is reloading — used to snapshot positions before graph changes
    let syncState: ABSyncState?   // when non-nil, zoom/pan/nodes are shared with the other A/B panel
    let skipInitialFit: Bool      // true when seeded from master — preserve master's zoom/pan
    let onNodeAction: ((String, NodeAction) -> Void)?
    let normValues:       [String: Double]?                      // if set, display norm badges on edges
    let normMetric:       TransitionMetric                       // metric the norms apply to
    let showCompliance:   Bool                                   // color edges by actual-vs-norm compliance
    let normIsMinimum:    Bool                                   // true = norm is a floor (actual must be ≥), false = ceiling
    let onEdgeTap:     ((ProcessTransition, CGPoint) -> Void)?  // called in norm-edit mode
    let notes:            [ProcessNote]?
    let ownNoteNodeNames: Set<String>?           // node names where the current user has a note
    let ownNoteEdgeIds:   Set<String>?           // edge IDs (fromStep->toStep) where the current user has a note
    let onNodeNote:       ((String) -> Void)?
    let onEdgeNote:       ((ProcessTransition) -> Void)?

    @AppStorage("processmap.showGrouping")         private var showGrouping         = true
    @AppStorage("processmap.showNodeDescriptions") private var showNodeDescriptions = true
    @AppStorage("graph.startMode")                 private var graphStartMode: GraphStartMode = .expanded
    @AppStorage("graph.optimisedLayout")           private var optimisedLayout      = true
    @AppStorage("graph.edge.colorizeByWeight")                    private var colorizeByWeight    = true
    @AppStorage("graph.edge.colorSchema.Count")    private var edgeSchemaRawCount   = EdgeColorSchema.defaultSchema(for: .count).rawValue
    @AppStorage("graph.edge.colorSchema.Avg Time") private var edgeSchemaRawAvg     = EdgeColorSchema.defaultSchema(for: .avgTime).rawValue
    @AppStorage("graph.edge.colorSchema.Min Time") private var edgeSchemaRawMin     = EdgeColorSchema.defaultSchema(for: .minTime).rawValue
    @AppStorage("graph.edge.colorSchema.Max Time") private var edgeSchemaRawMax     = EdgeColorSchema.defaultSchema(for: .maxTime).rawValue
    @AppStorage("graph.edge.colorSchema.Std Dev")  private var edgeSchemaRawStdDev  = EdgeColorSchema.defaultSchema(for: .stdDev).rawValue

    @State private var zoomScale: CGFloat
    @State private var panOffset: CGSize
    @State private var lastZoom:  CGFloat
    @State private var lastPan:   CGSize
    @State private var nodeOverrides: [String: CGPoint]
    @State private var dragMode: DragMode = .undetermined
    @State private var viewSize: CGSize = .zero
    @State private var transformCanvasSize: CGSize = .zero   // frozen at last fitToView call
    @State private var frozenPositions: [String: CGPoint] = [:]  // snapshot taken when loading begins
    @State private var menuNode: String? = nil
    @State private var menuEdge: ProcessTransition? = nil
    @State private var menuScreenPos: CGPoint = .zero
    @State private var descriptionNode: String? = nil
    @State private var collapsedGroups: Set<String> = []
    // Tracks the projectId for which the initial group-collapse state was last applied,
    // so we re-apply it on project switches but not on every filter-triggered graph reload.
    @State private var groupStateProjectId: String = ""

    init(graph: ProcessGraph, projectId: String, chartMode: String,
         forExport: Bool = false,
         metric: TransitionMetric = .count,
         isLoading: Bool = false,
         syncState: ABSyncState? = nil,
         initialViewState: ABSyncState? = nil,
         skipInitialFit: Bool = false,
         onNodeAction: ((String, NodeAction) -> Void)? = nil,
         normValues: [String: Double]? = nil,
         normMetric: TransitionMetric = .count,
         showCompliance: Bool = false,
         normIsMinimum: Bool = false,
         onEdgeTap: ((ProcessTransition, CGPoint) -> Void)? = nil,
         notes: [ProcessNote]? = nil,
         ownNoteNodeNames: Set<String>? = nil,
         ownNoteEdgeIds: Set<String>? = nil,
         onNodeNote: ((String) -> Void)? = nil,
         onEdgeNote: ((ProcessTransition) -> Void)? = nil) {
        self.graph          = graph
        self.projectId      = projectId
        self.chartMode      = chartMode
        self.forExport      = forExport
        self.metric         = metric
        self.isLoading      = isLoading
        self.syncState      = syncState
        self.skipInitialFit = skipInitialFit
        self.onNodeAction   = onNodeAction
        self.normValues       = normValues
        self.normMetric       = normMetric
        self.showCompliance   = showCompliance
        self.normIsMinimum    = normIsMinimum
        self.onEdgeTap      = onEdgeTap
        self.notes            = notes
        self.ownNoteNodeNames = ownNoteNodeNames
        self.ownNoteEdgeIds   = ownNoteEdgeIds
        self.onNodeNote       = onNodeNote
        self.onEdgeNote       = onEdgeNote
        // Seed zoom/pan from master snapshot if provided
        _zoomScale = State(initialValue: initialViewState?.zoomScale ?? 1.0)
        _panOffset = State(initialValue: initialViewState?.panOffset ?? .zero)
        _lastZoom  = State(initialValue: initialViewState?.lastZoom  ?? 1.0)
        _lastPan   = State(initialValue: initialViewState?.lastPan   ?? .zero)
        // NodeOverrides: prefer master snapshot, then UserDefaults, then empty
        if let seed = initialViewState, !seed.nodeOverrides.isEmpty {
            _nodeOverrides = State(initialValue: seed.nodeOverrides)
        } else {
            let key = "layout_\(projectId)_\(chartMode)"
            if let data    = UserDefaults.standard.data(forKey: key),
               let decoded = try? JSONDecoder().decode([String: CodablePoint].self, from: data) {
                _nodeOverrides = State(initialValue: decoded.mapValues(\.cgPoint))
            } else {
                _nodeOverrides = State(initialValue: [:])
            }
        }
        // Seed transformCanvasSize from master's saved canvas size so B's very first
        // render frame uses the correct centering without waiting for onAppear.
        if skipInitialFit, let s = syncState, s.canvasSize != .zero {
            _transformCanvasSize = State(initialValue: s.canvasSize)
        }
    }

    // MARK: - Sync helpers

    private var activeZoom: CGFloat {
        if let s = syncState { return s.zoomScale }
        return zoomScale
    }
    private var activePan: CGSize {
        if let s = syncState { return s.panOffset }
        return panOffset
    }
    private var activeLastZoom: CGFloat {
        if let s = syncState { return s.lastZoom }
        return lastZoom
    }
    private var activeLastPan: CGSize {
        if let s = syncState { return s.lastPan }
        return lastPan
    }

    private func setZoom(_ val: CGFloat) {
        zoomScale = val; syncState?.zoomScale = val
    }
    private func setPan(_ val: CGSize) {
        panOffset = val; syncState?.panOffset = val
    }
    private func setLastZoom(_ val: CGFloat) {
        lastZoom = val; syncState?.lastZoom = val
    }
    private func setLastPan(_ val: CGSize) {
        lastPan = val; syncState?.lastPan = val
    }

    private var activeNodeOverrides: [String: CGPoint] {
        if let s = syncState { return s.nodeOverrides }
        return nodeOverrides
    }

    private func setNodeOverride(_ name: String, _ pos: CGPoint) {
        nodeOverrides[name] = pos
        syncState?.nodeOverrides[name] = pos
    }

    private func clearAllNodeOverrides() {
        nodeOverrides = [:]
        syncState?.nodeOverrides = [:]
    }

    static func defaultNodeHeight(for graph: ProcessGraph) -> CGFloat {
        graph.steps.values.contains { $0.eventTime != nil } ? 77 : nodeH
    }

    /// Canvas size needed to render the full graph for PDF export.
    /// Merges user-saved node positions (UserDefaults) with the auto-layout so that
    /// any dragged nodes outside the default bounds are still included.
    static func exportCanvasSize(graph: ProcessGraph, projectId: String, chartMode: String) -> CGSize {
        let nh = defaultNodeHeight(for: graph)
        let layout = GraphLayout.compute(graph: graph, nodeHeight: nh)
        var positions = layout.nodePositions

        let key = "layout_\(projectId)_\(chartMode)"
        if let data    = UserDefaults.standard.data(forKey: key),
           let decoded = try? JSONDecoder().decode([String: CodablePoint].self, from: data) {
            for (k, v) in decoded { positions[k] = v.cgPoint }
        }

        guard !positions.isEmpty else { return layout.canvasSize }

        let allX = positions.values.map(\.x)
        let allY = positions.values.map(\.y)
        let pad:        CGFloat = 48   // matches file-level padding constant
        let arrowSpace: CGFloat = 70   // clearance for start/end arrow indicators

        // Full four-sided bounding box.
        // Nodes pushed left/up by group-overlap resolution may fall outside [0,∞),
        // so compute how much the content overshoots the origin and add it to the size.
        let leftEdge   = allX.min()! - nodeW / 2 - pad
        let topEdge    = allY.min()! - nh    / 2 - pad - arrowSpace  // start arrows above
        let rightEdge  = allX.max()! + nodeW / 2 + pad
        let bottomEdge = allY.max()! + nh    / 2 + pad + arrowSpace  // end arrows below

        let extraLeft = max(0, -leftEdge)
        let extraTop  = max(0, -topEdge)

        let w = (rightEdge + extraLeft).rounded(.up)
        let h = (bottomEdge + extraTop).rounded(.up)

        return CGSize(width:  max(layout.canvasSize.width,  w),
                      height: max(layout.canvasSize.height, h))
    }

    /// Translation needed in the export Canvas so no content falls outside the origin.
    private var exportOffset: CGPoint {
        let positions = effectivePositions
        guard !positions.isEmpty else { return .zero }
        let allX = positions.values.map(\.x)
        let allY = positions.values.map(\.y)
        let nh = effectiveNodeH
        let pad: CGFloat = 48
        let arrowSpace: CGFloat = 70
        let leftEdge = allX.min()! - nodeW / 2 - pad
        let topEdge  = allY.min()! - nh    / 2 - pad - arrowSpace
        return CGPoint(x: max(0, -leftEdge), y: max(0, -topEdge))
    }

    private var hasTimedSteps: Bool { graph.steps.values.contains { $0.eventTime != nil } }
    private var effectiveNodeH: CGFloat { hasTimedSteps ? 70 : nodeH }

    private var layout: GraphLayout { GraphLayout.compute(graph: graph, nodeHeight: effectiveNodeH, optimised: optimisedLayout) }

    // Nodes that have no incoming transitions from other nodes — process entry points.
    private var startNodeNames: Set<String> {
        let trans = resolvedTransitions
        let targets = Set(trans.filter { $0.fromStep != $0.toStep }.map(\.toStep))
        return Set(resolvedSteps.keys.filter { !targets.contains($0) })
    }

    // Nodes that have no outgoing transitions to other nodes — process exit points.
    private var endNodeNames: Set<String> {
        let trans = resolvedTransitions
        let sources = Set(trans.filter { $0.fromStep != $0.toStep }.map(\.fromStep))
        return Set(resolvedSteps.keys.filter { !sources.contains($0) })
    }

    // Merge auto-computed positions with frozen snapshot and user-dragged overrides,
    // then apply group collapsing (collapsed groups → single virtual proxy node).
    // Priority: nodeOverrides > frozenPositions > layout, then collapse resolution.
    private var effectivePositions: [String: CGPoint] {
        var pos = layout.nodePositions
        for (k, v) in frozenPositions    { pos[k] = v }
        for (k, v) in activeNodeOverrides { pos[k] = v }
        return resolvedPositions(base: pos)
    }

    var body: some View {
        if forExport {
            // ImageRenderer does not reliably deliver the correct size to GeometryReader,
            // so the interactive pan/zoom transform would be miscalculated.
            // For export we skip GeometryReader entirely and draw at natural canvas
            // coordinates. An offset translation is applied so content that would fall
            // outside the origin (nodes pushed left/up by group-overlap resolution,
            // or start arrows reaching above Y=0) is shifted back into view.
            Canvas { context, _ in
                var ctx = context
                let off = exportOffset
                if off.x != 0 || off.y != 0 {
                    ctx.translateBy(x: off.x, y: off.y)
                }
                drawContent(ctx: ctx, positions: effectivePositions)
            }
        } else {
            GeometryReader { geo in
                Canvas { context, size in
                    var ctx = context
                    ctx.translateBy(x: size.width / 2 + activePan.width,
                                    y: size.height / 2 + activePan.height)
                    ctx.scaleBy(x: activeZoom, y: activeZoom)
                    let tcs = transformCanvasSize
                    ctx.translateBy(x: -tcs.width  / 2,
                                    y: -tcs.height / 2)

                    let positions = effectivePositions
                    let dragging: String? = {
                        if case .node(let n) = dragMode { return n } else { return nil }
                    }()
                    let lifted: Set<String> = {
                        if case .group(let g, _) = dragMode { return Set(nodesInGroup(g)) }
                        return []
                    }()
                    drawContent(ctx: ctx, positions: positions,
                                draggingName: dragging, liftedGroup: lifted)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
                .gesture(zoomGesture)
                .simultaneousGesture(mainDragGesture)
                .onTapGesture(count: 2) {
                    menuNode = nil
                    menuEdge = nil
                    withAnimation(.spring(duration: 0.4)) {
                        setZoom(1.0); setLastZoom(1.0)
                        setPan(.zero); setLastPan(.zero)
                    }
                }
                .simultaneousGesture(
                    DragGesture(minimumDistance: 0)
                        .onEnded { value in
                            guard hypot(value.translation.width, value.translation.height) < 4 else { return }
                            let cp = screenToCanvas(value.startLocation)
                            // Group +/- badge tap — toggle collapse, always active when grouping shown
                            if showGrouping, let groupName = groupBadgeAt(cp) {
                                if collapsedGroups.contains(groupName) {
                                    collapsedGroups.remove(groupName)
                                } else {
                                    collapsedGroups.insert(groupName)
                                }
                                return
                            }
                            guard onNodeAction != nil || onEdgeTap != nil || onEdgeNote != nil else { return }
                            // Skip context menu for virtual group proxy nodes
                            if let node = nodeAt(cp), onNodeAction != nil,
                               isVirtualGroupNode(node) == nil {
                                menuNode = node
                                menuEdge = nil
                                menuScreenPos = value.startLocation
                            } else if let transition = edgeAt(cp), let onEdgeTap {
                                menuNode = nil
                                menuEdge = nil
                                onEdgeTap(transition, value.startLocation)
                            } else if let transition = edgeAt(cp), onEdgeNote != nil {
                                menuNode = nil
                                menuEdge = transition
                                menuScreenPos = value.startLocation
                            } else {
                                menuNode = nil
                                menuEdge = nil
                            }
                        }
                )
                .onAppear {
                    viewSize = geo.size
                    // Apply user's preferred initial group collapse state.
                    applyInitialGroupState()
                    groupStateProjectId = projectId
                    // Push persisted node positions into a fresh syncState so the AB
                    // view inherits saved overrides the first time it is opened.
                    if let s = syncState, s.nodeOverrides.isEmpty, !nodeOverrides.isEmpty {
                        s.nodeOverrides = nodeOverrides
                    }
                    if skipInitialFit {
                        // Seeded from master: use master's canvas size so the centering
                        // transform matches A exactly, giving identical initial positions.
                        if transformCanvasSize == .zero {
                            let masterCanvas = syncState?.canvasSize ?? .zero
                            transformCanvasSize = masterCanvas != .zero ? masterCanvas : layout.canvasSize
                        }
                        if frozenPositions.isEmpty { frozenPositions = layout.nodePositions }
                    } else {
                        fitToView(animated: false)
                    }
                }
                .onChange(of: geo.size)        { old, s in
                    viewSize = s
                    // Re-fit whenever the viewport is genuinely resized (startup layout
                    // finalisation, window drag, split-pane move). Guard against layout
                    // noise during data reloads and against the B-panel which inherits
                    // A's viewport and should never auto-reset it.
                    guard !isLoading, !skipInitialFit,
                          max(abs(s.width - old.width), abs(s.height - old.height)) > 2
                    else { return }
                    fitToView(animated: false)
                }
                .onChange(of: projectId)       { _, _ in fitToView() }
                .onChange(of: graph) { _, _ in
                    // Re-apply the start-mode when a new project's graph arrives.
                    // Skip filter-triggered reloads for the same project.
                    guard projectId != groupStateProjectId, !graph.steps.isEmpty else { return }
                    applyInitialGroupState()
                    groupStateProjectId = projectId
                }
                .onChange(of: collapsedGroups) { _, _ in saveCollapsedGroups() }
                // Establish @Observable dependencies on the shared sync state here
                // (in body context) so the Canvas re-draws when the other panel pans,
                // zooms, or moves nodes. Without these, the @escaping Canvas closure
                // doesn't participate in observation tracking and B stays frozen.
                .onChange(of: syncState?.zoomScale)     { _, val in if let val { zoomScale = val; lastZoom = val } }
                .onChange(of: syncState?.panOffset)     { _, val in if let val { panOffset = val; lastPan = val } }
                .onChange(of: syncState?.nodeOverrides) { _, _ in }  // keep empty – avoid UserDefaults pollution
            }
            .overlay(alignment: .bottomTrailing) {
                HStack(alignment: .bottom, spacing: 8) {
                    if colorizeByWeight {
                        colorScaleIndicator
                    }
                    zoomControls
                }
                .padding()
            }
            .overlay {
                if let node = menuNode, onNodeAction != nil {
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture { menuNode = nil }
                    nodeActionMenu(for: node, at: menuScreenPos)
                }
            }
            .overlay {
                if let node = descriptionNode,
                   let desc = graph.steps[node]?.description,
                   !desc.isEmpty, desc != node {
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture { descriptionNode = nil }
                    descriptionCard(node: node, description: desc, at: menuScreenPos)
                }
            }
            .overlay {
                if let edge = menuEdge, onEdgeNote != nil {
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture { menuEdge = nil }
                    edgeActionMenu(for: edge, at: menuScreenPos)
                }
            }
        }
    }

    // MARK: - Shared canvas drawing

    private func drawContent(ctx: GraphicsContext, positions: [String: CGPoint],
                             draggingName: String? = nil, liftedGroup: Set<String> = []) {
        let ctx = ctx
        let nh = effectiveNodeH
        let drawGraph = graphForDrawing   // resolved graph (collapses applied)

        // Groups (drawn first, behind everything)
        if showGrouping {
            for (groupName, rect) in groupRects(positions: positions) {
                let color = groupColor(for: groupName)
                let isCollapsed = collapsedGroups.contains(groupName)
                let path  = Path(roundedRect: rect, cornerRadius: 16)
                ctx.fill(path, with: .color(color.opacity(isCollapsed ? 0.13 : 0.07)))
                ctx.stroke(path, with: .color(color.opacity(0.45)),
                           style: StrokeStyle(lineWidth: isCollapsed ? 2.0 : 1.5,
                                              dash: isCollapsed ? [] : [6, 4]))
                // Group name badge (top-left)
                let badgeH: CGFloat = 20
                let badgeW = max(40, CGFloat(groupName.count) * 9.0 + 24)
                let badgeRect = CGRect(x: rect.minX + 12,
                                       y: rect.minY - badgeH / 2,
                                       width: badgeW, height: badgeH)
                let pill = Path(roundedRect: badgeRect, cornerRadius: badgeH / 2)
                ctx.drawLayer { lCtx in
                    lCtx.addFilter(.shadow(color: .black.opacity(0.35), radius: 4, x: 0, y: 2))
                    lCtx.fill(pill, with: .color(color.opacity(0.90)))
                }
                ctx.stroke(pill, with: .color(.white.opacity(0.80)),
                           style: StrokeStyle(lineWidth: 1.5))
                ctx.draw(
                    Text(groupName)
                        .font(.system(size: 11, weight: .bold, design: .rounded))
                        .foregroundStyle(.white),
                    in: badgeRect.insetBy(dx: 10, dy: 3)
                )
                // Collapse / expand badge (top-right corner)
                let toggleSymbol  = isCollapsed ? "+" : "−"
                // Signal green (+) / signal red (−)
                let toggleBadgeColor: Color = isCollapsed
                    ? Color(red: 0.04, green: 0.72, blue: 0.22)   // signal green
                    : Color(red: 0.86, green: 0.10, blue: 0.10)   // signal red
                let tbRect = groupToggleBadgeBounds(for: rect)
                let tbPill = Path(roundedRect: tbRect, cornerRadius: tbRect.height / 2)
                ctx.drawLayer { lCtx in
                    lCtx.addFilter(.shadow(color: .black.opacity(0.30), radius: 4, x: 0, y: 2))
                    lCtx.fill(tbPill, with: .color(toggleBadgeColor))
                }
                ctx.stroke(tbPill, with: .color(.white.opacity(0.80)),
                           style: StrokeStyle(lineWidth: 1.5))
                ctx.draw(
                    Text(toggleSymbol)
                        .font(.system(size: 14, weight: .bold, design: .rounded))
                        .foregroundStyle(.white),
                    at: CGPoint(x: tbRect.midX, y: tbRect.midY), anchor: .center
                )
            }
        }

        // Edges (behind nodes)
        for transition in drawGraph.transitions {
            drawEdge(ctx: ctx, transition: transition, positions: positions,
                     nodeH: nh, drawGraph: drawGraph)
        }

        // Start/end arrow indicators
        let starts    = startNodeNames
        let ends      = endNodeNames
        let gRects    = showGrouping ? groupRects(positions: positions) : []
        let badgeHalf: CGFloat = 10
        for name in starts {
            guard let pos = positions[name] else { continue }
            let tipY: CGFloat
            // Determine which group this node belongs to (real or virtual)
            let effectiveGroup: String? = isVirtualGroupNode(name) ?? graph.steps[name]?.belongsTo
            if showGrouping,
               let groupName = effectiveGroup, !groupName.isEmpty,
               let gr = gRects.first(where: { $0.name == groupName })?.rect {
                tipY = gr.minY - badgeHalf - 6
            } else {
                tipY = pos.y - nh / 2 - 6
            }
            drawStartArrow(ctx: ctx, at: pos.x, tipY: tipY)
        }
        for name in ends {
            guard let pos = positions[name] else { continue }
            let baseY: CGFloat
            let effectiveGroup: String? = isVirtualGroupNode(name) ?? graph.steps[name]?.belongsTo
            if showGrouping,
               let groupName = effectiveGroup, !groupName.isEmpty,
               let gr = gRects.first(where: { $0.name == groupName })?.rect {
                baseY = gr.maxY + 8
            } else {
                baseY = pos.y + nh / 2 + 8
            }
            drawEndArrow(ctx: ctx, at: pos.x, baseY: baseY)
        }

        // Non-lifted nodes
        for (name, step) in drawGraph.steps
            where name != draggingName && !liftedGroup.contains(name) {
            drawNode(ctx: ctx, name: name, step: step, positions: positions, lifted: false, nodeH: nh)
        }

        // Dragged single node on top with lifted shadow
        if let name = draggingName, let step = drawGraph.steps[name] {
            drawNode(ctx: ctx, name: name, step: step, positions: positions, lifted: true, nodeH: nh)
        }

        // Dragged group nodes on top with lifted shadows
        for name in liftedGroup {
            if let step = drawGraph.steps[name] {
                drawNode(ctx: ctx, name: name, step: step, positions: positions, lifted: true, nodeH: nh)
            }
        }

        // Aggregation legend — shown when at least one group is collapsed
        if !forExport, !collapsedGroups.isEmpty {
            let tcs = transformCanvasSize
            let legendPos = CGPoint(x: tcs.width / 2, y: tcs.height - 14)
            ctx.draw(
                Text("Collapsed groups: connection counts summed · times weighted-averaged")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color.black),
                at: legendPos, anchor: .center
            )
        }
    }

    // MARK: - Persistence

    private var storageKey: String { "layout_\(projectId)_\(chartMode)" }

    private func loadOverrides() {
        guard let data = UserDefaults.standard.data(forKey: storageKey),
              let decoded = try? JSONDecoder().decode([String: CodablePoint].self, from: data)
        else { return }
        nodeOverrides = decoded.mapValues(\.cgPoint)
    }

    private func saveOverrides() {
        let codable = nodeOverrides.mapValues { CodablePoint($0) }
        if let data = try? JSONEncoder().encode(codable) {
            UserDefaults.standard.set(data, forKey: storageKey)
        }
    }

    private func resetLayout() {
        clearAllNodeOverrides()
        UserDefaults.standard.removeObject(forKey: storageKey)
        // Re-run fitToView so frozenPositions is seeded from the fresh auto-layout.
        fitToView(animated: true)
    }

    // MARK: - Coordinate conversion

    private func screenToCanvas(_ pt: CGPoint) -> CGPoint {
        let az = activeZoom
        let ap = activePan
        let tcs = transformCanvasSize
        return CGPoint(
            x: (pt.x - viewSize.width  / 2 - ap.width)  / az + tcs.width  / 2,
            y: (pt.y - viewSize.height / 2 - ap.height) / az + tcs.height / 2
        )
    }

    private func snapped(_ p: CGPoint) -> CGPoint {
        CGPoint(x: (p.x / gridSize).rounded() * gridSize,
                y: (p.y / gridSize).rounded() * gridSize)
    }

    // Scales and centers the canvas so the entire graph fits in the current viewport.
    private func fitToView(animated: Bool = true) {
        guard !forExport, viewSize.width > 0, viewSize.height > 0 else { return }
        // Seed frozen positions from the current layout so subsequent graph changes
        // (filter applies) keep nodes at these positions instead of re-running layout.
        frozenPositions = layout.nodePositions
        let canvas = layout.canvasSize
        guard canvas.width > 0, canvas.height > 0 else { return }
        transformCanvasSize = canvas
        syncState?.canvasSize = canvas
        let scale = min(viewSize.width / canvas.width, viewSize.height / canvas.height) * 0.97
        let clamped = max(0.15, min(5.0, scale))
        if animated {
            withAnimation(.easeOut(duration: 0.35)) {
                setZoom(clamped); setLastZoom(clamped)
                setPan(.zero);    setLastPan(.zero)
            }
        } else {
            setZoom(clamped); setLastZoom(clamped)
            setPan(.zero);    setLastPan(.zero)
        }
    }

    private func nodeAt(_ canvasPoint: CGPoint) -> String? {
        let h = effectiveNodeH
        for (name, pos) in effectivePositions {
            if abs(canvasPoint.x - pos.x) <= nodeW / 2 &&
               abs(canvasPoint.y - pos.y) <= h / 2 {
                return name
            }
        }
        return nil
    }

    private func edgeAt(_ canvasPoint: CGPoint) -> ProcessTransition? {
        let positions = effectivePositions
        let radius: CGFloat = 30
        for transition in resolvedTransitions where transition.fromStep != transition.toStep {
            guard let fromPos = positions[transition.fromStep],
                  let toPos   = positions[transition.toStep] else { continue }
            let mid = CGPoint(x: (fromPos.x + toPos.x) / 2, y: (fromPos.y + toPos.y) / 2)
            if hypot(canvasPoint.x - mid.x, canvasPoint.y - mid.y) < radius {
                return transition
            }
        }
        return nil
    }

    private func groupAt(_ canvasPoint: CGPoint) -> String? {
        for (groupName, rect) in groupRects(positions: effectivePositions) {
            if rect.contains(canvasPoint) { return groupName }
        }
        return nil
    }

    private func nodesInGroup(_ groupName: String) -> [String] {
        graph.steps.compactMap { name, step in
            step.belongsTo == groupName ? name : nil
        }
    }

    // MARK: - Group collapse helpers

    private func collapsedNodeId(for group: String) -> String { "__group__\(group)" }

    private func isVirtualGroupNode(_ name: String) -> String? {
        guard name.hasPrefix("__group__") else { return nil }
        return String(name.dropFirst(9))
    }

    // Maps a step name to its virtual proxy ID if its group is collapsed.
    private func resolvedStep(_ step: String) -> String {
        for group in collapsedGroups where nodesInGroup(group).contains(step) {
            return collapsedNodeId(for: group)
        }
        return step
    }

    // Transitions with collapsed-group edges merged: counts summed, times weighted-averaged.
    private var resolvedTransitions: [ProcessTransition] {
        guard !collapsedGroups.isEmpty else { return graph.transitions }
        struct Acc { var from, to: String; var occ = 0; var wTime: Double = 0; var wCount = 0 }
        var acc: [String: Acc] = [:]
        for t in graph.transitions {
            let f = resolvedStep(t.fromStep), e = resolvedStep(t.toStep)
            guard f != e else { continue }  // drop intra-group edges
            let key = "\(f)->\(e)"
            var a = acc[key] ?? Acc(from: f, to: e)
            a.occ += t.occurrences
            if let at = t.avgSecs { a.wTime += at * Double(t.occurrences); a.wCount += t.occurrences }
            acc[key] = a
        }
        return acc.values.map { a in
            let avg: Double? = a.wCount > 0 ? a.wTime / Double(a.wCount) : nil
            return ProcessTransition(fromStep: a.from, toStep: a.to,
                                     occurrences: a.occ, avgSecs: avg,
                                     minSecs: nil, maxSecs: nil, stdDevSecs: nil)
        }
    }

    // Steps with collapsed groups replaced by a single virtual proxy step.
    private var resolvedSteps: [String: StepInfo] {
        guard !collapsedGroups.isEmpty else { return graph.steps }
        var result = graph.steps
        for group in collapsedGroups {
            for m in nodesInGroup(group) { result.removeValue(forKey: m) }
            let vid = collapsedNodeId(for: group)
            result[vid] = StepInfo(step: group, description: "", bgColor: "accentColor",
                                   fgColor: "white", score: nil, shape: "stadium",
                                   endOfProcess: false, belongsTo: nil)
        }
        return result
    }

    // ProcessGraph reflecting the current collapsed state (for max-value calculations).
    private var graphForDrawing: ProcessGraph {
        guard !collapsedGroups.isEmpty else { return graph }
        return ProcessGraph(steps: resolvedSteps, transitions: resolvedTransitions)
    }

    // Base positions → collapsed group members replaced by their centroid virtual node.
    // If the virtual node already has a user-set override (from a drag), that is kept.
    private func resolvedPositions(base: [String: CGPoint]) -> [String: CGPoint] {
        guard !collapsedGroups.isEmpty else { return base }
        var result = base
        for group in collapsedGroups {
            let members = nodesInGroup(group)
            let vid = collapsedNodeId(for: group)
            let hasOverride = result[vid] != nil
            let pts = members.compactMap { result[$0] }
            for m in members { result.removeValue(forKey: m) }
            if !hasOverride, !pts.isEmpty {
                let cx = pts.map(\.x).reduce(0, +) / CGFloat(pts.count)
                let cy = pts.map(\.y).reduce(0, +) / CGFloat(pts.count)
                result[vid] = CGPoint(x: cx, y: cy)
            }
        }
        return result
    }

    private var collapsedGroupsStorageKey: String {
        "graph.collapsedGroups_\(projectId)_\(chartMode)"
    }

    private var allGroupNames: Set<String> {
        Set(graph.steps.values.compactMap(\.belongsTo).filter { !$0.isEmpty })
    }

    private func applyInitialGroupState() {
        let allGroups = allGroupNames
        guard !allGroups.isEmpty else { return }
        switch graphStartMode {
        case .expanded:
            collapsedGroups = []
        case .collapsed:
            collapsedGroups = allGroups
        case .persisted:
            if let data    = UserDefaults.standard.data(forKey: collapsedGroupsStorageKey),
               let decoded = try? JSONDecoder().decode([String].self, from: data) {
                collapsedGroups = Set(decoded).intersection(allGroups)
            } else {
                collapsedGroups = []
            }
        }
    }

    private func saveCollapsedGroups() {
        guard graphStartMode == .persisted else { return }
        if let data = try? JSONEncoder().encode(Array(collapsedGroups)) {
            UserDefaults.standard.set(data, forKey: collapsedGroupsStorageKey)
        }
    }

    // Rect of the +/- toggle badge at the upper-right corner of a group box.
    private func groupToggleBadgeBounds(for rect: CGRect) -> CGRect {
        let bW: CGFloat = 22, bH: CGFloat = 22
        return CGRect(x: rect.maxX - bW - 6, y: rect.minY - bH / 2, width: bW, height: bH)
    }

    private func groupBadgeAt(_ pt: CGPoint) -> String? {
        for (name, rect) in groupRects(positions: effectivePositions) {
            if groupToggleBadgeBounds(for: rect).contains(pt) { return name }
        }
        return nil
    }

    // MARK: - Gestures

    private var zoomGesture: some Gesture {
        MagnificationGesture()
            .onChanged { value in setZoom(max(0.15, min(5.0, activeLastZoom * value))) }
            .onEnded   { _ in setLastZoom(activeZoom) }
    }

    private var mainDragGesture: some Gesture {
        DragGesture(minimumDistance: 4)
            .onChanged { value in
                switch dragMode {
                case .undetermined:
                    menuNode = nil
                    menuEdge = nil
                    let startCP = screenToCanvas(value.startLocation)
                    if let name = nodeAt(startCP) {
                        // Single-node drag
                        dragMode = .node(name)
                        setNodeOverride(name, snapped(screenToCanvas(value.location)))
                    } else if showGrouping, let groupName = groupAt(startCP) {
                        // Group drag: for collapsed groups move the virtual proxy; for expanded, all members
                        let keys: [String] = collapsedGroups.contains(groupName)
                            ? [collapsedNodeId(for: groupName)]
                            : nodesInGroup(groupName)
                        let snap = effectivePositions
                        let origins = keys.reduce(into: [String: CGPoint]()) { d, n in
                            d[n] = snap[n] ?? .zero
                        }
                        dragMode = .group(groupName, origins)
                        let cur = screenToCanvas(value.location)
                        let dx = cur.x - startCP.x, dy = cur.y - startCP.y
                        for (n, o) in origins {
                            setNodeOverride(n, snapped(CGPoint(x: o.x + dx, y: o.y + dy)))
                        }
                    } else {
                        dragMode = .pan
                        setPan(CGSize(
                            width:  activeLastPan.width  + value.translation.width,
                            height: activeLastPan.height + value.translation.height
                        ))
                    }
                case .node(let name):
                    setNodeOverride(name, snapped(screenToCanvas(value.location)))
                case .group(_, let origins):
                    let startCP = screenToCanvas(value.startLocation)
                    let cur     = screenToCanvas(value.location)
                    let dx = cur.x - startCP.x, dy = cur.y - startCP.y
                    for (n, o) in origins {
                        setNodeOverride(n, snapped(CGPoint(x: o.x + dx, y: o.y + dy)))
                    }
                case .pan:
                    setPan(CGSize(
                        width:  activeLastPan.width  + value.translation.width,
                        height: activeLastPan.height + value.translation.height
                    ))
                }
            }
            .onEnded { _ in
                if case .pan = dragMode { setLastPan(activePan) }
                dragMode = .undetermined
                saveOverrides()
            }
    }

    // MARK: - Node action context menu

    private func nodeActionMenu(for node: String, at pos: CGPoint) -> some View {
        let w: CGFloat = 214
        let estH: CGFloat = 114
        let margin: CGFloat = 10
        let rawY = pos.y + 56
        let x = min(max(w / 2 + margin, pos.x), viewSize.width  - w / 2 - margin)
        let y = min(max(estH / 2 + margin, rawY), viewSize.height - estH / 2 - margin)
        let desc = graph.steps[node]?.description
        let hasDesc = (desc ?? "").isEmpty == false && desc != node && showNodeDescriptions

        return VStack(alignment: .leading, spacing: 0) {
            Text(node)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .padding(.horizontal, 12)
                .padding(.top, 9)
                .padding(.bottom, 7)
            Divider()
            Button {
                onNodeAction?(node, .include)
                menuNode = nil
            } label: {
                Label("Require in journeys", systemImage: "checkmark.circle")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            Divider()
            Button {
                onNodeAction?(node, .exclude)
                menuNode = nil
            } label: {
                Label("Exclude from journeys", systemImage: "minus.circle")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.red)
            if hasDesc {
                Divider()
                Button {
                    menuNode = nil
                    descriptionNode = node
                } label: {
                    Label("Show description", systemImage: "text.alignleft")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .contentShape(Rectangle())
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                }
                .buttonStyle(.plain)
            }
            if onNodeNote != nil {
                Divider()
                Button {
                    onNodeNote?(node)
                    menuNode = nil
                } label: {
                    Label("Show Notes", systemImage: "note.text")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .contentShape(Rectangle())
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.yellow)
            }
        }
        .font(.callout)
        .frame(width: w)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12)
            .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.22), radius: 14, x: 0, y: 6)
        .position(x: x, y: y)
    }

    // MARK: - Description card

    private func descriptionCard(node: String, description: String, at pos: CGPoint) -> some View {
        let w: CGFloat = 240
        let margin: CGFloat = 12
        let x = min(max(w / 2 + margin, pos.x), viewSize.width  - w / 2 - margin)
        let y = min(max(120, pos.y + 56), viewSize.height - 120)

        return VStack(alignment: .leading, spacing: 8) {
            Text(node)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Divider()
            Text(description)
                .font(.callout)
                .fixedSize(horizontal: false, vertical: true)
            Button("Done") { descriptionNode = nil }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .padding(14)
        .frame(width: w)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12)
            .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.22), radius: 14, x: 0, y: 6)
        .position(x: x, y: y)
    }

    // MARK: - Edge action menu

    private func edgeActionMenu(for edge: ProcessTransition, at pos: CGPoint) -> some View {
        let w: CGFloat = 214
        let margin: CGFloat = 10
        let rawY = pos.y + 56
        let x = min(max(w / 2 + margin, pos.x), viewSize.width  - w / 2 - margin)
        let y = min(max(100, rawY), viewSize.height - 100)
        return VStack(alignment: .leading, spacing: 0) {
            Text("\(edge.fromStep) → \(edge.toStep)")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .padding(.horizontal, 12)
                .padding(.top, 9)
                .padding(.bottom, 7)
            Divider()
            Button {
                onEdgeNote?(edge)
                menuEdge = nil
            } label: {
                Label("Show Notes", systemImage: "note.text")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.yellow)
        }
        .font(.callout)
        .frame(width: w)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12)
            .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.22), radius: 14, x: 0, y: 6)
        .position(x: x, y: y)
    }

    // MARK: - Edge schema helpers

    private func activeEdgeSchema(for m: TransitionMetric) -> EdgeColorSchema {
        let raw: String
        switch m {
        case .count:   raw = edgeSchemaRawCount
        case .avgTime: raw = edgeSchemaRawAvg
        case .minTime: raw = edgeSchemaRawMin
        case .maxTime: raw = edgeSchemaRawMax
        case .stdDev:  raw = edgeSchemaRawStdDev
        }
        return EdgeColorSchema(rawValue: raw) ?? .neutral
    }

    // MARK: - Zoom controls overlay

    private var colorScaleIndicator: some View {
        let schema = activeEdgeSchema(for: metric)
        return VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 4) {
                Image(systemName: metric.icon)
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(.secondary)
                Text(metric.rawValue)
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(.secondary)
            }
            if let colors = schema.gradientColors {
                LinearGradient(colors: [colors.low, colors.high],
                               startPoint: .leading, endPoint: .trailing)
                    .frame(width: 64, height: 6)
                    .clipShape(RoundedRectangle(cornerRadius: 3))
                HStack(spacing: 0) {
                    Text("Low")
                        .font(.system(size: 8))
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                    Text("High")
                        .font(.system(size: 8))
                        .foregroundStyle(.secondary)
                }
                .frame(width: 64)
            } else {
                RoundedRectangle(cornerRadius: 3)
                    .fill(Color.secondary.opacity(0.25))
                    .frame(width: 64, height: 6)
                Text("No color scale")
                    .font(.system(size: 8))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private var zoomControls: some View {
        HStack(spacing: 8) {
            Button {
                let z = max(0.15, activeZoom / 1.3)
                withAnimation { setZoom(z); setLastZoom(z) }
            } label: {
                Image(systemName: "minus.magnifyingglass")
            }
            Text(String(format: "%.0f%%", activeZoom * 100))
                .font(.caption.monospacedDigit())
                .frame(width: 44)
            Button {
                let z = min(5.0, activeZoom * 1.3)
                withAnimation { setZoom(z); setLastZoom(z) }
            } label: {
                Image(systemName: "plus.magnifyingglass")
            }
            Button {
                withAnimation(.spring(duration: 0.4)) {
                    setZoom(1); setLastZoom(1); setPan(.zero); setLastPan(.zero)
                }
            } label: {
                Image(systemName: "arrow.uturn.backward.circle")
            }
            Divider().frame(height: 16)
            Button {
                resetLayout()
            } label: {
                Image(systemName: "arrow.counterclockwise.circle")
            }
            if showGrouping && !allGroupNames.isEmpty {
                Divider().frame(height: 16)
                Button {
                    withAnimation {
                        if collapsedGroups == allGroupNames {
                            collapsedGroups = []
                        } else {
                            collapsedGroups = allGroupNames
                        }
                    }
                } label: {
                    Image(systemName: collapsedGroups == allGroupNames
                          ? "arrow.up.left.and.arrow.down.right"
                          : "arrow.down.right.and.arrow.up.left")
                }
            }
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 10))
    }

    // MARK: - Edge drawing

    private func drawEdge(ctx: GraphicsContext, transition: ProcessTransition,
                          positions: [String: CGPoint], nodeH: CGFloat,
                          drawGraph: ProcessGraph) {
        guard let fromPos = positions[transition.fromStep],
              let toPos   = positions[transition.toStep] else { return }

        // Determine visual appearance based on mode
        let lineWidth:  CGFloat
        let lineColor:  Color
        let lineAlpha:  Double
        let labelText:  String
        let useBadge:   Bool   // true when showing norm or compliance badge

        if let norms = normValues {
            useBadge = true
            let normVal      = norms[transition.id]
            // Count norms are percentages relative to total outgoing from the same source node
            let outgoing     = drawGraph.transitions.filter { $0.fromStep == transition.fromStep }
                                   .reduce(0) { $0 + $1.occurrences }
            let isCountPct   = normMetric == .count
            let actualVal: Double = isCountPct
                ? (outgoing > 0 ? Double(transition.occurrences) / Double(outgoing) * 100.0 : 0.0)
                : (transition.metricValue(for: normMetric) ?? Double(transition.occurrences))

            if showCompliance {
                // Compliance mode: width by actual metric ratio, color by actual-vs-norm
                let maxVal = drawGraph.maxValue(for: normMetric)
                let ratio  = max(0, min(1, CGFloat(actualVal / max(maxVal, 1))))
                lineWidth  = 3.0 + ratio * 19.0
                lineAlpha  = 0.45 + Double(ratio) * 0.35
                if let nv = normVal {
                    lineColor = actualVal <= nv ? .green : .red
                } else {
                    lineColor = .secondary
                }
                labelText = isCountPct
                    ? String(format: "%.0f%%", actualVal)
                    : (normMetric.isTimeBased
                        ? (transition.metricValue(for: normMetric).map { formatDuration($0) } ?? "—")
                        : formatCount(transition.occurrences))
            } else {
                // Target process mode: uniform appearance, show stored norm values
                lineWidth = 6.0
                lineAlpha = 0.40
                lineColor = .secondary
                if let nv = normVal {
                    labelText = isCountPct
                        ? String(format: "%.0f%%", nv)
                        : (normMetric.isTimeBased ? formatDuration(nv) : formatCount(Int(nv.rounded())))
                } else {
                    labelText = "—"
                }
            }
        } else {
            // Normal mode: metric-based thickness + optional weight colorization
            useBadge = false
            let maxVal = drawGraph.maxValue(for: metric)
            let val    = transition.metricValue(for: metric) ?? Double(transition.occurrences)
            let ratio  = max(0, min(1, CGFloat(val / max(maxVal, 1))))
            lineWidth  = 3.0 + ratio * 19.0
            lineAlpha  = 0.3 + Double(ratio) * 0.5
            if colorizeByWeight, let colors = activeEdgeSchema(for: metric).gradientColors {
                lineColor = colors.low.interpolated(to: colors.high, t: Double(ratio))
            } else {
                lineColor = .secondary
            }
            labelText  = metric.isTimeBased
                ? (transition.metricValue(for: metric).map { formatDuration($0) } ?? "—")
                : formatCount(transition.occurrences)
        }

        // Draw edge path
        if transition.fromStep == transition.toStep {
            let r: CGFloat = 18
            let loopRect = CGRect(x: fromPos.x - r, y: fromPos.y - nodeH / 2 - r * 2.2,
                                  width: r * 2, height: r * 2)
            var path = Path(); path.addEllipse(in: loopRect)
            ctx.stroke(path, with: .color(lineColor.opacity(lineAlpha)),
                       style: StrokeStyle(lineWidth: lineWidth))
        } else {
            let start  = CGPoint(x: fromPos.x, y: fromPos.y + nodeH / 2)
            let end    = CGPoint(x: toPos.x,   y: toPos.y   - nodeH / 2)
            let dy     = end.y - start.y
            let cpDist = max(abs(dy) * 0.45, 40.0)
            let cp1    = CGPoint(x: start.x, y: start.y + cpDist)
            let cp2    = CGPoint(x: end.x,   y: end.y   - cpDist)

            var path = Path()
            path.move(to: start)
            path.addCurve(to: end, control1: cp1, control2: cp2)
            ctx.stroke(path, with: .color(lineColor.opacity(lineAlpha)),
                       style: StrokeStyle(lineWidth: lineWidth, lineCap: .round, lineJoin: .round))

            let arrowSize = max(5.0, lineWidth * 0.75)
            drawArrowHead(ctx: ctx, tip: end, color: lineColor, size: arrowSize, alpha: lineAlpha)
        }

        // Draw label or norm badge
        let mid = CGPoint(x: (fromPos.x + toPos.x) / 2, y: (fromPos.y + toPos.y) / 2)

        if useBadge {
            let hasNorm = normValues?[transition.id] != nil
            let badgeColor: Color
            if showCompliance {
                if let nv = normValues?[transition.id] {
                    let out  = drawGraph.transitions.filter { $0.fromStep == transition.fromStep }
                                   .reduce(0) { $0 + $1.occurrences }
                    let av: Double = normMetric == .count
                        ? (out > 0 ? Double(transition.occurrences) / Double(out) * 100.0 : 0.0)
                        : (transition.metricValue(for: normMetric) ?? Double(transition.occurrences))
                    badgeColor = (normIsMinimum ? av >= nv : av <= nv) ? .green : .red
                } else {
                    badgeColor = .secondary
                }
            } else {
                badgeColor = hasNorm ? Color.accentColor : Color.secondary
            }
            let badgeFill: Double = (hasNorm || showCompliance) ? 0.88 : 0.30
            let badgeW: CGFloat   = max(44, CGFloat(labelText.count) * 9 + 18)
            let badgeH: CGFloat   = 22
            let badgeRect = CGRect(x: mid.x - badgeW / 2, y: mid.y - badgeH / 2,
                                   width: badgeW, height: badgeH)
            ctx.fill(Path(roundedRect: badgeRect, cornerRadius: badgeH / 2),
                     with: .color(badgeColor.opacity(badgeFill)))
            ctx.draw(
                Text(labelText)
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .foregroundStyle((hasNorm || showCompliance) ? Color.white : Color.primary.opacity(0.55)),
                at: mid, anchor: .center
            )
        } else {
            ctx.draw(
                Text(labelText)
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .foregroundStyle(.primary),
                at: mid, anchor: .center
            )
        }

        // Small yellow dot when edge has a note
        if hasNote(forEdge: transition) {
            let dotR: CGFloat = 7
            let dotCenter = CGPoint(x: mid.x + 18, y: mid.y)
            ctx.drawLayer { lCtx in
                lCtx.addFilter(.shadow(color: .black.opacity(0.25), radius: 3, x: 0, y: 1))
                lCtx.fill(Path(ellipseIn: CGRect(x: dotCenter.x - dotR, y: dotCenter.y - dotR,
                                                  width: dotR * 2, height: dotR * 2)),
                          with: .color(.yellow))
            }
            ctx.draw(
                Text("✎").font(.system(size: 9)).foregroundStyle(Color.black.opacity(0.75)),
                at: dotCenter, anchor: .center
            )
        }
    }

    private func drawArrowHead(ctx: GraphicsContext, tip: CGPoint,
                               color: Color = .secondary, size: CGFloat, alpha: Double) {
        var arrow = Path()
        arrow.move(to: tip)
        arrow.addLine(to: CGPoint(x: tip.x - size, y: tip.y - size * 1.6))
        arrow.addLine(to: CGPoint(x: tip.x + size, y: tip.y - size * 1.6))
        arrow.closeSubpath()
        ctx.fill(arrow, with: .color(color.opacity(alpha + 0.1)))
    }

    // MARK: - Node shape helper

    private func nodePath(shape: String, rect: CGRect) -> Path {
        switch shape {
        case "stadium":
            return Path(roundedRect: rect, cornerRadius: rect.height / 2)
        case "circle":
            return Path(ellipseIn: rect)
        case "hex":
            let cx = rect.midX, cy = rect.midY
            let rx = rect.width / 2, ry = rect.height / 2
            var p = Path()
            for i in 0..<6 {
                let angle = CGFloat(i) * .pi / 3 - .pi / 6
                let pt = CGPoint(x: cx + rx * cos(angle), y: cy + ry * sin(angle))
                i == 0 ? p.move(to: pt) : p.addLine(to: pt)
            }
            p.closeSubpath()
            return p
        default: // "round"
            return Path(roundedRect: rect, cornerRadius: 12)
        }
    }

    // MARK: - Node drawing

    private func drawNode(ctx: GraphicsContext, name: String, step: StepInfo,
                          positions: [String: CGPoint], lifted: Bool, nodeH: CGFloat) {
        guard let center = positions[name] else { return }

        // Virtual group proxy nodes: show member count inside, group name is on the box badge.
        let bgColor: Color
        let fgColor: Color
        if let groupName = isVirtualGroupNode(name) {
            bgColor = groupColor(for: groupName)
            fgColor = .white
        } else {
            bgColor = step.backgroundColor
            fgColor = step.foregroundColor
        }

        let rect  = CGRect(x: center.x - nodeW / 2, y: center.y - nodeH / 2,
                           width: nodeW, height: nodeH)
        let shape = nodePath(shape: step.shape, rect: rect)

        // Shadow — larger when node is being dragged
        ctx.fill(nodePath(shape: step.shape, rect: rect.offsetBy(dx: lifted ? 4 : 2, dy: lifted ? 8 : 3)),
                 with: .color(.black.opacity(lifted ? 0.22 : 0.12)))

        ctx.fill(shape, with: .color(bgColor))
        ctx.stroke(shape,
                   with: .color(.black.opacity(lifted ? 0.28 : 0.18)),
                   style: StrokeStyle(lineWidth: lifted ? 1.5 : 1.0))

        // Collapsed group proxy: show member count centered in the node
        if let groupName = isVirtualGroupNode(name) {
            let count = nodesInGroup(groupName).count
            let countSize: CGFloat = 22, labelSize: CGFloat = 10, gap: CGFloat = 2
            let totalH = countSize + gap + labelSize
            let countY = center.y - totalH / 2 + countSize / 2
            let labelY = center.y + totalH / 2 - labelSize / 2
            ctx.draw(
                Text("\(count)")
                    .font(.system(size: countSize, weight: .bold, design: .rounded))
                    .foregroundStyle(fgColor),
                at: CGPoint(x: center.x, y: countY), anchor: .center
            )
            ctx.draw(
                Text(count == 1 ? "node" : "nodes")
                    .font(.system(size: labelSize, weight: .regular, design: .rounded))
                    .foregroundStyle(fgColor.opacity(0.80)),
                at: CGPoint(x: center.x, y: labelY), anchor: .center
            )
        } else if let time = step.eventTime {
            // Split node vertically: name on top, time below
            let nameRect = CGRect(x: rect.minX, y: rect.minY,
                                  width: rect.width, height: rect.height * 0.56)
            let timeRect = CGRect(x: rect.minX, y: rect.minY + rect.height * 0.56,
                                  width: rect.width, height: rect.height * 0.44)
            ctx.draw(
                Text(name)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(fgColor),
                at: CGPoint(x: nameRect.midX, y: nameRect.midY), anchor: .center
            )
            let timeStr = time.formatted(date: .omitted, time: .standard)
            ctx.draw(
                Text(timeStr)
                    .font(.system(size: 10, weight: .regular, design: .monospaced))
                    .foregroundStyle(fgColor.opacity(0.75)),
                at: CGPoint(x: timeRect.midX, y: timeRect.midY), anchor: .center
            )
        } else {
            let desc = step.description
            let hasDesc = showNodeDescriptions && !desc.isEmpty && desc != name
            if hasDesc {
                let nameRect = CGRect(x: rect.minX, y: rect.minY,
                                     width: rect.width, height: rect.height * 0.55)
                let descRect = CGRect(x: rect.minX, y: rect.minY + rect.height * 0.55,
                                     width: rect.width, height: rect.height * 0.45)
                ctx.draw(
                    Text(name)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(fgColor),
                    at: CGPoint(x: nameRect.midX, y: nameRect.midY), anchor: .center
                )
                let truncated = desc.count > 20 ? String(desc.prefix(20)) + "\u{2026}" : desc
                ctx.draw(
                    Text(truncated)
                        .font(.system(size: 13, weight: .regular))
                        .foregroundStyle(fgColor.opacity(0.80)),
                    at: CGPoint(x: descRect.midX, y: descRect.midY), anchor: .center
                )
            } else {
                ctx.draw(
                    Text(name)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(fgColor),
                    at: CGPoint(x: rect.midX, y: rect.midY), anchor: .center
                )
            }
        }

        if step.endOfProcess {
            let dotR: CGFloat = 5
            let dotCenter = CGPoint(x: rect.maxX - 10, y: rect.minY + 10)
            ctx.fill(
                Path(ellipseIn: CGRect(x: dotCenter.x - dotR, y: dotCenter.y - dotR,
                                       width: dotR * 2, height: dotR * 2)),
                with: .color(.orange)
            )
        }

        if let score = step.score {
            let bR: CGFloat = 13
            let bCenter = CGPoint(x: rect.minX + bR, y: rect.minY - 4)
            let badgeRect = CGRect(x: bCenter.x - bR, y: bCenter.y - bR,
                                   width: bR * 2, height: bR * 2)
            let badgeColor: Color = score > 0 ? .green : score < 0 ? .red : .blue

            // Filled badge inside an isolated layer so the shadow applies only to the fill
            ctx.drawLayer { lCtx in
                lCtx.addFilter(.shadow(color: .black.opacity(0.40), radius: 5, x: 0, y: 3))
                lCtx.fill(Path(ellipseIn: badgeRect), with: .color(badgeColor))
            }
            // White border separates the badge from the node surface
            ctx.stroke(Path(ellipseIn: badgeRect),
                       with: .color(.white.opacity(0.90)),
                       style: StrokeStyle(lineWidth: 2))
            ctx.draw(
                Text("\(score)").font(.system(size: 10, weight: .bold)).foregroundStyle(.white),
                at: bCenter, anchor: .center
            )
        }

        // Note badge (yellow, top-right corner)
        if hasNote(forNode: name) {
            let nR: CGFloat = 11
            let nCenter = CGPoint(x: rect.maxX - nR + 2, y: rect.minY - 4)
            let nRect   = CGRect(x: nCenter.x - nR, y: nCenter.y - nR, width: nR * 2, height: nR * 2)
            ctx.drawLayer { lCtx in
                lCtx.addFilter(.shadow(color: .black.opacity(0.30), radius: 4, x: 0, y: 2))
                lCtx.fill(Path(ellipseIn: nRect), with: .color(.yellow))
            }
            ctx.draw(
                Text("✎").font(.system(size: 11)).foregroundStyle(Color.black.opacity(0.75)),
                at: nCenter, anchor: .center
            )
        }

    }

    // MARK: - Start node indicator

    private func drawStartArrow(ctx: GraphicsContext, at centerX: CGFloat, tipY: CGFloat) {
        let stemTopY = tipY - 46    // dot sits 46pt above the arrowhead tip
        let color    = Color(red: 0.18, green: 0.80, blue: 0.38)
        let hw: CGFloat = 13, th: CGFloat = 15, r: CGFloat = 7

        ctx.drawLayer { lCtx in
            lCtx.addFilter(.shadow(color: .black.opacity(0.35), radius: 5, x: 0, y: 2))
            var stem = Path()
            stem.move(to: CGPoint(x: centerX, y: stemTopY + r + 2))
            stem.addLine(to: CGPoint(x: centerX, y: tipY - th))
            lCtx.stroke(stem, with: .color(color),
                        style: StrokeStyle(lineWidth: 4, lineCap: .round))
            var head = Path()
            head.move(to: CGPoint(x: centerX,        y: tipY))
            head.addLine(to: CGPoint(x: centerX - hw, y: tipY - th))
            head.addLine(to: CGPoint(x: centerX + hw, y: tipY - th))
            head.closeSubpath()
            lCtx.fill(head, with: .color(color))
            lCtx.fill(Path(ellipseIn: CGRect(x: centerX - r, y: stemTopY - r,
                                             width: r * 2, height: r * 2)),
                      with: .color(color))
        }
        var stem = Path()
        stem.move(to: CGPoint(x: centerX, y: stemTopY + r + 2))
        stem.addLine(to: CGPoint(x: centerX, y: tipY - th))
        ctx.stroke(stem, with: .color(color),
                   style: StrokeStyle(lineWidth: 4, lineCap: .round))
        var head = Path()
        head.move(to: CGPoint(x: centerX,        y: tipY))
        head.addLine(to: CGPoint(x: centerX - hw, y: tipY - th))
        head.addLine(to: CGPoint(x: centerX + hw, y: tipY - th))
        head.closeSubpath()
        ctx.fill(head, with: .color(color))
        ctx.fill(Path(ellipseIn: CGRect(x: centerX - r, y: stemTopY - r,
                                        width: r * 2, height: r * 2)),
                 with: .color(color))
    }

    // End node indicator: dot just below the node/group, stem + arrowhead pointing down.
    private func drawEndArrow(ctx: GraphicsContext, at centerX: CGFloat, baseY: CGFloat) {
        let dotY     = baseY
        let tipY     = dotY + 46
        let color    = Color(red: 0.95, green: 0.42, blue: 0.12)
        let hw: CGFloat = 13, th: CGFloat = 15, r: CGFloat = 7

        ctx.drawLayer { lCtx in
            lCtx.addFilter(.shadow(color: .black.opacity(0.35), radius: 5, x: 0, y: 2))
            var stem = Path()
            stem.move(to: CGPoint(x: centerX, y: dotY + r + 2))
            stem.addLine(to: CGPoint(x: centerX, y: tipY - th))
            lCtx.stroke(stem, with: .color(color),
                        style: StrokeStyle(lineWidth: 4, lineCap: .round))
            var head = Path()
            head.move(to: CGPoint(x: centerX,        y: tipY))
            head.addLine(to: CGPoint(x: centerX - hw, y: tipY - th))
            head.addLine(to: CGPoint(x: centerX + hw, y: tipY - th))
            head.closeSubpath()
            lCtx.fill(head, with: .color(color))
            lCtx.fill(Path(ellipseIn: CGRect(x: centerX - r, y: dotY - r,
                                             width: r * 2, height: r * 2)),
                      with: .color(color))
        }
        var stem = Path()
        stem.move(to: CGPoint(x: centerX, y: dotY + r + 2))
        stem.addLine(to: CGPoint(x: centerX, y: tipY - th))
        ctx.stroke(stem, with: .color(color),
                   style: StrokeStyle(lineWidth: 4, lineCap: .round))
        var head = Path()
        head.move(to: CGPoint(x: centerX,        y: tipY))
        head.addLine(to: CGPoint(x: centerX - hw, y: tipY - th))
        head.addLine(to: CGPoint(x: centerX + hw, y: tipY - th))
        head.closeSubpath()
        ctx.fill(head, with: .color(color))
        ctx.fill(Path(ellipseIn: CGRect(x: centerX - r, y: dotY - r,
                                        width: r * 2, height: r * 2)),
                 with: .color(color))
    }

    // MARK: - Group helpers

    private func groupRects(positions: [String: CGPoint]) -> [(name: String, rect: CGRect)] {
        let pad: CGFloat = 20
        let nh = effectiveNodeH
        var grouped: [String: [CGPoint]] = [:]
        // Expanded groups: collect member node positions
        for (name, step) in graph.steps {
            guard let group = step.belongsTo, !group.isEmpty,
                  !collapsedGroups.contains(group),
                  let pos = positions[name] else { continue }
            grouped[group, default: []].append(pos)
        }
        // Collapsed groups: use the virtual proxy node position
        for group in collapsedGroups {
            if let pos = positions[collapsedNodeId(for: group)] { grouped[group] = [pos] }
        }
        return grouped.sorted { $0.key < $1.key }.map { (groupName, centers) in
            let minX = centers.map { $0.x - nodeW / 2 }.min()! - pad
            let minY = centers.map { $0.y - nh  / 2 }.min()! - pad - 18
            let maxX = centers.map { $0.x + nodeW / 2 }.max()! + pad
            let maxY = centers.map { $0.y + nh  / 2 }.max()! + pad
            return (name: groupName, rect: CGRect(x: minX, y: minY,
                                                  width: maxX - minX, height: maxY - minY))
        }
    }

    private func groupColor(for name: String) -> Color {
        let hash = name.unicodeScalars.reduce(0) { ($0 &* 31) &+ Int($1.value) }
        let hue  = Double(abs(hash) % 360) / 360.0
        return Color(hue: hue, saturation: 0.55, brightness: 0.72)
    }

    // MARK: - Note badge helpers

    private func hasNote(forNode name: String) -> Bool {
        notes?.contains { if case .node(let n) = $0.target { return n == name }; return false } ?? false
    }
    private func hasNote(forEdge t: ProcessTransition) -> Bool {
        notes?.contains { if case .edge(let f, let to) = $0.target { return f == t.fromStep && to == t.toStep }; return false } ?? false
    }

    // MARK: - Helpers

    private func formatCount(_ n: Int) -> String {
        switch n {
        case 0..<1_000:     return "\(n)"
        case 0..<1_000_000: return String(format: "%.1fk", Double(n) / 1_000)
        default:            return String(format: "%.1fM", Double(n) / 1_000_000)
        }
    }

    private func formatDuration(_ secs: Double) -> String {
        if secs < 60    { return String(format: "%.0fs",  secs) }
        if secs < 3600  { return String(format: "%.0fm",  secs / 60) }
        if secs < 86400 { return String(format: "%.1fh",  secs / 3600) }
        return            String(format: "%.1fd",  secs / 86400)
    }
}
