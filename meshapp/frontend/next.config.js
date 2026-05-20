/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  distDir: process.env.MESH_NEXT_DIST_DIR || ".next",
  output: "export",
  turbopack: {
    root: __dirname,
  },
};

module.exports = nextConfig;
