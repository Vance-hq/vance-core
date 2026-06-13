import type { Metadata } from "next";
import "./globals.css";
import HealthBar from "./components/HealthBar";

export const metadata: Metadata = {
  title: "Vance HQ",
  description: "Real-time Vance agent control dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-surface-0 min-h-screen">
        <HealthBar />
        <main className="px-4 pb-8 pt-4 max-w-screen-2xl mx-auto">{children}</main>
      </body>
    </html>
  );
}
