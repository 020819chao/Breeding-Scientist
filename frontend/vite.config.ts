import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  base: "/__frontend__/",
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/sessions": "http://127.0.0.1:8000",
      "/knowledge": "http://127.0.0.1:8000",
    },
  },
});
