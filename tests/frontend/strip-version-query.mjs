/**
 * Node's ESM resolver rejects `./data.js?v=0.12.1`. The browser uses that query
 * to bust the module cache. Tests strip it before resolve.
 */
export async function resolve(specifier, context, nextResolve) {
  const query = specifier.indexOf("?");
  if (query === -1) return nextResolve(specifier, context);
  return nextResolve(specifier.slice(0, query), context);
}
