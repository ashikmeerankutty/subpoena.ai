"use client";

import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Callout, CalloutHeading, CalloutText } from "@twilio-paste/core/callout";
import { Checkbox } from "@twilio-paste/core/checkbox";
import { HelpText } from "@twilio-paste/core/help-text";
import { Input } from "@twilio-paste/core/input";
import { Label } from "@twilio-paste/core/label";
import { Option, Select } from "@twilio-paste/core/select";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import { useEffect, useMemo, useState } from "react";

import { useToast } from "@/app/providers";
import { Drawer } from "@/components/Drawer";
import { PageHeader, Panel } from "@/components/Shell";
import { CATEGORIES, CONNECTORS, type Category, type Connector } from "@/lib/connectors";

// Previews are remembered in this browser only, and never with secret fields.
const STORAGE_KEY = "subpoena.connectors.preview";
type Saved = Record<string, { values: Record<string, string>; schedule: string; saved_at: string }>;

function loadSaved(): Saved {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Saved; } catch { return {}; }
}

/** Black or white initials, whichever contrasts more with the tile colour. */
function ink(hex: string) {
  const lin = (i: number) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const l = 0.2126 * lin(1) + 0.7152 * lin(3) + 0.0722 * lin(5);
  return 1.05 / (l + 0.05) >= (l + 0.05) / 0.05 ? "#ffffff" : "#121c2d";
}

function Logo({ c, size = 40 }: { c: Connector; size?: number }) {
  return (
    <Box display="flex" alignItems="center" justifyContent="center" borderRadius="borderRadius30" flexShrink={0} aria-hidden="true"
      style={{ width: size, height: size, background: c.color, color: ink(c.color), fontWeight: 700, fontSize: size * (c.initials.length > 2 ? 0.3 : 0.38) }}>
      {c.initials}
    </Box>
  );
}

