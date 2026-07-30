import { useMemo, useState } from "react";
import type { GraphNode, KnowledgeGraph as GraphData } from "../types";

interface PositionedNode extends GraphNode {
  x: number;
  y: number;
}

const palette = {
  library: "#8b5cf6",
  version: "#60a5fa",
  page: "#9ca3af",
  source: "#2dd4bf",
  api: "#8b5cf6",
  guide: "#2dd4bf",
  example: "#f472b6",
  concept: "#f59e0b",
  default: "#9ca3af"
};

function nodeColor(node: GraphNode) {
  const key = (node.kind || node.group || "default").toLowerCase();
  return (
    Object.entries(palette).find(([name]) => key.includes(name))?.[1] ?? palette.default
  );
}

function layout(graph: GraphData, width: number, height: number): PositionedNode[] {
  const visible = graph.nodes.slice(0, 80);
  if (!visible.length) return [];
  const groups = new Map<string, GraphNode[]>();
  visible.forEach((node) => {
    const group = node.group || node.kind || "other";
    groups.set(group, [...(groups.get(group) ?? []), node]);
  });
  const groupRows = [...groups.values()];
  const centerX = width / 2;
  const centerY = height / 2;
  const orbit = Math.min(width, height) * 0.31;
  const result: PositionedNode[] = [];

  groupRows.forEach((nodes, groupIndex) => {
    const groupAngle = (Math.PI * 2 * groupIndex) / groupRows.length - Math.PI / 2;
    const groupCenterX = centerX + Math.cos(groupAngle) * orbit;
    const groupCenterY = centerY + Math.sin(groupAngle) * orbit;
    nodes.forEach((node, nodeIndex) => {
      const localAngle = (Math.PI * 2 * nodeIndex) / Math.max(nodes.length, 1);
      const localRadius = Math.min(78, 18 + nodes.length * 5);
      result.push({
        ...node,
        x: groupCenterX + Math.cos(localAngle) * localRadius,
        y: groupCenterY + Math.sin(localAngle) * localRadius
      });
    });
  });
  return result;
}

export function KnowledgeGraph({
  graph,
  onOpen
}: {
  graph: GraphData;
  onOpen?: (node: GraphNode) => void;
}) {
  const [selected, setSelected] = useState<string>();
  const width = 900;
  const height = 540;
  const nodes = useMemo(() => layout(graph, width, height), [graph]);
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const selectedNode = selected ? nodeMap.get(selected) : undefined;

  if (!nodes.length) {
    return (
      <div className="empty-state empty-state--graph">
        <div className="empty-orbit" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
        <h3>图谱尚未生成</h3>
        <p>发布 Wiki 后，这里会显示 library、版本、页面与源码引用关系。</p>
      </div>
    );
  }

  return (
    <div className="graph-shell">
      <svg
        className="knowledge-graph"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`知识图谱，包含 ${nodes.length} 个节点和 ${graph.edges.length} 条关系`}
      >
        <defs>
          <filter id="node-glow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <radialGradient id="graph-aura">
            <stop offset="0%" stopColor="#8b5cf6" stopOpacity=".1" />
            <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="450" cy="270" r="250" fill="url(#graph-aura)" />
        <g className="graph-edges">
          {graph.edges.slice(0, 200).map((edge, index) => {
            const source = nodeMap.get(edge.source);
            const target = nodeMap.get(edge.target);
            if (!source || !target) return null;
            const active = selected && (selected === edge.source || selected === edge.target);
            return (
              <line
                key={`${edge.source}-${edge.target}-${index}`}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                className={active ? "is-active" : undefined}
              >
                <title>{edge.kind || "引用关系"}</title>
              </line>
            );
          })}
        </g>
        <g className="graph-nodes">
          {nodes.map((node) => {
            const isSelected = selected === node.id;
            const radius = Math.max(7, Math.min(15, 7 + (node.weight ?? 1)));
            return (
              <g
                key={node.id}
                transform={`translate(${node.x} ${node.y})`}
                className={isSelected ? "graph-node is-selected" : "graph-node"}
                role="button"
                tabIndex={0}
                aria-label={`${node.label}，${node.kind || "节点"}`}
                onClick={() => setSelected(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelected(node.id);
                  }
                }}
              >
                <circle
                  r={radius + 7}
                  fill={nodeColor(node)}
                  opacity=".08"
                  filter={isSelected ? "url(#node-glow)" : undefined}
                />
                <circle
                  r={radius}
                  fill={nodeColor(node)}
                  stroke={isSelected ? "#fff" : nodeColor(node)}
                  strokeWidth={isSelected ? 2 : 1}
                />
                <text y={radius + 17} textAnchor="middle">
                  {node.label.length > 18 ? `${node.label.slice(0, 17)}…` : node.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="graph-legend" aria-label="节点图例">
        {Object.entries(palette)
          .filter(([name]) => name !== "default")
          .map(([name, color]) => (
            <span key={name}>
              <i style={{ backgroundColor: color }} /> {name}
            </span>
          ))}
      </div>
      {selectedNode && (
        <aside className="graph-inspector">
          <span className="eyebrow">{selectedNode.kind || "知识节点"}</span>
          <h3>{selectedNode.label}</h3>
          <p>{selectedNode.path || selectedNode.id}</p>
          {onOpen && selectedNode.path && (
            <button className="button button--small" onClick={() => onOpen(selectedNode)}>
              打开文档
            </button>
          )}
        </aside>
      )}
    </div>
  );
}
