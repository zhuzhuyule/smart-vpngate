"""Tiny stdlib YAML loader for the config subset Smart VPNGate uses.

The project ships as *zero-dependency, pure standard library*. PyYAML is used
when present (it is more complete), but the runtime must not require it, so this
module provides a minimal fallback that understands exactly what
``config.example.yaml`` needs:

* nested mappings (``key: value`` / ``key:`` + indented block),
* block sequences (``- item``) and inline flow sequences (``[a, b, c]``),
* scalars: int, float, bool (``true``/``false``/``yes``/``no``),
  null (``null``/``~``), quoted and bare strings,
* ``#`` comments and blank lines.

It is intentionally small — not a general YAML parser. For anything richer,
install PyYAML and it will be used automatically.
"""

from __future__ import annotations

from typing import Any


def _scalar(token: str) -> Any:
    s = token.strip()
    if s == "":
        return None
    if (s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'"):
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _flow_list(token: str) -> list[Any]:
    inner = token.strip()[1:-1].strip()
    if not inner:
        return []
    return [_scalar(part) for part in inner.split(",")]


def _strip_comment(line: str) -> str:
    """Remove a trailing ``#`` comment (only when preceded by whitespace)."""
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1] in " \t":
                return line[:i]
    return line


def safe_load(text: str) -> Any:
    """Parse the supported YAML subset into Python objects."""
    cleaned: list[str] = []
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if line.strip():
            cleaned.append(line)
    if not cleaned:
        return None

    root: dict[str, Any] = {}
    # stack of (indent, container); root sits below any real indentation.
    stack: list[tuple[int, Any]] = [(-1, root)]

    i = 0
    while i < len(cleaned):
        line = cleaned[i]
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()

        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]

        if content.startswith("- ") or content == "-":
            if not isinstance(parent, list):
                raise ValueError(f"unexpected list item at line: {line!r}")
            parent.append(_scalar(content[1:].strip()) if content != "-" else None)
            i += 1
            continue

        if ":" not in content:
            raise ValueError(f"cannot parse YAML line: {line!r}")

        key, _, rest = content.partition(":")
        key, rest = key.strip(), rest.strip()
        if not isinstance(parent, dict):
            raise ValueError(f"unexpected mapping at line: {line!r}")

        if rest == "":
            # Container follows. Peek the next line to choose list vs map.
            nxt = cleaned[i + 1] if i + 1 < len(cleaned) else ""
            nxt_indent = (len(nxt) - len(nxt.lstrip(" "))) if nxt else -1
            if nxt and nxt_indent > indent and nxt.strip().startswith("-"):
                container: Any = []
            else:
                container = {}
            parent[key] = container
            stack.append((indent, container))
        elif rest.startswith("["):
            parent[key] = _flow_list(rest)
        else:
            parent[key] = _scalar(rest)
        i += 1

    return root
