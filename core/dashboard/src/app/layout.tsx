import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Vance HQ",
  description: "Vance agent status dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <style>{`
          *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
          body { font-family: 'SF Mono', 'Fira Code', monospace; background: #0d0d0d; color: #e0e0e0; min-height: 100vh; }
          a { color: inherit; text-decoration: none; }
        `}</style>
      </head>
      <body>{children}</body>
    </html>
  );
}
