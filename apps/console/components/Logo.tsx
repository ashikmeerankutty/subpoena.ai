import { useId } from "react";

/** The mark: a courthouse inside a speech bubble, i.e. the court that asks the witness. */
export function LogoMark({ size = 32 }: { size?: number }) {
  const id = useId();
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" style={{ flexShrink: 0 }}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#ff5466" />
          <stop offset="1" stopColor="#c8102e" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="10" fill={`url(#${id})`} />
      <path d="M13 9h14a5 5 0 0 1 5 5v8a5 5 0 0 1-5 5h-8l-6 4.5V27a5 5 0 0 1-5-5v-8a5 5 0 0 1 5-5z" fill="#fff" />
      <path d="M20 12.2l7.6 4H12.4zM14.1 17.4h2.3v5.2h-2.3zm4.75 0h2.3v5.2h-2.3zm4.75 0h2.3v5.2h-2.3zM12.4 23.3h15.2v1.8H12.4z"
        fill="#d91c35" />
    </svg>
  );
}

export function Wordmark({ size = 18, inverse = false }: { size?: number; inverse?: boolean }) {
  return (
    <span style={{ fontSize: size, fontWeight: 700, letterSpacing: "-0.02em", color: inverse ? "#fff" : "#121c2d" }}>
      Subpoena<span style={{ color: inverse ? "#ff7a88" : "#d91c35" }}>.ai</span>
    </span>
  );
}

export function Logo({ size = 32, inverse = false }: { size?: number; inverse?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: size * 0.35 }}>
      <LogoMark size={size} />
      <Wordmark size={size * 0.6} inverse={inverse} />
    </span>
  );
}
