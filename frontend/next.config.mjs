/** The browser only talks to this Next server; /api is proxied to the FastAPI backend. */
const API_URL = process.env.API_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};
export default nextConfig;
