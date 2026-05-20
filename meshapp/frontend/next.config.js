/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  output: "export",
  turbopack: {
    root: __dirname,
  },
};

module.exports = nextConfig;
