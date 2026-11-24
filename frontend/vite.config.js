import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// React dev server on http://localhost:5173
// The dashboard talks directly to the Flask nodes (ports 5001-5003); the nodes send CORS headers.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, open: true },
});
