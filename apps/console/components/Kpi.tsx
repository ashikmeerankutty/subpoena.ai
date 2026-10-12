"use client";

import { Box } from "@twilio-paste/core/box";
import { Text } from "@twilio-paste/core/text";
import type { ReactNode } from "react";

export function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: string }) {
  return (
    <Box backgroundColor="colorBackgroundBody" borderRadius="borderRadius30" borderWidth="borderWidth10"
      borderStyle="solid" borderColor="colorBorderWeaker" padding="space60" boxShadow="shadowLow">
      <Text as="div" fontSize="fontSize20" color="colorTextWeak" fontWeight="fontWeightMedium">{label}</Text>
      <Text as="div" fontSize="fontSize70" fontWeight="fontWeightBold" marginTop="space20"
        style={{ color: tone, fontVariantNumeric: "tabular-nums" }}>{value}</Text>
      {hint ? <Text as="div" fontSize="fontSize20" color="colorTextWeak" marginTop="space10">{hint}</Text> : null}
    </Box>
  );
}

export function KpiGrid({ children }: { children: ReactNode }) {
  return (
    <Box display="grid" columnGap="space50" rowGap="space50"
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))" }}>
      {children}
    </Box>
  );
}
