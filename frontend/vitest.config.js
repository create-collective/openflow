// Unit tests for the primitives, hooks and the api contract (tests/unit). Pages are not unit
// tested: they change with the restyle and are covered by the Playwright route walk instead.
//
//     npm test              (vitest run)
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["tests/setup.js"],
    include: ["tests/unit/**/*.test.{js,jsx}"],
  },
});
