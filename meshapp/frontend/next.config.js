const path = require("path");

/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  distDir: process.env.MESH_NEXT_DIST_DIR || ".next",
  output: "export",
  turbopack: {
    root: path.join(__dirname, "../.."),
  },
};

module.exports = nextConfig;
