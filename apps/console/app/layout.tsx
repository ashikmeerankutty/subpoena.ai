import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Courthouse Console · Subpoena.ai",
  description: "Multi-agent fraud courtroom: cases, pipeline transcripts and subpoenas.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
        />
        <link rel="icon" href="/favicon.svg" />
      </head>
      <body style={{ margin: 0 }}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
