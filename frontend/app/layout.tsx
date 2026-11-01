import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || "Yatra";

export const metadata: Metadata = {
  title: { default: APP_NAME, template: `%s · ${APP_NAME}` },
  description: "Explore public exoplanet observations and analyse light curves, with full provenance.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">Skip to content</a>
        <div className="app-shell">
          <Nav appName={APP_NAME} />
          <div className="content-shell"><main id="main">{children}</main>
            <footer>Archive data are retrieved on demand. Algorithmic candidates and model estimates are never confirmation of a planet.</footer>
          </div>
        </div>
      </body>
    </html>
  );
}
