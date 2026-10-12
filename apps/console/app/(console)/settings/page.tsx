"use client";

import { Alert } from "@twilio-paste/core/alert";
import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { HelpText } from "@twilio-paste/core/help-text";
import { Input } from "@twilio-paste/core/input";
import { Label } from "@twilio-paste/core/label";
import { Modal, ModalBody, ModalFooter, ModalFooterActions, ModalHeader, ModalHeading } from "@twilio-paste/core/modal";
import { Radio, RadioGroup } from "@twilio-paste/core/radio-group";
import { Option, Select } from "@twilio-paste/core/select";
import { Switch } from "@twilio-paste/core/switch";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import { useEffect, useState } from "react";

import { useToast } from "@/app/providers";
import { Kpi, KpiGrid } from "@/components/Kpi";
import { PageHeader, Panel, useMe } from "@/components/Shell";
import { api, usePoll } from "@/lib/api";
import { ago, usd } from "@/lib/format";
import type { Member, Role } from "@/lib/types";

interface SettingsView {
  workspace: { id: string; name: string; region: string; plan: string; created_at: string; settings: { pii_masking: boolean } };
  sso: { google: boolean };
}

const ROLES: { value: Role; label: string; help: string }[] = [
  { value: "ADMIN", label: "Admin", help: "Everything, including keys, members, policies and settings" },
  { value: "ANALYST", label: "Analyst", help: "Review cases, override verdicts, send test events" },
  { value: "VIEWER", label: "Viewer", help: "Read-only; phone numbers, IPs and emails are masked" },
];

