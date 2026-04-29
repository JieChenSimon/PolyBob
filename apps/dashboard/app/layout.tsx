import type { Metadata } from "next";
import "./globals.css";
import PrimaryNav from "@/components/PrimaryNav";

export const metadata: Metadata = {
  title: "PolyBob Workbench",
  description: "Personal market research and paper execution workbench",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        <PrimaryNav />
        {children}
      </body>
    </html>
  );
}
