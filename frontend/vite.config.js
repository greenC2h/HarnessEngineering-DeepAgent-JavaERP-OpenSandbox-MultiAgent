import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: Number(process.env.MYAGENT_FRONTEND_PORT || "4000"),
    strictPort: true,
    proxy: {
      "/auth": `http://127.0.0.1:${process.env.MYAGENT_BACKEND_PORT || "18000"}`,
      "/chat": `http://127.0.0.1:${process.env.MYAGENT_BACKEND_PORT || "18000"}`,
      "/history": `http://127.0.0.1:${process.env.MYAGENT_BACKEND_PORT || "18000"}`,
      "/async-tasks": `http://127.0.0.1:${process.env.MYAGENT_BACKEND_PORT || "18000"}`,
      "/visualizations": `http://127.0.0.1:${process.env.MYAGENT_BACKEND_PORT || "18000"}`,
      // 报告下载接口也在后端；否则 Vite 会把 /analysis/... 回退到 index.html。
      "/analysis": `http://127.0.0.1:${process.env.MYAGENT_BACKEND_PORT || "18000"}`,
    },
  },
});
