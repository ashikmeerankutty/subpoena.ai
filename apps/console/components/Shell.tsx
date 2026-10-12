"use client";

import { Avatar } from "@twilio-paste/core/avatar";
import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Option, Select } from "@twilio-paste/core/select";
import {
  Sidebar, SidebarBody, SidebarHeader, SidebarHeaderLabel, SidebarNavigation, SidebarNavigationItem,
  SidebarPushContentWrapper,
} from "@twilio-paste/core/sidebar";
import { Text } from "@twilio-paste/core/text";
import { Topbar, TopbarActions } from "@twilio-paste/core/topbar";
import { ProductContactCenterTasksIcon } from "@twilio-paste/icons/esm/ProductContactCenterTasksIcon";
import { ProductDebuggerIcon } from "@twilio-paste/icons/esm/ProductDebuggerIcon";
import { ProductDestinationsIcon } from "@twilio-paste/icons/esm/ProductDestinationsIcon";
import { ProductEventLibraryIcon } from "@twilio-paste/icons/esm/ProductEventLibraryIcon";
import { ProductHomeIcon } from "@twilio-paste/icons/esm/ProductHomeIcon";
import { ProductLogsIcon } from "@twilio-paste/icons/esm/ProductLogsIcon";
import { ProductSettingsIcon } from "@twilio-paste/icons/esm/ProductSettingsIcon";
import { ProductMessagingIcon } from "@twilio-paste/icons/esm/ProductMessagingIcon";
import { ProductProtocolsIcon } from "@twilio-paste/icons/esm/ProductProtocolsIcon";
import { ProductSourcesIcon } from "@twilio-paste/icons/esm/ProductSourcesIcon";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import type { Me } from "@/lib/types";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);

const NAV = [
  { href: "/", label: "Overview", icon: ProductHomeIcon },
  { href: "/sources", label: "Sources", icon: ProductSourcesIcon },
  { href: "/destinations", label: "Destinations", icon: ProductDestinationsIcon },
  { href: "/transactions", label: "Transactions", icon: ProductDebuggerIcon },
  { href: "/cases", label: "Cases", icon: ProductContactCenterTasksIcon },
  { href: "/subpoenas", label: "Subpoenas", icon: ProductMessagingIcon },
  { href: "/policies", label: "Policies", icon: ProductProtocolsIcon },
  { href: "/precedents", label: "Precedents", icon: ProductEventLibraryIcon },
  { href: "/audit-log", label: "Audit Log", icon: ProductLogsIcon },
  { href: "/settings", label: "Settings", icon: ProductSettingsIcon },
];

interface WorkspaceChoice { id: string; name: string; role: string }

const IDS = { main: "main", nav: "nav", top: "topbar" };

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceChoice[]>([]);

  useEffect(() => {
    api<Me>("me").then(setMe).catch(() => router.replace("/login"));
  }, [router]);

  useEffect(() => {
    if (me?.principal?.type !== "MEMBER") return;
    api<{ workspaces: WorkspaceChoice[] }>("sessions/current").then((s) => setWorkspaces(s.workspaces)).catch(() => undefined);
  }, [me]);

  async function switchTo(workspaceId: string) {
    const res = await fetch("/api/session/switch", { method: "POST", body: JSON.stringify({ workspace_id: workspaceId }) });
    if (res.ok) location.href = "/";
  }

  async function signOut() {
    await fetch("/api/session", { method: "DELETE" });
    router.replace("/login");
  }

  const selected = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <MeContext.Provider value={me}>
      <Sidebar variant="default" mainContentSkipLinkID={IDS.main} sidebarNavigationSkipLinkID={IDS.nav}
        topbarSkipLinkID={IDS.top}>
        <SidebarHeader>
          <Box display="flex" alignItems="center" columnGap="space30">
            <img src="/favicon.svg" alt="" width={28} height={28} />
            <SidebarHeaderLabel>Subpoena.ai</SidebarHeaderLabel>
          </Box>
        </SidebarHeader>
        <SidebarBody>
          <SidebarNavigation aria-label="Console" id={IDS.nav}>
            {NAV.map(({ href, label, icon: Icon }) => (
              <SidebarNavigationItem key={href} href={href} selected={selected(href)}
                icon={<Icon decorative />}
                onClick={(e) => { e.preventDefault(); router.push(href); }}>
                {label}
              </SidebarNavigationItem>
            ))}
          </SidebarNavigation>
        </SidebarBody>
      </Sidebar>
      <SidebarPushContentWrapper variant="default">
        <Topbar id={IDS.top}>
          <TopbarActions justify="start">
            <Box display="flex" alignItems="center" columnGap="space30">
              <Box width="sizeSquare80" height="sizeSquare80" borderRadius="borderRadius20" backgroundColor="colorBackgroundBrandStrong"
                display="flex" alignItems="center" justifyContent="center">
                <Text as="span" color="colorTextInverse" fontWeight="fontWeightBold" fontSize="fontSize30">◆</Text>
              </Box>
              {workspaces.length > 1 && me ? (
                <Box width="size30">
                  <Select value={me.workspace.id} onChange={(e) => switchTo(e.target.value)} aria-label="Workspace">
                    {workspaces.map((w) => <Option key={w.id} value={w.id}>{w.name}</Option>)}
                  </Select>
                </Box>
              ) : (
                <Text as="span" fontWeight="fontWeightSemibold">{me?.workspace.name ?? "…"}</Text>
              )}
              {me ? <Badge as="span" variant="neutral" size="small">{me.role}</Badge> : null}
            </Box>
          </TopbarActions>
          <TopbarActions justify="end">
            {me ? (
              <Text as="span" color="colorTextWeak" fontSize="fontSize20">
                {me.principal?.type === "MEMBER" ? me.principal.email : `${me.key.name} · ${me.key.prefix}…`}
              </Text>
            ) : null}
            <Button variant="link" onClick={signOut}>Sign out</Button>
            <Avatar size="sizeIcon70" name={me?.principal?.name ?? me?.key.name ?? "?"} />
          </TopbarActions>
        </Topbar>
        <Box as="main" id={IDS.main} padding="space90" backgroundColor="colorBackground" minHeight="100vh">
          {children}
        </Box>
      </SidebarPushContentWrapper>
    </MeContext.Provider>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <Box display="flex" alignItems="flex-start" justifyContent="space-between" marginBottom="space70" columnGap="space50">
      <Box>
        <Text as="h1" fontSize="fontSize70" fontWeight="fontWeightBold" lineHeight="lineHeight70">{title}</Text>
        {description ? <Text as="p" color="colorTextWeak" marginTop="space20">{description}</Text> : null}
      </Box>
      {actions ? <Box display="flex" columnGap="space30" flexShrink={0}>{actions}</Box> : null}
    </Box>
  );
}

export function Panel({ title, children, actions }: { title?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <Box backgroundColor="colorBackgroundBody" borderRadius="borderRadius30" borderWidth="borderWidth10"
      borderStyle="solid" borderColor="colorBorderWeaker" boxShadow="shadowLow" marginBottom="space60">
      {title || actions ? (
        <Box display="flex" justifyContent="space-between" alignItems="center" paddingX="space60" paddingY="space40"
          borderBottomWidth="borderWidth10" borderBottomStyle="solid" borderBottomColor="colorBorderWeaker">
          <Text as="h2" fontWeight="fontWeightSemibold" fontSize="fontSize40">{title}</Text>
          <Box display="flex" columnGap="space30">{actions}</Box>
        </Box>
      ) : null}
      <Box padding="space60">{children}</Box>
    </Box>
  );
}
