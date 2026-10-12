import * as nodeModule from "node:module";

function resolve(specifier, context, nextResolve) {
  const query = specifier.indexOf("?");
  if (query === -1) return nextResolve(specifier, context);
  return nextResolve(specifier.slice(0, query), context);
}

if (typeof nodeModule.registerHooks === "function") {
  nodeModule.registerHooks({ resolve });
} else {
  await nodeModule.register("./strip-version-query.mjs", import.meta.url);
}
