"""A stdlib PNG reader and pixel comparison for screenshot baselines (no imaging dependency).

Playwright's ``to_have_screenshot`` belongs to a pytest plugin this project does not carry
(no new dependency), so baselines are plain PNG files compared here: decoded with ``zlib`` and
``struct`` into raw 8-bit pixel rows, then compared by the fraction of pixels that differ.
Only 8-bit, non-interlaced greyscale, RGB, grey+alpha and RGBA images are accepted; anything
else raises rather than being compared wrongly.
"""

import struct
import zlib
from dataclasses import dataclass

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


@dataclass(frozen=True)
class Image:
    width: int
    height: int
    channels: int
    rows: tuple[bytes, ...]


def _paeth(a: int, b: int, c: int) -> int:
    estimate = a + b - c
    da, db, dc = abs(estimate - a), abs(estimate - b), abs(estimate - c)
    if da <= db and da <= dc:
        return a
    return b if db <= dc else c


def _unfilter(kind: int, line: bytearray, prior: bytearray, step: int) -> None:
    size = len(line)
    if kind == 0:
        return
    if kind == 1:
        for i in range(step, size):
            line[i] = (line[i] + line[i - step]) & 255
    elif kind == 2:
        for i in range(size):
            line[i] = (line[i] + prior[i]) & 255
    elif kind == 3:
        for i in range(size):
            left = line[i - step] if i >= step else 0
            line[i] = (line[i] + ((left + prior[i]) >> 1)) & 255
    elif kind == 4:
        for i in range(size):
            left = line[i - step] if i >= step else 0
            upper_left = prior[i - step] if i >= step else 0
            line[i] = (line[i] + _paeth(left, prior[i], upper_left)) & 255
    else:
        raise ValueError(f"Unknown PNG filter {kind}")


def decode(data: bytes) -> Image:
    if not data.startswith(SIGNATURE):
        raise ValueError("Not a PNG file")
    position, header, compressed = len(SIGNATURE), None, bytearray()
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        if len(body) != length:
            raise ValueError("Truncated PNG chunk")
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed += body
        elif kind == b"IEND":
            break
        position += 12 + length
    if header is None:
        raise ValueError("PNG without a header")
    width, height, depth, color, compression, filtering, interlace = header
    if depth != 8 or color not in CHANNELS or compression or filtering or interlace:
        raise ValueError("Only 8-bit non-interlaced greyscale, RGB and RGBA PNGs are supported")
    channels = CHANNELS[color]
    stride = width * channels
    raw = zlib.decompress(bytes(compressed))
    if len(raw) != height * (stride + 1):
        raise ValueError("PNG pixel data has the wrong length")
    rows: list[bytes] = []
    prior = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        line = bytearray(raw[start + 1 : start + 1 + stride])
        _unfilter(raw[start], line, prior, channels)
        rows.append(bytes(line))
        prior = line
    return Image(width, height, channels, tuple(rows))


def different_fraction(a: Image, b: Image, *, channel_tolerance: int) -> float:
    """Fraction of pixels whose largest channel difference exceeds ``channel_tolerance``.

    Images of different sizes or channel counts are wholly different (1.0): a baseline cannot
    match a page that changed shape.
    """
    if (a.width, a.height, a.channels) != (b.width, b.height, b.channels):
        return 1.0
    step, differing = a.channels, 0
    for row_a, row_b in zip(a.rows, b.rows, strict=True):
        if row_a == row_b:
            continue
        for x in range(0, len(row_a), step):
            if any(abs(row_a[x + c] - row_b[x + c]) > channel_tolerance for c in range(step)):
                differing += 1
    return differing / (a.width * a.height)


def encode(width: int, height: int, channels: int, rows: list[bytes], filters: list[int]) -> bytes:
    """Write a PNG with the given per-row filters (used to test every unfilter path)."""
    color = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    stride = width * channels
    out, prior = bytearray(), bytes(stride)
    for row, kind in zip(rows, filters, strict=True):
        filtered = bytearray()
        for i, value in enumerate(row):
            left = row[i - channels] if i >= channels else 0
            up = prior[i]
            upper_left = prior[i - channels] if i >= channels else 0
            predictor = (
                0,
                left,
                up,
                (left + up) >> 1,
                _paeth(left, up, upper_left),
            )[kind]
            filtered.append((value - predictor) & 255)
        out += bytes([kind]) + filtered
        prior = row

    def chunk(name: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(name + body)
        return struct.pack(">I", len(body)) + name + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    return (
        SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(out)))
        + chunk(b"IEND", b"")
    )
