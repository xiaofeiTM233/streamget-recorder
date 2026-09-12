import type { NextConfig } from "next";

// 开发态走 dev server 代理到后端；生产构建为纯静态导出，由 FastAPI 托管
const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = isDev
  ? {
      trailingSlash: true,
      async rewrites() {
        const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
        return [
          { source: "/api/:path*", destination: `${backend}/api/:path*` },
          { source: "/docs", destination: `${backend}/api/docs` },
        ];
      },
    }
  : {
      output: "export",
      trailingSlash: true,
      images: { unoptimized: true },
    };

export default nextConfig;
