from __future__ import annotations

from typing import List


class ParseError(ValueError):
    pass


def split_args(line: str) -> List[str]:
    line = (line or "").strip()
    if not line:
        return []

    tokens = []
    buf = []
    i = 0
    in_quote = False
    quote_char = ""
    while i < len(line):
        ch = line[i]
        if in_quote:
            if ch == "\\" and i + 1 < len(line) and line[i + 1] == quote_char:
                buf.append(quote_char)
                i += 2
                continue
            if ch == quote_char:
                in_quote = False
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue
        if ch in ('"', "'"):
            in_quote = True
            quote_char = ch
            i += 1
            continue
        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1

    if in_quote:
        raise ParseError("Unclosed quoted string")
    if buf:
        tokens.append("".join(buf))
    return tokens


__all__ = ["split_args", "ParseError"]
