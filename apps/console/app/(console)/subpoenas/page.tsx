"use client";

import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Drawer } from "@/components/Drawer";
import { PageHeader, Panel, useMe } from "@/components/Shell";
import { StatusBadge } from "@/components/StatusBadge";
import { WitnessChat } from "@/components/WitnessChat";
import { usePoll } from "@/lib/api";
import { ago, channelName, money, seconds, time } from "@/lib/format";
import type { Subpoena } from "@/lib/types";

const STATE: Record<string, ["new" | "success" | "error" | "warning" | "neutral", string]> = {
  AWAITING_REPLY: ["new", "Awaiting reply"],
  ADMITTED: ["success", "Testimony admitted"],
  AUTH_FAILED: ["error", "Lookup failed (SIM swap)"],
  CODE_FAILED: ["error", "Code failed"],
  EXPIRED: ["warning", "Expired"],
};

export default function SubpoenasPage() {
  const router = useRouter();
  const me = useMe();
  const { data } = usePoll<{ data: Subpoena[] }>("subpoenas?limit=100", 2500);
  const [openId, setOpenId] = useState<string | null>(null);
  const open = data?.data.find((s) => s.id === openId) ?? null;
  return (
    <>
      <PageHeader title="Subpoenas" description="Questions sent to cardholders, witness authentication and testimony." />
      <Panel title={`${data?.data.length ?? 0} subpoenas`}>
        <div className="clickable-rows"><Table scrollHorizontally>
          <THead><Tr><Th>Sent</Th><Th>Witness</Th><Th>Channel</Th><Th>Question</Th><Th>State</Th><Th>Auth</Th><Th>Response time</Th><Th>Outcome</Th></Tr></THead>
          <TBody>
            {(data?.data ?? []).map((s) => {
              const [variant, label] = STATE[s.state] ?? ["neutral", s.state];
              const rt = s.responded_at ? (new Date(s.responded_at).getTime() - new Date(s.sent_at).getTime()) / 1000 : null;
              return (
                <Tr key={s.id} onClick={() => setOpenId(s.id)}>
                  <Td><Text as="span" fontSize="fontSize20" color="colorTextWeak">{ago(s.sent_at)}</Text></Td>
                  <Td>{s.user_id}<br /><Text as="span" fontSize="fontSize20" color="colorTextWeak">{s.phone}</Text></Td>
                  <Td>{channelName(s.channel)}</Td>
                  <Td><Text as="span" fontSize="fontSize20">{s.question}</Text></Td>
                  <Td><Badge as="span" size="small" variant={variant}>{label}</Badge></Td>
                  <Td>{s.state === "AUTH_FAILED" || s.state === "CODE_FAILED" ? "FAILED" : s.code_verified ? "PASSED" : "pending"}</Td>
                  <Td>{seconds(rt)}</Td>
                  <Td>{s.evaluation ? <StatusBadge status={s.evaluation.status} verdict={s.evaluation.verdict} /> : "—"}</Td>
                </Tr>
              );
            })}
            {!data?.data.length ? <Tr><Td colSpan={8}><Text as="p" color="colorTextWeak">No subpoenas yet. Send the “auto parts deadlock” test event.</Text></Td></Tr> : null}
          </TBody>
        </Table></div>
      </Panel>
      <Drawer open={!!open} onClose={() => setOpenId(null)} width="620px" title={open ? `Subpoena ${open.id}` : ""}
        actions={open ? <Button variant="secondary" size="small" onClick={() => router.push(`/cases/${open.evaluation_id}`)}>Open case</Button> : null}>
        {open ? (
          <Box>
            <Box display="grid" columnGap="space50" rowGap="space30" marginBottom="space60" style={{ gridTemplateColumns: "auto 1fr" }}>
              <Text as="span" color="colorTextWeak">Question</Text><Text as="span"><em>“{open.question}”</em></Text>
              <Text as="span" color="colorTextWeak">Transaction</Text>
              <Text as="span">{open.evaluation ? `${money(open.evaluation.amount, open.evaluation.currency)} at ${open.evaluation.merchant}` : open.evaluation_id}</Text>
              <Text as="span" color="colorTextWeak">Sent / expires</Text><Text as="span">{time(open.sent_at)} / {time(open.expires_at)}</Text>
              <Text as="span" color="colorTextWeak">Lookup</Text>
              <Text as="span">{open.lookup?.line_type ?? "—"} · {open.lookup?.carrier ?? ""} · SIM swap: {open.lookup?.last_sim_swap ? `${ago(open.lookup.last_sim_swap)}${open.lookup.recent_sim_swap ? " (recent!)" : ""}` : "none"}</Text>
              <Text as="span" color="colorTextWeak">Verify</Text><Text as="span">{open.code_verified ? "code verified" : `${open.code_attempts} attempt(s)`}</Text>
            </Box>
            <WitnessChat phone={open.phone} simulator={!!me?.simulator && open.state === "AWAITING_REPLY"} />
          </Box>
        ) : null}
      </Drawer>
    </>
  );
}
