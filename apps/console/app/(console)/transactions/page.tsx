"use client";

import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Input } from "@twilio-paste/core/input";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Drawer } from "@/components/Drawer";
import { JsonView } from "@/components/JsonView";
import { SendTestEvent } from "@/components/SendTestEvent";
import { PageHeader, Panel } from "@/components/Shell";
import { PFraud, StatusBadge } from "@/components/StatusBadge";
import { usePoll } from "@/lib/api";
import { money, time } from "@/lib/format";
import type { Evaluation, Page } from "@/lib/types";

const ROUTE: Record<string, ["success" | "error" | "new", string]> = {
  EXIT_APPROVE: ["success", "Tier 0 · approve"],
  EXIT_BLOCK: ["error", "Tier 0 · block"],
  COURT: ["new", "Sent to court"],
};

export default function TransactionsPage() {
  const router = useRouter();
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Evaluation | null>(null);
  const [raw, setRaw] = useState(true);
  const { data } = usePoll<Page<Evaluation>>("evaluations?limit=100", paused ? 0 : 2000);
  const rows = useMemo(() => {
    const q = filter.toLowerCase();
    return (data?.data ?? []).filter((e) => !q || [e.user_id, e.transaction_id, e.merchant, e.verdict ?? ""].some((s) => s.toLowerCase().includes(q)));
  }, [data, filter]);

  return (
    <>
      <PageHeader title="Transactions" description="Live debugger: every incoming transaction with its Tier 0 score and routing."
        actions={<>
          <Button variant="secondary" onClick={() => setPaused(!paused)}>{paused ? "Resume stream" : "Pause stream"}</Button>
          <SendTestEvent />
        </>} />
      <Panel title={<Box display="flex" alignItems="center" columnGap="space30">
          <span style={{ width: 8, height: 8, borderRadius: 4, background: paused ? "#8891aa" : "#14b053", display: "inline-block" }} />
          {paused ? "Paused" : "Live"}
        </Box>}
        actions={<Box width="size30"><Input type="search" aria-label="Filter" placeholder="Filter by user, txn, merchant, verdict" value={filter} onChange={(e) => setFilter(e.target.value)} /></Box>}>
        <div className="clickable-rows"><Table scrollHorizontally>
          <THead>
            <Tr><Th>Time</Th><Th>Transaction</Th><Th>User</Th><Th textAlign="right">Amount</Th><Th>Merchant</Th><Th>Tier 0</Th><Th>Routing</Th><Th>Status</Th></Tr>
          </THead>
          <TBody>
            {rows.map((e) => (
              <Tr key={e.evaluation_id} onClick={() => setOpen(e)}>
                <Td><Text as="span" fontSize="fontSize20" color="colorTextWeak">{time(e.created_at)}</Text></Td>
                <Td><code>{e.transaction_id}</code></Td>
                <Td>{e.user_id}</Td>
                <Td textAlign="right">{money(e.amount, e.currency)}</Td>
                <Td>{e.merchant}</Td>
                <Td><PFraud value={e.tier0?.score ?? null} /></Td>
                <Td>{e.tier0 ? <Badge as="span" size="small" variant={ROUTE[e.tier0.route][0]}>{ROUTE[e.tier0.route][1]}</Badge> : "—"}</Td>
                <Td><StatusBadge status={e.status} verdict={e.verdict} /></Td>
              </Tr>
            ))}
            {rows.length === 0 ? <Tr><Td colSpan={8}><Text as="p" color="colorTextWeak">Waiting for events… use “Send test event”.</Text></Td></Tr> : null}
          </TBody>
        </Table></div>
      </Panel>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.transaction_id ?? ""}
        actions={<>
          <Button variant="secondary" size="small" onClick={() => setRaw(!raw)}>{raw ? "Show enriched" : "Show raw"}</Button>
          {open ? <Button variant="primary" size="small" onClick={() => router.push(`/cases/${open.evaluation_id}`)}>Open case</Button> : null}
        </>}>
        {open ? <JsonView maxHeight="80vh" value={raw ? {
          transaction_id: open.transaction_id, user_id: open.user_id, amount: open.amount, currency: open.currency, merchant: open.merchant,
        } : open} /> : null}
      </Drawer>
    </>
  );
}
