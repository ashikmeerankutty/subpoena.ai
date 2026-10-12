"use client";

import { Theme } from "@twilio-paste/core/theme";
import { Toaster, useToaster } from "@twilio-paste/core/toast";
import { createContext, useContext, type ReactNode } from "react";

type Toast = ReturnType<typeof useToaster>;
const ToastContext = createContext<Toast | null>(null);

export function useToast(): Toast {
  const t = useContext(ToastContext);
  if (!t) throw new Error("useToast outside Providers");
  return t;
}

export function Providers({ children }: { children: ReactNode }) {
  const toaster = useToaster();
  return (
    <Theme.Provider theme="default">
      <ToastContext.Provider value={toaster}>
        <Toaster {...toaster} />
        {children}
      </ToastContext.Provider>
    </Theme.Provider>
  );
}
