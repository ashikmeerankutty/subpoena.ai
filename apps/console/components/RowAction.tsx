"use client";

import Link from "next/link";
import type { ReactNode } from "react";

/**
 * The keyboard and screen-reader way into a clickable table row: the row keeps its mouse click,
 * and this cell holds a real link or button that a Tab key and assistive tech can reach.
 */
export function RowAction({ href, onClick, label, children }: {
  href?: string; onClick?: () => void; label: string; children: ReactNode;
}) {
  // The row's own onClick would fire twice (or navigate twice) without this.
  const stop = (e: React.MouseEvent) => e.stopPropagation();
  return href ? (
    <Link href={href} className="row-action" aria-label={label} onClick={stop}>{children}</Link>
  ) : (
    <button type="button" className="row-action" aria-label={label} onClick={(e) => { stop(e); onClick?.(); }}>
      {children}
    </button>
  );
}
