import type { AgentName } from "./types";

export const AGENTS: Record<AgentName, { label: string; color: string; role: string }> = {
  system: { label: "System", color: "#606b85", role: "Tier 0 & bookkeeping" },
  clerk: { label: "Clerk", color: "#0263e0", role: "Evidence intake" },
  geo: { label: "Geo", color: "#0b7a8a", role: "Expert witness" },
  device: { label: "Device", color: "#0b7a8a", role: "Expert witness" },
  velocity: { label: "Velocity", color: "#0b7a8a", role: "Expert witness" },
  merchant: { label: "Merchant", color: "#0b7a8a", role: "Expert witness" },
  graph: { label: "Graph", color: "#0b7a8a", role: "Expert witness" },
  prosecutor: { label: "Prosecutor", color: "#d61f1f", role: "Argues BLOCK" },
  defense: { label: "Defense", color: "#0b7a39", role: "Argues APPROVE" },
  judge: { label: "Judge", color: "#6d2ed1", role: "Rules p_fraud" },
  bailiff: { label: "Bailiff", color: "#a84b00", role: "Witness auth" },
  witness: { label: "Witness", color: "#121c2d", role: "Cardholder" },
  stenographer: { label: "Stenographer", color: "#4b5671", role: "Explains verdict" },
  analyst: { label: "Analyst", color: "#c8102e", role: "Appeals court" },
};

export const EXPERTS: AgentName[] = ["geo", "device", "velocity", "merchant", "graph"];
