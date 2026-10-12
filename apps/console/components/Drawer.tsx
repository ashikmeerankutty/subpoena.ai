"use client";

import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Heading } from "@twilio-paste/core/heading";
import { CloseIcon } from "@twilio-paste/icons/esm/CloseIcon";
import { useEffect, type ReactNode } from "react";

/** Segment-style right-side detail drawer. */
export function Drawer({
  open, title, onClose, children, width = "560px", actions,
}: {
  open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; width?: string; actions?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!open) return null;
  return (
    <>
      <Box position="fixed" top="0" left="0" right="0" bottom="0" zIndex="zIndex80"
        backgroundColor="colorBackgroundOverlay" onClick={onClose} />
      <Box position="fixed" top="0" right="0" bottom="0" zIndex="zIndex90" backgroundColor="colorBackgroundBody"
        boxShadow="shadowElevation20" display="flex" flexDirection="column" style={{ width, maxWidth: "100vw" }}
        role="dialog" aria-modal="true">
        <Box display="flex" alignItems="center" justifyContent="space-between" paddingX="space60" paddingY="space50"
          borderBottomWidth="borderWidth10" borderBottomStyle="solid" borderBottomColor="colorBorderWeaker">
          <Heading as="h2" variant="heading30" marginBottom="space0">{title}</Heading>
          <Box display="flex" columnGap="space30" alignItems="center">
            {actions}
            <Button variant="secondary_icon" size="reset" onClick={onClose}>
              <CloseIcon decorative={false} title="Close" />
            </Button>
          </Box>
        </Box>
        <Box padding="space60" overflowY="auto" flexGrow={1}>{children}</Box>
      </Box>
    </>
  );
}
