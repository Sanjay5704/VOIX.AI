// Writes static-host config next to the build (Cloudflare Pages / Netlify format):
//   dist/_redirects  SPA fallback
//   dist/_headers    security headers + a CSP whose connect-src allows the API origin
// The API origin comes from VITE_API_BASE_URL (same-origin when empty).
import { writeFileSync } from "node:fs";

const api = process.env.VITE_API_BASE_URL ? new URL(process.env.VITE_API_BASE_URL).origin : "";
// Downloads may be redirected to presigned object-storage URLs (Cloudflare R2).
const storage = process.env.VOIX_STORAGE_ORIGIN || "https://*.r2.cloudflarestorage.com";

const csp = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' https://fonts.googleapis.com",
  "font-src https://fonts.gstatic.com",
  "img-src 'self' data: blob:",
  "media-src 'self' blob:",
  `connect-src 'self' ${api} ${storage}`.replace(/\s+/g, " ").trim(),
  "object-src 'none'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
].join("; ");

writeFileSync("dist/_redirects", "/* /index.html 200\n");
writeFileSync(
  "dist/_headers",
  `/*
  Content-Security-Policy: ${csp}
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), geolocation=()
/assets/*
  Cache-Control: public, max-age=31536000, immutable
`,
);
console.log(`static config written (connect-src: 'self' ${api} ${storage})`);
