"""A test double for macOS `textutil`, used only where the real tool is absent (Linux CI).

Run as a script it understands the two invocations the suite makes:
`textutil -convert txt -stdout FILE` and `textutil -convert rtf FILE -output OUT`. The RTF
reader covers what TextEdit writes and the fixtures use: groups, destinations to skip, `\\par`,
`\\line`, `\\tab`, `\\'hh` (cp1252) and `\\uN` escapes, and a backslash before a line break.
Plain text passes through unchanged, as the real tool treats a file without an RTF header.
It is stdlib-only because the generated launcher runs it in isolated mode.
"""

import re
import sys
from pathlib import Path

_SKIPPED_DESTINATIONS = {"fonttbl", "colortbl", "stylesheet", "info", "expandedcolortable"}
_WORD = re.compile(r"([a-zA-Z]+)(-?\d+)? ?")


def rtf_to_text(data: bytes) -> str:
    """The text of an RTF document, or of a plain-text file (UTF-8, optional BOM)."""
    if not data.startswith(b"{\\rtf"):
        return data.decode("utf-8-sig")
    source = data.decode("latin-1")
    out: list[str] = []
    skipping = [False]  # one flag per open group: its destination is not document text
    fallback = 0  # characters still to drop after a \uN escape
    i = 0
    while i < len(source):
        char = source[i]
        i += 1
        if fallback:
            fallback -= 1
            continue
        emit = ""
        if char == "{":
            skipping.append(skipping[-1])
        elif char == "}":
            if len(skipping) > 1:
                skipping.pop()
        elif char == "\\":
            nxt = source[i : i + 1]
            i += 1
            if nxt in ("\\", "{", "}"):
                emit = nxt
            elif nxt == "'":
                emit = bytes([int(source[i : i + 2], 16)]).decode("cp1252", errors="replace")
                i += 2
            elif nxt in ("\n", "\r"):
                if nxt == "\r" and source[i : i + 1] == "\n":
                    i += 1
                emit = "\n"
            elif nxt == "*":
                skipping[-1] = True
            elif nxt.isalpha():
                match = _WORD.match(source, i - 1)
                assert match is not None
                i = match.end()
                word, param = match.group(1), match.group(2)
                if word in _SKIPPED_DESTINATIONS:
                    skipping[-1] = True
                elif word in ("par", "line"):
                    emit = "\n"
                elif word == "tab":
                    emit = "\t"
                elif word == "u" and param is not None:
                    emit = chr(int(param) % 65536)
                    fallback = 1
        elif char not in "\r\n":
            emit = char
        if emit and not skipping[-1]:
            out.append(emit)
    return "".join(out).encode("utf-16", "surrogatepass").decode("utf-16")  # join pairs


def text_to_rtf(text: str) -> bytes:
    """A minimal RTF document holding `text`; non-ASCII becomes `\\uN?` escapes."""
    body: list[str] = []
    for char in text:
        if char in "\\{}":
            body.append("\\" + char)
        elif char == "\n":
            body.append("\\\n")
        elif char == "\t":
            body.append("\\tab ")
        elif ord(char) < 128:
            body.append(char)
        else:
            units = char.encode("utf-16-le")
            for k in range(0, len(units), 2):
                value = int.from_bytes(units[k : k + 2], "little")
                body.append(f"\\u{value - 65536 if value > 32767 else value}?")
    header = "{\\rtf1\\ansi\\ansicpg1252\\cocoartf2822\n{\\fonttbl\\f0\\fswiss Helvetica;}\n"
    return (header + "\\pard\\f0 " + "".join(body) + "}").encode("ascii")


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] != "-convert" or argv[1] not in ("txt", "rtf"):
        sys.stderr.write("fake textutil: unsupported arguments\n")
        return 2
    target, rest = argv[1], argv[2:]
    output = rest[rest.index("-output") + 1] if "-output" in rest else None
    files = [a for a in rest if a not in ("-stdout", "-output", output)]
    if len(files) != 1 or not Path(files[0]).is_file():
        sys.stderr.write("fake textutil: cannot read input\n")
        return 1
    try:
        text = rtf_to_text(Path(files[0]).read_bytes())
    except (UnicodeDecodeError, ValueError):
        sys.stderr.write("fake textutil: cannot interpret input\n")
        return 1
    result = text.encode("utf-8") if target == "txt" else text_to_rtf(text)
    if output is None:
        sys.stdout.buffer.write(result)
    else:
        Path(output).write_bytes(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
