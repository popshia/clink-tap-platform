import { execSync } from "node:child_process";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const git = (fmt) =>
  execSync(
    `git log -1 --oneline -E --format=${fmt} --date=short --grep='^(feat|fix|refactor)'`,
  )
    .toString()
    .trim();

export default defineConfig({
  define: {
    __COMMIT_DATE__: JSON.stringify(git("%cd")),
    __COMMIT_LOG__: JSON.stringify(git("%B")),
  },
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
      },
    },
  },
});
