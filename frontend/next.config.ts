import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server output used by the Docker image.
  output: "standalone",
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
