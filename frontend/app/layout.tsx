import type { Metadata, Viewport } from "next";
import { absoluteUrl, brandName, defaultOgImage, homeSeo, siteName, siteUrl } from "@/lib/seo";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: homeSeo.title,
  description: homeSeo.description,
  keywords: homeSeo.keywords,
  applicationName: brandName,
  authors: [{ name: brandName, url: siteUrl }],
  creator: brandName,
  publisher: brandName,
  openGraph: {
    title: homeSeo.title,
    description: homeSeo.description,
    url: siteUrl,
    siteName,
    type: "website",
    images: [
      {
        url: defaultOgImage,
        width: 1600,
        height: 1000,
        alt: "DiamScore MLB optimizer dashboard with DFS lineup projections and slate analytics",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: homeSeo.title,
    description: homeSeo.description,
    images: [defaultOgImage],
  },
  alternates: {
    canonical: siteUrl,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
      "max-video-preview": -1,
    },
  },
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/diamscore-hero-analytics.png", type: "image/png" },
    ],
    apple: [{ url: "/diamscore-hero-analytics.png" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <script async src="https://www.googletagmanager.com/gtag/js?id=G-BV0VY80EVE" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());

            gtag('config', 'G-BV0VY80EVE');
          `,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
