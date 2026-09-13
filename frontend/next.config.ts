import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle with only the node_modules actually
  // used at runtime. This is what frontend/Dockerfile's final stage copies —
  // without it the image build fails, and with it the image is far smaller
  // than shipping the whole node_modules tree.
  //
  // It has no effect on `npm run dev`.
  output: "standalone",
};

export default nextConfig;
