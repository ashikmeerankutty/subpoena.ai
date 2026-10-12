"use client";

import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useRef, useState } from "react";

import { AGENTS, EXPERTS } from "@/lib/agents";
import type { AgentName, PipelineEvent } from "@/lib/types";

type AgentNodeData = { agent: AgentName; count: number; active: boolean; selected: boolean };

function AgentNode({ data }: NodeProps<Node<AgentNodeData>>) {
  const meta = AGENTS[data.agent];
  const visited = data.count > 0;
  return (
    <div style={{
      width: 132, padding: "8px 10px", borderRadius: 10, background: visited ? "#fff" : "#f4f4f6",
      border: `2px solid ${data.active ? meta.color : data.selected ? "#121c2d" : visited ? meta.color + "66" : "#e1e3ea"}`,
      boxShadow: data.active ? `0 0 0 6px ${meta.color}22` : "none", transition: "all .25s", fontFamily: "Inter, sans-serif",
      opacity: visited ? 1 : 0.6,
    }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span className={data.active ? "live-dot" : undefined}
          style={{ width: 8, height: 8, borderRadius: 4, background: visited ? meta.color : "#c1c4cf" }} />
        <strong style={{ fontSize: 13, color: "#121c2d" }}>{meta.label}</strong>
        {data.count ? <span style={{ marginLeft: "auto", fontSize: 11, color: "#606b85" }}>{data.count}</span> : null}
      </div>
      <div style={{ fontSize: 11, color: "#606b85", marginTop: 2 }}>{meta.role}</div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const NODE_TYPES = { agent: AgentNode };

const POS: Partial<Record<AgentName, [number, number]>> = {
  system: [-210, 200], clerk: [0, 200],
  geo: [210, 0], device: [210, 95], velocity: [210, 190], merchant: [210, 285], graph: [210, 380],
  prosecutor: [430, 110], defense: [430, 290],
  judge: [650, 200], bailiff: [870, 90], witness: [1090, 90], stenographer: [870, 320],
};

const LINKS: [AgentName, AgentName][] = [
  ["system", "clerk"],
  ...EXPERTS.map((e) => ["clerk", e] as [AgentName, AgentName]),
  ...EXPERTS.flatMap((e) => [[e, "prosecutor"], [e, "defense"]] as [AgentName, AgentName][]),
  ["prosecutor", "defense"], ["prosecutor", "judge"], ["defense", "judge"],
  ["judge", "bailiff"], ["bailiff", "witness"], ["witness", "judge"], ["judge", "stenographer"],
];

/** Which edges light up for the latest event. */
function activeLinks(e: PipelineEvent | undefined): Set<string> {
  const s = new Set<string>();
  if (!e) return s;
  const a = e.from_agent;
  const add = (x: AgentName, y: AgentName) => s.add(`${x}->${y}`);
  if (e.type === "CASE_OPENED") add("system", "clerk");
  if (e.type === "TOOL_CALL" && EXPERTS.includes(a)) add("clerk", a);
  if (e.type === "FINDING") { add(a, "prosecutor"); add(a, "defense"); }
  if (e.type === "ARGUMENT" || e.type === "REBUTTAL") { add(a, "judge"); add("prosecutor", "defense"); }
  if (e.type === "RULING" || e.type === "SUBPOENA_SENT") add("judge", e.type === "RULING" && e.payload.outcome !== "SUBPOENA" ? "stenographer" : "bailiff");
  if (e.type === "SUBPOENA_SENT" || (e.type === "TOOL_CALL" && a === "bailiff")) add("bailiff", "witness");
  if (e.type === "WITNESS_AUTH" || e.type === "TESTIMONY") add("witness", "judge");
  if (e.type === "VERDICT") add("judge", "stenographer");
  return s;
}

export function PipelineGraph({ events, selected, onSelect }: {
  events: PipelineEvent[]; selected: AgentName | null; onSelect: (a: AgentName | null) => void;
}) {
  const last = events[events.length - 1];
  const counts = useMemo(() => {
    const c: Partial<Record<AgentName, number>> = {};
    for (const e of events) c[e.from_agent] = (c[e.from_agent] ?? 0) + 1;
    return c;
  }, [events]);
  const active = activeLinks(last);

  const nodes: Node<AgentNodeData>[] = (Object.keys(POS) as AgentName[]).map((agent) => ({
    id: agent, type: "agent", position: { x: POS[agent]![0], y: POS[agent]![1] }, draggable: false,
    data: { agent, count: counts[agent] ?? 0, active: last?.from_agent === agent, selected: selected === agent },
  }));
  const edges: Edge[] = LINKS.map(([s, t]) => {
    const on = active.has(`${s}->${t}`);
    const seen = (counts[s] ?? 0) > 0 && (counts[t] ?? 0) > 0;
    return {
      id: `${s}->${t}`, source: s, target: t, animated: on,
      style: { stroke: on ? AGENTS[s].color : seen ? "#8891aa" : "#e1e3ea", strokeWidth: on ? 2.5 : 1.25 },
    };
  });

  const box = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    // Hidden tab panels measure 0×0; only mount the canvas once it has a size.
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setVisible(el.offsetWidth > 0));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={box} style={{ height: 470, border: "1px solid #e1e3ea", borderRadius: 8, background: "#fbfbfc" }}>
      {visible ? <ReactFlow nodes={nodes} edges={edges} nodeTypes={NODE_TYPES} fitView
        fitViewOptions={{ padding: 0.08 }}
        onInit={(rf) => { setTimeout(() => rf.fitView({ padding: 0.08 }), 60); }} nodesConnectable={false} panOnScroll zoomOnScroll={false}
        onNodeClick={(_, n) => onSelect(selected === n.id ? null : (n.id as AgentName))}
        proOptions={{ hideAttribution: true }}>
        <Background gap={20} color="#eceef2" />
      </ReactFlow> : null}
    </div>
  );
}
