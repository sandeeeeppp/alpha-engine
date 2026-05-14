import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Disable gzip compression — it buffers SSE chunks before sending
  compress: false,
};

export default nextConfig;
