import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { IBM_Plex_Sans_Arabic, Inter } from "next/font/google";
import "./globals.css";

// next/font downloads the fonts at build time and serves them from the app
// (no request to Google from the browser; the CSP stays self-only). Inter has
// no Arabic letters, so the browser takes them from IBM Plex Sans Arabic.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const plexArabic = IBM_Plex_Sans_Arabic({
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-arabic",
});

export const metadata: Metadata = {
  title: "Media Manager",
  // Project links hold the media token in the path. Do not let a search
  // engine index them, and do not send them as a referrer.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${plexArabic.variable}`}>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
