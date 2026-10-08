import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output: the Dockerfile copies only .next/standalone +
  // .next/static into the final image, not the whole node_modules tree.
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
