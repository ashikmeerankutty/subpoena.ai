export const money = (amount: string | number, currency = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(amount));

export const pct = (x: number | null | undefined, digits = 0) =>
  x == null ? "—" : `${(x * 100).toFixed(digits)}%`;

export const ago = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

export const time = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";

export const seconds = (s: number | null | undefined) =>
  s == null ? "—" : s < 60 ? `${s.toFixed(1)}s` : `${(s / 60).toFixed(1)}m`;

export const usd = (x: number | null | undefined) => (x == null ? "—" : `$${x.toFixed(x < 0.1 ? 4 : 2)}`);

export const title = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase().replaceAll("_", " ");
