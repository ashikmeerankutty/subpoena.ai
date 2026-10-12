"use client";

import { Button } from "@twilio-paste/core/button";
import { Heading } from "@twilio-paste/core/heading";
import { Label } from "@twilio-paste/core/label";
import { Modal, ModalBody, ModalFooter, ModalFooterActions, ModalHeader, ModalHeading } from "@twilio-paste/core/modal";
import { Option, Select } from "@twilio-paste/core/select";
import { TextArea } from "@twilio-paste/core/textarea";
import { useState } from "react";

import { useToast } from "@/app/providers";
import { api } from "@/lib/api";
import type { Evaluation, Verdict } from "@/lib/types";

export function OverrideModal({ ev, open, onClose, onDone }: {
  ev: Evaluation; open: boolean; onClose: () => void; onDone: (e: Evaluation) => void;
}) {
  const toast = useToast();
  const [verdict, setVerdict] = useState<Verdict>(ev.verdict === "APPROVE" ? "BLOCK" : "APPROVE");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      const out = await api<Evaluation>(`evaluations/${ev.evaluation_id}/override`, {
        method: "POST", body: JSON.stringify({ verdict, reason }),
      });
      toast.push({ message: `Verdict changed to ${verdict}`, variant: "success", dismissAfter: 4000 });
      onDone(out);
      onClose();
    } catch (e) {
      toast.push({ message: (e as Error).message, variant: "error", dismissAfter: 6000 });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal isOpen={open} onDismiss={onClose} size="default" ariaLabelledby="override-heading">
      <ModalHeader><ModalHeading as="h3" id="override-heading">Override verdict</ModalHeading></ModalHeader>
      <ModalBody>
        <Heading as="h4" variant="heading60">Current verdict: {ev.verdict ?? "pending"}</Heading>
        <Label htmlFor="verdict">New verdict</Label>
        <Select id="verdict" value={verdict} onChange={(e) => setVerdict(e.target.value as Verdict)}>
          <Option value="APPROVE">Approve</Option>
          <Option value="BLOCK">Block</Option>
          <Option value="HOLD">Hold</Option>
        </Select>
        <Label htmlFor="reason" required>Reason (becomes a training label)</Label>
        <TextArea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Chargeback received; customer confirmed fraud by phone" />
      </ModalBody>
      <ModalFooter><ModalFooterActions>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="destructive" onClick={submit} loading={busy} disabled={reason.trim().length < 3}>Override</Button>
      </ModalFooterActions></ModalFooter>
    </Modal>
  );
}
