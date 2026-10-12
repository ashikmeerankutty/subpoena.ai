"use client";

import { Box } from "@twilio-paste/core/box";
import { Option, Select } from "@twilio-paste/core/select";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { SendTestEvent } from "@/components/SendTestEvent";
import { PageHeader, Panel } from "@/components/Shell";
import { PFraud, StatusBadge } from "@/components/StatusBadge";
import { usePoll } from "@/lib/api";
import { ago, money, usd } from "@/lib/format";
import type { Evaluation, Page } from "@/lib/types";

const FILTERS: Record<string, string> = {
  all: "", court: "", awaiting: "status=AWAITING_TESTIMONY", escalated: "status=ESCALATED",
  blocked: "verdict=BLOCK", approved: "verdict=APPROVE", appealed: "status=APPEALED",
};

export default function CasesPage() {
  const router = useRouter();
  const [view, setView] = useState("court");
  const { data } = usePoll<Page<Evaluation>>(`evaluations?limit=200&${FILTERS[view]}`, 3000);
  const rows = (data?.data ?? []).filter((e) => view !== "court" || e.tier0?.route === "COURT");
  return (
    <>
      <PageHeader title="Cases" description="The docket: every evaluation, its status and the courtroom's ruling."
        actions={<SendTestEvent />} />
      <Panel title={`${rows.length} cases`} actions={
        <Box width="size30">
          <Select aria-label="Saved view" value={view} onChange={(e) => setView(e.target.value)}>
            <Option value="court">Sent to court</Option>
            <Option value="all">All evaluations</Option>
            <Option value="awaiting">Awaiting testimony</Option>
            <Option value="escalated">Escalated (analyst queue)</Option>
            <Option value="blocked">Blocked</Option>
            <Option value="approved">Approved</Option>
            <Option value="appealed">Overridden by analyst</Option>
          </Select>
        </Box>}>
        <div className="clickable-rows"><Table scrollHorizontally>
          <THead><Tr>
            <Th>Case</Th><Th>Txn</Th><Th>User</Th><Th textAlign="right">Amount</Th><Th>Merchant</Th>
            <Th>Status</Th><Th>p_fraud</Th><Th textAlign="right">Cost</Th><Th>Opened</Th>
          </Tr></THead>
          <TBody>
            {rows.map((e) => (
              <Tr key={e.evaluation_id} onClick={() => router.push(`/cases/${e.evaluation_id}`)}>
                <Td><code>{e.evaluation_id}</code></Td>
                <Td><code>{e.transaction_id}</code></Td>
                <Td>{e.user_id}</Td>
                <Td textAlign="right">{money(e.amount, e.currency)}</Td>
                <Td>{e.merchant}</Td>
                <Td><StatusBadge status={e.status} verdict={e.verdict} /></Td>
                <Td><PFraud value={e.p_fraud} /></Td>
                <Td textAlign="right">{usd(e.cost_usd)}</Td>
                <Td><Text as="span" color="colorTextWeak" fontSize="fontSize20">{ago(e.created_at)}</Text></Td>
              </Tr>
            ))}
            {rows.length === 0 ? <Tr><Td colSpan={9}><Text as="p" color="colorTextWeak">No cases in this view.</Text></Td></Tr> : null}
          </TBody>
        </Table></div>
      </Panel>
    </>
  );
}
