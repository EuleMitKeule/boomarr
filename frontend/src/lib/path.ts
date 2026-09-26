export type PathKey = string | number;
export type Path = readonly PathKey[];

export function getIn(data: unknown, path: Path): any { // eslint-disable-line @typescript-eslint/no-explicit-any
  let node: any = data; // eslint-disable-line @typescript-eslint/no-explicit-any
  for (const key of path) {
    if (node === null || node === undefined) return undefined;
    node = node[key];
  }
  return node;
}

/** Immutable set; creates objects/arrays along the way. */
export function setIn<T>(data: T, path: Path, value: unknown): T {
  if (path.length === 0) return value as T;
  const [key, ...rest] = path;
  const container: any = Array.isArray(data) ? [...data] : { ...(data ?? {}) }; // eslint-disable-line @typescript-eslint/no-explicit-any
  const child = container[key as keyof typeof container];
  const next = child ?? (typeof rest[0] === "number" ? [] : {});
  if (rest.length === 0 && value === undefined && !Array.isArray(container)) {
    delete container[key as keyof typeof container];
  } else {
    container[key as keyof typeof container] = setIn(next, rest, value);
  }
  return container as T;
}

export function pathKey(path: Path): string {
  return path.join(".");
}

export function samePath(a: Path, b: Path): boolean {
  return a.length === b.length && a.every((part, i) => String(part) === String(b[i]));
}

export function startsWith(path: Path, prefix: Path): boolean {
  return prefix.length <= path.length && prefix.every((part, i) => String(part) === String(path[i]));
}
