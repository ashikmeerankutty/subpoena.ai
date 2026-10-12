"use client";

import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Text } from "@twilio-paste/core/text";

import { money } from "@/lib/format";
import type { ReceiptCheck } from "@/lib/types";

const RESULT = {
  MATCH: { variant: "success", label: "Receipt matches" },
  PARTIAL: { variant: "warning", label: "Partly matches" },
  MISMATCH: { variant: "error", label: "Receipt does not match" },
  NOT_A_RECEIPT: { variant: "neutral", label: "Not a receipt" },
  UNREADABLE: { variant: "neutral", label: "Unreadable" },
} as const;

const mark = (ok: boolean | null) => (ok == null ? "—" : ok ? "✓" : "✗");

/** Receipt photo next to what was read from it and how it compares with the transaction. */
export function ReceiptCard({ check, expected }: {
  check: ReceiptCheck;
  expected?: { merchant: string; amount: string | number; currency: string; date: string };
}) {
  const r = RESULT[check.result];
  const rows: [string, string | null, string | undefined, boolean | null][] = [
    ["Merchant", check.merchant, expected?.merchant, check.merchant_match],
    ["Total", check.amount ? `${check.amount} ${check.currency ?? ""}` : null,
      expected ? money(expected.amount, expected.currency) : undefined, check.amount_match],
    ["Date", check.date, expected?.date.slice(0, 10), check.date_match],
  ];
  return (
    <Box display="flex" columnGap="space60" alignItems="flex-start">
      <a href={`/api/v1/media/${check.media_id}`} target="_blank" rel="noreferrer">
        <img src={`/api/v1/media/${check.media_id}`} alt="Receipt photo from the witness" width={120}
          style={{ borderRadius: 6, border: "1px solid #e1e3ea", display: "block" }} />
      </a>
      <Box flexGrow={1}>
        <Badge as="span" variant={r.variant}>{r.label}</Badge>
        <Box as="table" marginTop="space30" style={{ borderCollapse: "collapse", fontSize: 13 }}>
          <tbody>
            <tr><Text as="th" fontSize="fontSize20" color="colorTextWeak" textAlign="left" paddingRight="space50" fontWeight="fontWeightNormal"> </Text>
              <Text as="th" fontSize="fontSize20" color="colorTextWeak" textAlign="left" paddingRight="space50" fontWeight="fontWeightNormal">On the receipt</Text>
              {expected ? <Text as="th" fontSize="fontSize20" color="colorTextWeak" textAlign="left" paddingRight="space50" fontWeight="fontWeightNormal">Transaction</Text> : null}
              <th /></tr>
            {rows.map(([label, seen, want, ok]) => (
              <tr key={label}>
                <Text as="td" fontWeight="fontWeightSemibold" paddingRight="space50">{label}</Text>
                <Text as="td" paddingRight="space50">{seen ?? "not visible"}</Text>
                {expected ? <Text as="td" paddingRight="space50" color="colorTextWeak">{want}</Text> : null}
                <Text as="td" color={ok == null ? "colorTextWeak" : ok ? "colorTextSuccess" : "colorTextError"} fontWeight="fontWeightBold">{mark(ok)}</Text>
              </tr>
            ))}
          </tbody>
        </Box>
        {check.order_reference ? <Text as="p" fontSize="fontSize20" color="colorTextWeak" marginTop="space20">Order {check.order_reference}</Text> : null}
        {check.reasons.length ? <Text as="p" fontSize="fontSize20" color="colorTextWeak" marginTop="space20">{check.reasons.join(" · ")}</Text> : null}
      </Box>
    </Box>
  );
}