export default function ConnectorsPage() {
  const toast = useToast();
  const [category, setCategory] = useState<Category | "All">("All");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Connector | null>(null);
  const [saved, setSaved] = useState<Saved>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [schedule, setSchedule] = useState("daily");
  const [backfill, setBackfill] = useState(true);

  useEffect(() => setSaved(loadSaved()), []);

  const shown = useMemo(() => CONNECTORS.filter((c) =>
    (category === "All" || c.category === category) &&
    (!query || `${c.name} ${c.category} ${c.brings.join(" ")}`.toLowerCase().includes(query.toLowerCase()))), [category, query]);
  const connected = CONNECTORS.filter((c) => c.live || saved[c.id]);

  function openConnector(c: Connector) {
    setOpen(c);
    setValues(saved[c.id]?.values ?? {});
    setSchedule(saved[c.id]?.schedule ?? (c.sync === "Streaming" ? "streaming" : c.sync === "One-off" ? "once" : "daily"));
    setBackfill(true);
  }

  function save(c: Connector) {
    const publicValues = Object.fromEntries(
      Object.entries(values).filter(([k]) => !c.fields.find((f) => f.key === k)?.secret));
    const next = { ...saved, [c.id]: { values: publicValues, schedule, saved_at: new Date().toISOString() } };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* private mode: keep it in memory */ }
    setSaved(next);
    setOpen(null);
    toast.push({ message: `${c.name} saved as a preview. Syncing isn't enabled in this prototype.`, variant: "neutral", dismissAfter: 5000 });
  }

  function remove(c: Connector) {
    const { [c.id]: _, ...rest } = saved;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(rest)); } catch { /* ignore */ }
    setSaved(rest);
    setOpen(null);
  }

  const preview = () => toast.push({ message: "Preview: this step isn't enabled in the prototype.", variant: "neutral", dismissAfter: 4000 });

  return (
    <>
      <PageHeader title="Connectors"
        description="Bring in customer history so the courtroom knows what's normal for each cardholder from day one." />

      <Box marginBottom="space60">
        <Callout variant="neutral">
          <CalloutHeading as="h2">Prototype preview</CalloutHeading>
          <CalloutText>
            BigQuery is live with the synthetic demo dataset the agents read today. The other connectors show the setup a bank
            would go through: saving one is remembered in this browser only, and no data is synced.
          </CalloutText>
        </Callout>
      </Box>

      <Panel title={`${connected.length} connected`}>
        <Table>
          <THead><Tr><Th>Source</Th><Th>Brings</Th><Th>Sync</Th><Th>Status</Th></Tr></THead>
          <TBody>
            {connected.map((c) => (
              <Tr key={c.id}>
                <Td>
                  <Box display="flex" alignItems="center" columnGap="space40">
                    <Logo c={c} size={32} />
                    <Box>
                      <button type="button" className="row-action" onClick={() => openConnector(c)}>{c.name}</button>
                      <Text as="div" fontSize="fontSize20" color="colorTextWeak">{c.live?.summary ?? c.category}</Text>
                    </Box>
                  </Box>
                </Td>
                <Td>{c.brings.join(", ")}</Td>
                <Td>{c.live ? "Read in place" : saved[c.id]?.schedule === "streaming" ? "Streaming" : saved[c.id]?.schedule === "once" ? "One-off backfill" : saved[c.id]?.schedule === "hourly" ? "Hourly" : "Daily"}</Td>
                <Td>{c.live
                  ? <Badge as="span" variant="success" size="small">Live</Badge>
                  : <Badge as="span" variant="neutral" size="small">Preview · not syncing</Badge>}</Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      </Panel>

      <Panel title="Catalog" actions={
        <Box width="size30">
          <Input type="search" aria-label="Search connectors" placeholder="Search connectors" value={query} onChange={(e) => setQuery(e.target.value)} />
        </Box>}>
        <Box display="flex" flexWrap="wrap" columnGap="space30" rowGap="space30" marginBottom="space60" role="group" aria-label="Filter by category">
          {(["All", ...CATEGORIES] as const).map((cat) => (
            <Button key={cat} size="small" variant={category === cat ? "primary" : "secondary"} aria-pressed={category === cat}
              onClick={() => setCategory(cat)}>{cat}</Button>
          ))}
        </Box>
        <Box display="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
          {shown.map((c) => (
            <Box key={c.id} as="button" type="button" onClick={() => openConnector(c)} display="flex" flexDirection="column" rowGap="space30"
              padding="space50" borderRadius="borderRadius30" borderWidth="borderWidth10" borderStyle="solid" borderColor="colorBorderWeaker"
              backgroundColor="colorBackgroundBody" cursor="pointer" textAlign="left" _hover={{ borderColor: "colorBorderPrimary", boxShadow: "shadowLow" }}>
              <Box display="flex" alignItems="center" columnGap="space40">
                <Logo c={c} />
                <Box minWidth="0px">
                  <Text as="div" fontWeight="fontWeightSemibold">{c.name}</Text>
                  <Text as="div" fontSize="fontSize20" color="colorTextWeak">{c.category} · {c.sync}</Text>
                </Box>
                {c.live ? <Box marginLeft="auto"><Badge as="span" variant="success" size="small">Live</Badge></Box>
                  : saved[c.id] ? <Box marginLeft="auto"><Badge as="span" variant="neutral" size="small">Preview</Badge></Box> : null}
              </Box>
              <Text as="p" fontSize="fontSize30" color="colorTextWeak">{c.tagline}</Text>
              <Box display="flex" flexWrap="wrap" columnGap="space20" rowGap="space20">
                {c.brings.map((b) => <Badge key={b} as="span" variant="decorative10" size="small">{b}</Badge>)}
              </Box>
            </Box>
          ))}
        </Box>
        {shown.length === 0 ? <Text as="p" color="colorTextWeak">No connectors match.</Text> : null}
      </Panel>

      <Panel title="How imported history is used">
        <Box as="ul" margin="space0" paddingLeft="space60" display="grid" rowGap="space30">
          <li><Text as="span"><strong>Baselines.</strong> Typical amounts, hours, devices, IPs and home location per customer feed the Tier 0 screen and the Clerk.</Text></li>
          <li><Text as="span"><strong>Expert witnesses.</strong> Device and IP history drive the Device and Geo experts; payees and shared devices build the Graph expert's links.</Text></li>
          <li><Text as="span"><strong>The witness.</strong> The customer's phone from the CRM or core system is where the Bailiff sends the subpoena.</Text></li>
          <li><Text as="span"><strong>Fraud labels.</strong> Confirmed fraud and chargebacks would seed the precedent library and give a ground truth for tuning policy thresholds.</Text></li>
        </Box>
      </Panel>

      <Drawer open={!!open} onClose={() => setOpen(null)} width="640px" title={open?.name ?? ""}
        actions={open && !open.live ? <>
          {saved[open.id] ? <Button variant="destructive_secondary" size="small" onClick={() => remove(open)}>Remove</Button> : null}
          <Button variant="secondary" size="small" onClick={preview}>Test connection</Button>
          <Button variant="primary" size="small" onClick={() => save(open)}>Save preview</Button>
        </> : null}>
        {open ? (
          <Box display="grid" rowGap="space60">
            <Box display="flex" columnGap="space40" alignItems="center">
              <Logo c={open} size={48} />
              <Box>
                <Text as="p">{open.tagline}</Text>
                <Box display="flex" flexWrap="wrap" columnGap="space20" rowGap="space20" marginTop="space20">
                  {open.brings.map((b) => <Badge key={b} as="span" variant="decorative10" size="small">{b}</Badge>)}
                </Box>
              </Box>
            </Box>

            {open.live ? (
              <Callout variant="success">
                <CalloutHeading as="h3">Live: {open.live.summary}</CalloutHeading>
                <CalloutText>{open.live.detail}</CalloutText>
              </Callout>
            ) : (
              <Callout variant="neutral">
                <CalloutText>Preview of the setup flow. Nothing is sent or synced, and secret fields are never stored.</CalloutText>
              </Callout>
            )}

            {!open.live ? (
              <Box>
                <Text as="h3" fontWeight="fontWeightSemibold" marginBottom="space40">1. Connect</Text>
                {open.oauth ? <Box marginBottom="space50"><Button variant="secondary" onClick={preview}>{open.oauth}</Button></Box> : null}
                <Box display="grid" rowGap="space50">
                  {open.fields.map((f) => {
                    const id = `cx-${open.id}-${f.key}`;
                    return (
                      <Box key={f.key}>
                        <Label htmlFor={id}>{f.label}</Label>
                        <Input id={id} type={f.secret ? "password" : "text"} placeholder={f.placeholder} autoComplete="off"
                          value={values[f.key] ?? ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                          aria-describedby={f.help ? `${id}-help` : undefined} />
                        {f.help ? <HelpText id={`${id}-help`}>{f.help}</HelpText> : null}
                      </Box>
                    );
                  })}
                </Box>
              </Box>
            ) : null}

            <Box>
              <Text as="h3" fontWeight="fontWeightSemibold" marginBottom="space40">{open.live ? "Field mapping" : "2. Map fields"}</Text>
              <Table>
                <THead><Tr><Th>{open.name} field</Th><Th>Subpoena.ai field</Th></Tr></THead>
                <TBody>
                  {open.mapping.map(([src, dst]) => (
                    <Tr key={src}><Td><code>{src}</code></Td><Td><code>{dst}</code></Td></Tr>
                  ))}
                </TBody>
              </Table>
            </Box>

            {!open.live ? (
              <Box>
                <Text as="h3" fontWeight="fontWeightSemibold" marginBottom="space40">3. Sync</Text>
                <Label htmlFor="cx-schedule">Schedule</Label>
                <Select id="cx-schedule" value={schedule} onChange={(e) => setSchedule(e.target.value)}>
                  {open.sync === "Streaming" ? <Option value="streaming">Streaming (as events arrive)</Option> : null}
                  <Option value="hourly">Hourly</Option>
                  <Option value="daily">Daily</Option>
                  <Option value="once">One-off backfill</Option>
                </Select>
                <Box marginTop="space40">
                  <Checkbox id="cx-backfill" checked={backfill} onChange={(e) => setBackfill(e.target.checked)}
                    helpText="Builds baselines for every customer before the first live payment.">
                    Backfill the last 90 days
                  </Checkbox>
                </Box>
              </Box>
            ) : null}
          </Box>
        ) : null}
      </Drawer>
    </>
  );
}
