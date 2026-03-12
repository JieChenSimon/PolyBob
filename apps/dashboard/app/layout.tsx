import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PolyBob Dashboard",
  description: "Real-time Polymarket market monitor",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        {children}
      </body>
    </html>
  );
}
