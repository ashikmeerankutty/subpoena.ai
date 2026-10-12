"use client";

import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Heading } from "@twilio-paste/core/heading";
import { CloseIcon } from "@twilio-paste/icons/esm/CloseIcon";
import { useEffect, useId, useRef, type ReactNode } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

/** Segment-style right-side detail drawer. */
export function Drawer({
  open, title, onClose, children, width = "560px", actions,
}: {
  open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; width?: string; actions?: ReactNode;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  // Pages pass an inline onClose and re-render on every poll; only opening should move focus.
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open) return;
    // Modal dialog: focus moves in, Tab stays inside, and focus returns to the opener on close.
    const opener = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") return close.current();
      if (e.key !== "Tab" || !panel.current) return;
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); opener?.focus?.(); };
  }, [open]);
  if (!open) return null;
  return (
    <>
      <Box position="fixed" top="0" left="0" right="0" bottom="0" zIndex="zIndex80"
        backgroundColor="colorBackgroundOverlay" onClick={onClose} />
      <Box position="fixed" top="0" right="0" bottom="0" zIndex="zIndex90" backgroundColor="colorBackgroundBody"
        boxShadow="shadowElevation20" display="flex" flexDirection="column"
        role="dialog" aria-modal="true" aria-labelledby={titleId} ref={panel} tabIndex={-1}
        style={{ width, maxWidth: "100vw", outline: "none" }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" paddingX="space60" paddingY="space50"
          borderBottomWidth="borderWidth10" borderBottomStyle="solid" borderBottomColor="colorBorderWeaker">
          <Heading as="h2" variant="heading30" marginBottom="space0" id={titleId}>{title}</Heading>
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
