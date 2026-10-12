"use client";

import { Box } from "@twilio-paste/core/box";

export function JsonView({ value, maxHeight = "420px" }: { value: unknown; maxHeight?: string }) {
  return (
    <Box as="pre" tabIndex={0} backgroundColor="colorBackgroundInverse" color="colorTextInverse" borderRadius="borderRadius30"
      padding="space50" margin="space0" overflow="auto" fontSize="fontSize20" lineHeight="lineHeight20"
      style={{ maxHeight, fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}>
      {JSON.stringify(value, null, 2)}
    </Box>
  );
}