export default function SettingsPage() {
  const me = useMe();
  const toast = useToast();
  const admin = me?.role === "ADMIN";
  const { data, reload } = usePoll<SettingsView>("settings");
  const { data: members, reload: reloadMembers } = usePoll<{ data: Member[] }>(admin ? "members" : null);
  const { data: usage } = usePoll<any>("stats/overview?hours=720");
  const [name, setName] = useState("");
  const [adding, setAdding] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("ANALYST");

  useEffect(() => { if (data) setName(data.workspace.name); }, [data]);

  async function run(action: () => Promise<unknown>, ok: string, after: () => void) {
    try {
      await action();
      toast.push({ message: ok, variant: "success", dismissAfter: 3000 });
      after();
    } catch (e) {
      toast.push({ message: (e as Error).message, variant: "error", dismissAfter: 6000 });
    }
  }

  const patch = (body: object, ok: string) =>
    run(() => api("settings", { method: "PATCH", body: JSON.stringify(body) }), ok, reload);

  const addMember = () =>
    run(() => api("members", { method: "POST", body: JSON.stringify({ email: email.trim(), role }) }),
      `Added ${email.trim()}`, () => { setAdding(false); setEmail(""); reloadMembers(); });

  const ws = data?.workspace;
  return (
    <>
      <PageHeader title="Settings" description="Workspace, members and roles, sign-in and privacy." />

      <Panel title="Workspace">
        <Box display="grid" style={{ gridTemplateColumns: "minmax(0, 360px) 1fr", gap: 24 }}>
          <Box>
            <Label htmlFor="ws-name">Name</Label>
            <Box display="flex" columnGap="space30">
              <Input id="ws-name" type="text" value={name} disabled={!admin} onChange={(e) => setName(e.target.value)} />
              {admin ? <Button variant="secondary" disabled={!name.trim() || name === ws?.name}
                onClick={() => patch({ name: name.trim() }, "Workspace renamed")}>Save</Button> : null}
            </Box>
          </Box>
          <Box display="flex" columnGap="space90">
            <Box><Text as="div" color="colorTextWeak" fontSize="fontSize20">Workspace ID</Text><code>{ws?.id}</code></Box>
            <Box><Text as="div" color="colorTextWeak" fontSize="fontSize20">Region</Text><Text as="span">{ws?.region}</Text></Box>
            <Box><Text as="div" color="colorTextWeak" fontSize="fontSize20">Plan</Text><Text as="span">{ws?.plan}</Text></Box>
          </Box>
        </Box>
      </Panel>

      <Panel title="Members & roles" actions={admin ? <Button variant="primary" size="small" onClick={() => setAdding(true)}>Add member</Button> : null}>
        {!admin ? (
          <Alert variant="neutral"><Text as="span">Only workspace admins can manage members.</Text></Alert>
        ) : (
          <Table>
            <THead><Tr><Th>Member</Th><Th>Role</Th><Th>Added by</Th><Th>Last sign-in</Th><Th /></Tr></THead>
            <TBody>
              {(members?.data ?? []).map((m) => (
                <Tr key={m.id}>
                  <Td><Text as="div" fontWeight="fontWeightSemibold">{m.name ?? m.email}</Text>
                    {m.name ? <Text as="div" color="colorTextWeak" fontSize="fontSize20">{m.email}</Text> : null}</Td>
                  <Td>
                    <Box width="size20">
                      <Select value={m.role} aria-label={`Role for ${m.email}`}
                        onChange={(e) => run(() => api(`members/${m.id}`, { method: "PATCH", body: JSON.stringify({ role: e.target.value }) }),
                          `${m.email} is now ${e.target.value.toLowerCase()}`, reloadMembers)}>
                        {ROLES.map((r) => <Option key={r.value} value={r.value}>{r.label}</Option>)}
                      </Select>
                    </Box>
                  </Td>
                  <Td>{m.added_by ?? "—"}</Td>
                  <Td>{m.last_login_at ? ago(m.last_login_at) : <Badge as="span" size="small" variant="neutral">Invited</Badge>}</Td>
                  <Td textAlign="right">
                    <Button variant="destructive_link" size="small"
                      onClick={() => run(() => api(`members/${m.id}`, { method: "DELETE" }), `Removed ${m.email}`, reloadMembers)}>Remove</Button>
                  </Td>
                </Tr>
              ))}
              {members && !members.data.length ? (
                <Tr><Td colSpan={5}><Text as="span" color="colorTextWeak">No members yet. Add a Google account to let someone sign in.</Text></Td></Tr>
              ) : null}
            </TBody>
          </Table>
        )}
      </Panel>

      <Panel title="Sign-in">
        <Box display="flex" alignItems="center" columnGap="space30" marginBottom="space30">
          <Text as="span" fontWeight="fontWeightSemibold">Google</Text>
          {data?.sso.google ? <Badge as="span" variant="success" size="small">Enabled</Badge> : <Badge as="span" variant="neutral" size="small">Not configured</Badge>}
        </Box>
        <Text as="p" color="colorTextWeak">
          Members sign in with the Google account of their listed email. Sessions last 12 hours and end immediately when a
          member is removed or their role changes. Bank systems keep using API keys from Sources.
        </Text>
      </Panel>

      <Panel title="Privacy">
        <Switch checked={ws?.settings.pii_masking ?? true} disabled={!admin}
          onChange={(e) => patch({ pii_masking: e.target.checked }, e.target.checked ? "PII masking on" : "PII masking off")}>
          Mask PII for viewers
        </Switch>
        <HelpText>Phone numbers, IP addresses and emails are masked in every API response and live stream a Viewer receives.</HelpText>
      </Panel>

      <Panel title="Usage (30 days)">
        <KpiGrid>
          <Kpi label="Evaluations" value={usage?.evaluations ?? "—"} />
          <Kpi label="Courtroom cases" value={usage?.sent_to_court ?? "—"} />
          <Kpi label="Subpoenas" value={usage?.subpoenas ?? "—"} />
          <Kpi label="Model cost" value={usd(usage?.total_cost_usd)} hint={`${usd(usage?.cost_per_courtroom_case_usd)} per case`} />
        </KpiGrid>
      </Panel>

      <Modal isOpen={adding} onDismiss={() => setAdding(false)} size="default" ariaLabelledby="add-member">
        <ModalHeader><ModalHeading as="h3" id="add-member">Add member</ModalHeading></ModalHeader>
        <ModalBody>
          <Label htmlFor="m-email" required>Google account email</Label>
          <Input id="m-email" type="email" value={email} placeholder="analyst@bank.com" onChange={(e) => setEmail(e.target.value)} />
          <Box marginTop="space60">
            <RadioGroup name="role" legend="Role" value={role} onChange={(v) => setRole(v as Role)}>
              {ROLES.map((r) => <Radio key={r.value} id={`role-${r.value}`} value={r.value} helpText={r.help}>{r.label}</Radio>)}
            </RadioGroup>
          </Box>
        </ModalBody>
        <ModalFooter><ModalFooterActions>
          <Button variant="secondary" onClick={() => setAdding(false)}>Cancel</Button>
          <Button variant="primary" onClick={addMember} disabled={!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())}>Add</Button>
        </ModalFooterActions></ModalFooter>
      </Modal>
    </>
  );
}
