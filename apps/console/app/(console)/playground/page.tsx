"use client";

import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { HelpText } from "@twilio-paste/core/help-text";
import { Input } from "@twilio-paste/core/input";
import { Label } from "@twilio-paste/core/label";
import { Option, OptionGroup, Select } from "@twilio-paste/core/select";
import { Text } from "@twilio-paste/core/text";
import { CopyIcon } from "@twilio-paste/icons/esm/CopyIcon";
import { RefreshIcon } from "@twilio-paste/icons/esm/RefreshIcon";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { useToast } from "@/app/providers";
import { PageHeader, Panel } from "@/components/Shell";
import { usePoll } from "@/lib/api";
import { ENDPOINTS, PARAM, curl, harvest, params, type Endpoint, type Method } from "@/lib/playground";

interface Scenario { name: string; description: string; request: Record<string, any> }
interface Result {
  status: number; ms: number; size: number; type: string; text: string;
  json: unknown; method: Method; path: string; at: number; streaming?: boolean;
}
interface HistoryItem { method: Method; path: string; body: string | null; status: number; ms: number; at: number }

const METHOD_COLOR: Record<Method, string> = { GET: "#0263e0", POST: "#1a9e55", PATCH: "#c25700", DELETE: "#cf2d4f" };
const HISTORY_KEY = "playground.history";

