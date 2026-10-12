"use client";

import { Box } from "@twilio-paste/core/box";
import { Input } from "@twilio-paste/core/input";
import { Text } from "@twilio-paste/core/text";
import { useEffect, useState } from "react";

import { useToast } from "@/app/providers";
import { PrecedentTable } from "@/components/PrecedentTable";
import { PageHeader, Panel, useMe } from "@/components/Shell";
import { api, usePoll } from "@/lib/api";
import type { Precedent } from "@/lib/types";

export default function PrecedentsPage() {
  const me = useMe();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);
  const path = query ? `precedents?q=${encodeURIComponent(query)}&limit=20` : "precedents?limit=100";
  const { data, reload } = usePoll<{ data: Precedent[]; meta: { total?: number; model: string } }>(path);

  async function remove(p: Precedent) {
    try {
      await api(`precedents/${p.id}`, { method: "DELETE" });
      toast.push({ message: "Precedent removed", variant: "warning", dismissAfter: 3000 });
      reload();
    } catch (e) {
      toast.push({ message: (e as Error).message, variant: "error", dismissAfter: 5000 });
    }
  }

  return (
    <>
      <PageHeader title="Precedents"
        description={<>Stare decisis: every courtroom ruling joins this library, and the Defense and Judge retrieve the most similar cases by embedding similarity{data ? <> (<code>{data.meta.model}</code>)</> : null}. Analyst overrides correct the record.</>} />
      <Panel>
        <Box marginBottom="space50" maxWidth="size70">
          <Input type="search" aria-label="Search precedents" placeholder='Describe a case, e.g. "late-night auto parts order from a new device"'
            value={q} onChange={(e) => setQ(e.target.value)} />
        </Box>
        {data ? (
          data.data.length ? <PrecedentTable rows={data.data} onRemove={me?.role === "ADMIN" ? remove : undefined} />
            : <Text as="p" color="colorTextWeak">No similar precedents.</Text>
        ) : null}
        {!query && data?.meta.total ? <Text as="p" color="colorTextWeak" fontSize="fontSize20" marginTop="space40">{data.meta.total} precedents in this workspace's library.</Text> : null}
      </Panel>
    </>
  );
}
