const path = require("path");

const apiProxyTarget = (process.env.NEXT_PUBLIC_MESH_API_URL || "http://127.0.0.1:8787").replace(/\/+$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  distDir: process.env.MESH_NEXT_DIST_DIR || ".next",
  output: "export",
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyTarget}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
