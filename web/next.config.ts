import type { NextConfig } from 'next';

// STATIC_EXPORT=1 (set by scripts/build-static.sh) builds the UI as static files for the
// Cloudflare Worker deployment; the Worker replaces app/api/* and middleware.ts there.
const staticExport = process.env.STATIC_EXPORT === '1';

const nextConfig: NextConfig = staticExport ? { output: 'export', images: { unoptimized: true } } : {};

export default nextConfig;
