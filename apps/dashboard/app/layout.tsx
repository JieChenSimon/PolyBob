import type { Metadata } from "next";
import "./globals.css";
import PrimaryNav from "@/components/PrimaryNav";
import NavigationPerformanceMonitor from "@/components/NavigationPerformanceMonitor";
import { WorkbenchQueryProvider } from "@/lib/queryProvider";
import { WorkbenchStatusStrip } from "@/components/WorkbenchChrome";
import LanguageDocumentSync from "@/components/LanguageDocumentSync";

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
        <a href="#main-content" className="skip-link">
          跳转到主内容 / Skip to content
        </a>
        <WorkbenchQueryProvider>
          <NavigationPerformanceMonitor />
          <LanguageDocumentSync />
          <PrimaryNav />
          <WorkbenchStatusStrip />
          <div id="main-content" tabIndex={-1} className="outline-none">
            {children}
          </div>
        </WorkbenchQueryProvider>
      </body>
    </html>
  );
}
