"use client";

import { Menu, MenuButton, MenuItem, useMenuState } from "@twilio-paste/core/menu";
import { ChevronDownIcon } from "@twilio-paste/icons/esm/ChevronDownIcon";
import { useRouter } from "next/navigation";

import { useToast } from "@/app/providers";
import { api, usePoll } from "@/lib/api";
import type { Evaluation } from "@/lib/types";

interface Scenario { name: string; description: string; request: Record<string, any> }

/** Sends a seed scenario as a fresh transaction (Sources → "test event" in the spec). */
export function SendTestEvent({ openCase = true }: { openCase?: boolean }) {
  const menu = useMenuState();
  const toast = useToast();
  const router = useRouter();
  const { data } = usePoll<{ data: Scenario[] }>("demo/scenarios");

  async function send(s: Scenario) {
    menu.hide();
    const suffix = Math.random().toString(36).slice(2, 8);
    const body = { ...s.request, transaction_id: `${s.request.transaction_id}_${suffix}` };
    try {
      const ev = await api<Evaluation>("evaluations", {
        method: "POST",
        body: JSON.stringify({ ...body, options: { sync_timeout_ms: 0 } }),
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      toast.push({ message: `${s.name}: ${ev.tier0?.route === "COURT" ? "sent to court" : ev.verdict}`, variant: "success", dismissAfter: 4000 });
      if (openCase && ev.tier0?.route === "COURT") router.push(`/cases/${ev.evaluation_id}?tab=pipeline`);
    } catch (e) {
      toast.push({ message: (e as Error).message, variant: "error", dismissAfter: 6000 });
    }
  }

  if (!data?.data.length) return null;
  return (
    <>
      <MenuButton {...menu} variant="primary">
        Send test event <ChevronDownIcon decorative />
      </MenuButton>
      <Menu {...menu} aria-label="Demo scenarios">
        {data.data.map((s) => (
          <MenuItem key={s.name} {...menu} onClick={() => send(s)}>
            <span><strong>{s.name.replaceAll("_", " ")}</strong> — {s.description}</span>
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}

