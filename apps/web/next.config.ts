import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  typedRoutes: false,
  // Produce a self-contained deploy bundle under .next/standalone that includes
  // only the minimum node_modules needed at runtime. ~10x smaller than copying
  // the full pnpm workspace tree into the runtime image. Required by the
  // Cloud Run Dockerfile in apps/web/Dockerfile.
  output: "standalone",
  // The standalone tracer walks up to find the workspace root so it can
  // hoist symlinked workspace deps (e.g. @uteki/shared-types) into the
  // standalone bundle. Without this, next build emits a warning and may
  // miss workspace package files.
  //
  // Note: in Next 15 this lived under `experimental.outputFileTracingRoot`.
  // Next 16 promoted it to the top level — see the migration warning the
  // build prints if you put it back under experimental.
  outputFileTracingRoot: path.join(__dirname, "..", ".."),
};

export default nextConfig;
