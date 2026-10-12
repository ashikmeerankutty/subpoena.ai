"use client";

import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import Link from "next/link";

import { ago } from "@/lib/format";
import type { Precedent } from "@/lib/types";

const SOURCE: Record<Precedent["source"], string> = { SEED: "Library", CASE: "Ruling", OVERRIDE: "Analyst override" };

export function PrecedentTable({ rows, onRemove }: { rows: Precedent[]; onRemove?: (p: Precedent) => void }) {
  const searched = rows.some((p) => p.similarity != null);
  return (
    <Table>
      <THead><Tr>{searched ? <Th>Similarity</Th> : null}<Th>Precedent</Th><Th>Ruling</Th><Th>Source</Th><Th>Case</Th>{onRemove ? <Th /> : null}</Tr></THead>
      <TBody>
        {rows.map((p) => (
          <Tr key={p.id}>
            {searched ? (
              <Td>
                <Box display="flex" alignItems="center" columnGap="space30">
                  <Box width="size10" height="sizeSquare20" backgroundColor="colorBackgroundStrong" borderRadius="borderRadius20" overflow="hidden">
                    <Box height="100%" backgroundColor="colorBackgroundPrimary" style={{ width: `${Math.round((p.similarity ?? 0) * 100)}%` }} />
                  </Box>
                  <Text as="span" fontSize="fontSize20">{(p.similarity ?? 0).toFixed(2)}</Text>
                </Box>
              </Td>
            ) : null}
            <Td><Text as="span">{p.summary}</Text>
              {p.tags.length ? <Box marginTop="space20" display="flex" flexWrap="wrap" columnGap="space20" rowGap="space20">
                {p.tags.slice(0, 6).map((t) => <Badge key={t} as="span" size="small" variant="neutral">{t}</Badge>)}</Box> : null}</Td>
            <Td><Badge as="span" variant={p.label === "FRAUD" ? "error" : "success"}>{p.label}</Badge>
              <Text as="div" fontSize="fontSize20" color="colorTextWeak">{p.verdict}</Text></Td>
            <Td><Text as="span" fontSize="fontSize20">{SOURCE[p.source]}</Text><Text as="div" fontSize="fontSize20" color="colorTextWeak">{ago(p.created_at)}</Text></Td>
            <Td>{p.evaluation_id ? <Link href={`/cases/${p.evaluation_id}`}><code>{p.evaluation_id}</code></Link> : "—"}</Td>
            {onRemove ? <Td textAlign="right">{p.source !== "SEED" ? <Button size="small" variant="destructive_link" onClick={() => onRemove(p)}>Remove</Button> : null}</Td> : null}
          </Tr>
        ))}
      </TBody>
    </Table>
  );
}