const store = {
  get<T>(k: string, fallback: T): T {
    try { const v = localStorage.getItem(k); return v ? (JSON.parse(v) as T) : fallback; } catch { return fallback; }
  },
  set(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

function freshScenario(s: Scenario | undefined): string {
  if (!s) return "{}";
  const suffix = Math.random().toString(36).slice(2, 8);
  return JSON.stringify({ ...s.request, transaction_id: `${s.request.transaction_id}_${suffix}`, options: { sync_timeout_ms: 8000 } }, null, 2);
}

interface SseEvent { id: string; type: string; data: Record<string, any> | null; raw: string }

/** Split a server-sent-events body into its complete events. */
function parseSse(text: string): SseEvent[] {
  return text.split(/\n\n/).filter((b) => b.trim()).map((block) => {
    const field = (k: string) => block.split("\n").filter((l) => l.startsWith(`${k}:`)).map((l) => l.slice(k.length + 1).trim()).join("\n");
    let data: Record<string, any> | null = null;
    try { data = JSON.parse(field("data")); } catch { /* end marker or partial */ }
    return { id: field("id"), type: field("event") || "message", data, raw: block };
  });
}

function fill(path: string, values: Record<string, string>): string {
  return path.replace(PARAM, (_, k: string) => encodeURIComponent(values[k] ?? `{${k}}`));
}

/** Minimal JSON highlighting: keys, strings, numbers, literals. Escapes first. */
function highlight(json: string) {
  const esc = json.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  return esc.replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (m, str, colon, lit, num) =>
      str ? `<span class="${colon ? "j-key" : "j-str"}">${str}</span>${colon ?? ""}`
        : lit ? `<span class="j-lit">${lit}</span>` : num ? `<span class="j-num">${num}</span>` : m,
  );
}

export default function PlaygroundPage() {
  const toast = useToast();
  const router = useRouter();
  const { data: scen } = usePoll<{ data: Scenario[] }>("demo/scenarios");
  const scenarios = useMemo(() => scen?.data ?? [], [scen]);

  const [endpoint, setEndpoint] = useState<Endpoint>(ENDPOINTS[0]);
  const [scenario, setScenario] = useState("auto_parts_deadlock");
  const [path, setPath] = useState(ENDPOINTS[0].path);
  const [values, setValues] = useState<Record<string, string>>({});
  const [body, setBody] = useState("");
  const [idem, setIdem] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [apiUrl, setApiUrl] = useState("https://<your-api>");
  const [raw, setRaw] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const out = useRef<HTMLDivElement | null>(null);
  const abort = useRef<AbortController | null>(null);
  const restoring = useRef<HistoryItem | null>(null);

  useEffect(() => {
    setHistory(store.get<HistoryItem[]>(HISTORY_KEY, []));
    fetch("/api/auth/config").then((r) => r.json()).then((c: { api_url?: string }) => c.api_url && setApiUrl(c.api_url)).catch(() => {});
    return () => abort.current?.abort();
  }, []);

  // Selecting an endpoint (or a scenario) resets the request to its template.
  useEffect(() => {
    setPath(endpoint.path);
    setIdem(endpoint.idempotent ? crypto.randomUUID() : "");
    if (endpoint.scenario) setBody(freshScenario(scenarios.find((s) => s.name === scenario)));
    else setBody(endpoint.body ? JSON.stringify(endpoint.body, null, 2) : "");
    const h = restoring.current;
    if (h) {
      restoring.current = null;
      setPath(h.path);
      if (h.body) setBody(h.body);
    }
  }, [endpoint, scenario, scenarios]);

  const hasBody = endpoint.method !== "GET" && endpoint.method !== "DELETE";
  const bodyError = useMemo(() => {
    if (!hasBody || !body.trim()) return null;
    try { JSON.parse(body); return null; } catch (e) { return (e as Error).message; }
  }, [body, hasBody]);
  const names = params(path);
  const missing = names.filter((n) => !values[n]);
  const resolved = fill(path, values);
  const canSend = !busy && !bodyError && missing.length === 0;

  function remember(item: HistoryItem) {
    const next = [item, ...history].slice(0, 15);
    setHistory(next);
    store.set(HISTORY_KEY, next);
  }

  async function send() {
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setBusy(true);
    const started = performance.now();
    const sentBody = hasBody && body.trim() ? body : null;
    try {
      const res = await fetch(`/api/v1/${resolved}`, {
        method: endpoint.method,
        signal: ctl.signal,
        cache: "no-store",
        headers: {
          ...(sentBody ? { "content-type": "application/json" } : {}),
          ...(idem ? { "idempotency-key": idem } : {}),
          ...(endpoint.stream ? { accept: "text/event-stream" } : {}),
        },
        body: sentBody,
      });
      const type = res.headers.get("content-type") ?? "";
      const base = { status: res.status, type, method: endpoint.method, path: resolved, at: Date.now() };
      if (type.includes("text/event-stream") && res.body) {
        // Log the stream when it opens: it may run until the verdict or be stopped by hand.
        remember({ method: endpoint.method, path: resolved, body: null, status: res.status, ms: Math.round(performance.now() - started), at: Date.now() });
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let text = "";
        setResult({ ...base, ms: Math.round(performance.now() - started), size: 0, text, json: null, streaming: true });
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          text += dec.decode(value, { stream: true });
          setResult({ ...base, ms: Math.round(performance.now() - started), size: text.length, text, json: null, streaming: true });
        }
        setResult({ ...base, ms: Math.round(performance.now() - started), size: text.length, text, json: null });
      } else {
        const text = await res.text();
        let json: unknown = null;
        try { json = text ? JSON.parse(text) : null; } catch { /* not JSON */ }
        setResult({ ...base, ms: Math.round(performance.now() - started), size: text.length, text, json });
        if (json) setValues((v) => harvest(json, v));
        remember({ method: endpoint.method, path: resolved, body: sentBody, status: res.status, ms: Math.round(performance.now() - started), at: Date.now() });
      }
      // A retried POST with the same key returns the stored response; a new attempt needs a new key.
      if (endpoint.idempotent) setIdem(crypto.randomUUID());
      if (endpoint.scenario) setBody(freshScenario(scenarios.find((s) => s.name === scenario)));
    } catch (e) {
      if ((e as Error).name === "AbortError") setResult((r) => (r ? { ...r, streaming: false } : r));
      else toast.push({ message: (e as Error).message, variant: "error", dismissAfter: 5000 });
    } finally {
      setBusy(false);
    }
  }

  function restore(h: HistoryItem) {
    const ep = ENDPOINTS.find((e) => e.method === h.method && new RegExp(`^${e.path.split("?")[0].replace(PARAM, "[^/]+")}(\\?|$)`).test(h.path));
    if (ep && ep !== endpoint) {
      restoring.current = h; // applied after the endpoint's template loads
      setEndpoint(ep);
    } else {
      setPath(h.path);
      if (h.body) setBody(h.body);
    }
  }

  function copy(text: string, what: string) {
    navigator.clipboard.writeText(text).then(
      () => toast.push({ message: `${what} copied`, variant: "success", dismissAfter: 2000 }),
      () => toast.push({ message: "Copy failed", variant: "error", dismissAfter: 3000 }),
    );
  }

  const groups = [...new Set(ENDPOINTS.map((e) => e.group))];
  const sse = result?.type.includes("text/event-stream") ? parseSse(result.text) : null;
  // Follow a live stream like a terminal.
  useEffect(() => {
    if (result?.streaming && out.current) out.current.scrollTop = out.current.scrollHeight;
  }, [result]);
  const ev = result?.json as Record<string, any> | null;
  const caseId = ev && typeof ev === "object" && typeof ev.evaluation_id === "string" ? ev.evaluation_id : null;

  return (
    <>
      <PageHeader title="API Playground"
        description="Call the Subpoena.ai API as your Console session, with your role's permissions. Requests are real and land in this workspace." />
      <div className="pg-grid">
        <Panel title="Request">
          <Box display="grid" rowGap="space50">
            <Box>
              <Label htmlFor="ep">Endpoint</Label>
              <Select id="ep" value={endpoint.id} onChange={(e) => setEndpoint(ENDPOINTS.find((x) => x.id === e.target.value)!)}>
                {groups.map((g) => (
                  <OptionGroup key={g} label={g}>
                    {ENDPOINTS.filter((e) => e.group === g).map((e) => <Option key={e.id} value={e.id}>{e.method}  {e.title}</Option>)}
                  </OptionGroup>
                ))}
              </Select>
              <HelpText>{endpoint.description}</HelpText>
            </Box>

            {endpoint.scenario && scenarios.length ? (
              <Box>
                <Label htmlFor="sc">Sample transaction</Label>
                <Select id="sc" value={scenario} onChange={(e) => setScenario(e.target.value)}>
                  {scenarios.map((s) => <Option key={s.name} value={s.name}>{s.name.replaceAll("_", " ")} — {s.description}</Option>)}
                </Select>
                <HelpText>Each send gets a fresh transaction_id and Idempotency-Key.</HelpText>
              </Box>
            ) : null}

            <Box>
              <Label htmlFor="path">URL</Label>
              <Box display="flex" alignItems="center" columnGap="space30">
                <span className="pg-method" style={{ background: METHOD_COLOR[endpoint.method] }}>{endpoint.method}</span>
                <Box flexGrow={1}>
                  <Input id="path" type="text" value={path} onChange={(e) => setPath(e.target.value)} insertBefore={<Text as="span" color="colorTextWeak" fontFamily="fontFamilyCode" fontSize="fontSize20">/v1/</Text>} />
                </Box>
              </Box>
            </Box>

            {names.length ? (
              <Box display="grid" columnGap="space40" rowGap="space40" style={{ gridTemplateColumns: "1fr 1fr" }}>
                {names.map((n) => (
                  <Box key={n}>
                    <Label htmlFor={`p-${n}`} required>{n}</Label>
                    <Input id={`p-${n}`} type="text" value={values[n] ?? ""} placeholder={n === "evaluation_id" ? "eval_…" : n === "subpoena_id" ? "sbp_…" : ""}
                      onChange={(e) => setValues({ ...values, [n]: e.target.value.trim() })} />
                  </Box>
                ))}
                <Box style={{ gridColumn: "span 2" }}><HelpText>Filled in automatically from earlier responses.</HelpText></Box>
              </Box>
            ) : null}

            <Box>
              <Text as="div" fontWeight="fontWeightSemibold" fontSize="fontSize30" marginBottom="space20">Headers</Text>
              <div className="pg-headers">
                <span>Authorization</span><span className="pg-muted">your Console session (added by the server, never sent to the browser)</span>
                {idem ? <>
                  <span>Idempotency-Key</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <code>{idem}</code>
                    <Button variant="secondary_icon" size="reset" onClick={() => setIdem(crypto.randomUUID())}><RefreshIcon decorative={false} title="New key" /></Button>
                  </span>
                </> : null}
                {hasBody ? <><span>Content-Type</span><span>application/json</span></> : null}
              </div>
            </Box>

            {hasBody ? (
              <Box>
                <Box display="flex" justifyContent="space-between" alignItems="baseline">
                  <Label htmlFor="body">Body</Label>
                  <Button variant="link" size="small" disabled={!!bodyError || !body.trim()} onClick={() => setBody(JSON.stringify(JSON.parse(body), null, 2))}>Format</Button>
                </Box>
                <textarea id="body" className="pg-code pg-editor" spellCheck={false} value={body} onChange={(e) => setBody(e.target.value)}
                  rows={Math.min(22, Math.max(6, body.split("\n").length + 1))} aria-invalid={!!bodyError} />
                {bodyError ? <HelpText variant="error">Invalid JSON: {bodyError}</HelpText> : null}
              </Box>
            ) : null}

            <Box display="flex" columnGap="space40" alignItems="center">
              <Button variant="primary" onClick={send} disabled={!canSend} loading={busy && !result?.streaming}>
                Send request
              </Button>
              {busy && result?.streaming ? <Button variant="secondary" onClick={() => abort.current?.abort()}>Stop stream</Button> : null}
              <Button variant="secondary" onClick={() => copy(curl(apiUrl, endpoint.method, resolved, hasBody && body.trim() ? JSON.stringify(JSON.parse(body || "{}")) : null, idem || null), "curl command")}
                disabled={!!bodyError}>
                <CopyIcon decorative /> Copy as curl
              </Button>
              {missing.length ? <Text as="span" fontSize="fontSize20" color="colorTextWeak">Fill in {missing.join(", ")}</Text> : null}
            </Box>
          </Box>
        </Panel>

        <Box display="grid" rowGap="space60" style={{ alignContent: "start", minWidth: 0 }}>
          <Panel title="Response" actions={result ? (
            <Box display="flex" alignItems="center" columnGap="space30">
              <Badge as="span" size="small" variant={result.status < 300 ? "success" : result.status < 500 ? "warning" : "error"}>
                {result.status}{result.streaming ? " · streaming" : ""}
              </Badge>
              <Text as="span" fontSize="fontSize20" color="colorTextWeak">{result.ms} ms · {(result.size / 1024).toFixed(1)} KB</Text>
              <Button variant="secondary_icon" size="reset" onClick={() => copy(result.json ? JSON.stringify(result.json, null, 2) : result.text, "Response")}>
                <CopyIcon decorative={false} title="Copy response" />
              </Button>
            </Box>
          ) : null}>
            {!result ? (
              <Box paddingY="space100" textAlign="center">
                <Text as="p" color="colorTextWeak">Pick an endpoint and send a request. Try <strong>Evaluate a transaction</strong> with the
                  auto-parts sample: it goes to court and comes back 202 awaiting the witness.</Text>
              </Box>
            ) : (
              <>
                <Text as="div" fontFamily="fontFamilyCode" fontSize="fontSize20" color="colorTextWeak" marginBottom="space30">
                  {result.method} /v1/{result.path}
                </Text>
                {caseId ? (
                  <Box display="flex" flexWrap="wrap" columnGap="space30" rowGap="space20" marginBottom="space40" alignItems="center">
                    {ev?.status ? <Badge as="span" size="small" variant="neutral">{ev.status}{ev.verdict ? ` · ${ev.verdict}` : ""}</Badge> : null}
                    <Button variant="secondary" size="small" onClick={() => router.push(`/cases/${caseId}?tab=pipeline`)}>Open case</Button>
                    <Button variant="secondary" size="small" onClick={() => setEndpoint(ENDPOINTS.find((e) => e.id === "stream-events")!)}>Stream its events</Button>
                    {ev?.subpoena ? <Button variant="secondary" size="small" onClick={() => setEndpoint(ENDPOINTS.find((e) => e.id === "witness-reply")!)}>Reply as witness</Button> : null}
                  </Box>
                ) : null}
                {sse ? (
                  <Box display="flex" justifyContent="space-between" alignItems="center" marginBottom="space30">
                    <Text as="span" fontSize="fontSize20" color="colorTextWeak">{sse.filter((e) => e.data).length} events{result.streaming ? " so far" : ""}</Text>
                    <Button variant="link" size="small" onClick={() => setRaw(!raw)}>{raw ? "Show as events" : "Show raw"}</Button>
                  </Box>
                ) : null}
                {sse && !raw ? (
                  <div className="pg-events" ref={out}>
                    {sse.map((e, i) => e.data ? (
                      <div key={`${e.id}-${i}`} className="pg-event">
                        <button type="button" onClick={() => setOpen(open === e.data!.event_id ? null : e.data!.event_id)}>
                          <span className="pg-seq">{e.data.sequence}</span>
                          <span className="pg-type">{e.data.type}</span>
                          <span className="pg-muted">{e.data.from_agent}{e.data.to_agent ? ` → ${e.data.to_agent}` : ""}</span>
                          {e.data.latency_ms != null ? <span className="pg-muted">{Math.round(e.data.latency_ms)} ms</span> : <span />}
                        </button>
                        {open === e.data.event_id ? (
                          <pre className="pg-code" dangerouslySetInnerHTML={{ __html: highlight(JSON.stringify(e.data.payload, null, 2)) }} />
                        ) : null}
                      </div>
                    ) : e.type === "end" ? <div key={`end-${i}`} className="pg-end">Stream ended</div> : null)}
                  </div>
                ) : (
                  <div className="pg-output-wrap" ref={out}>
                    <pre className="pg-code pg-output" dangerouslySetInnerHTML={{
                      __html: result.json != null ? highlight(JSON.stringify(result.json, null, 2)) : highlight(result.text || "(empty body)"),
                    }} />
                  </div>
                )}
              </>
            )}
          </Panel>

          <Panel title="History" actions={history.length ? <Button variant="link" size="small" onClick={() => { setHistory([]); store.set(HISTORY_KEY, []); }}>Clear</Button> : null}>
            {history.length === 0 ? <Text as="p" color="colorTextWeak" fontSize="fontSize20">Requests you send appear here (kept in this browser only).</Text> : (
              <div className="pg-history">
                {history.map((h) => (
                  <button key={h.at} type="button" onClick={() => restore(h)}>
                    <span className="pg-method small" style={{ background: METHOD_COLOR[h.method] }}>{h.method}</span>
                    <code>/v1/{h.path}</code>
                    <span className={h.status < 300 ? "ok" : "bad"}>{h.status}</span>
                    <span className="pg-muted">{h.ms} ms</span>
                  </button>
                ))}
              </div>
            )}
          </Panel>
        </Box>
      </div>
    </>
  );
}
