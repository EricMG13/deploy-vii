"""The textutil test double must agree with the real tool wherever the real tool exists.

The double carries the credential tests on Linux, so its own behaviour is pinned here: fixed
expectations on every platform, and a differential check against macOS `textutil` where present.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.product import fake_textutil
from tests.product.live_support import FAKE_KEY

TEXTEDIT = (
    "{\\rtf1\\ansi\\ansicpg1252\\cocoartf2822\n{\\fonttbl\\f0\\fswiss\\fcharset0 Helvetica;}\n"
    "{\\colortbl;\\red255\\green255\\blue255;}\n{\\*\\expandedcolortable;}\n"
    "\\pard\\tx566\\pardirnatural\\partightenfactor0\n\n"
    "\\f0\\fs24 \\cf0 Label:\\\n\\\n\\'93KEY\\'94 \\u233? {\\\\ \\{x\\}}\\\n}"
)


def test_rtf_is_reduced_to_its_text() -> None:
    text = fake_textutil.rtf_to_text(TEXTEDIT.replace("KEY", FAKE_KEY).encode())
    assert text.split() == ["Label:", f"“{FAKE_KEY}”", "é", "\\", "{x}"]
    assert text.count("\n") == 3


def test_windows_line_breaks_and_plain_text() -> None:
    crlf = fake_textutil.rtf_to_text(b"{\\rtf1 a\\\r\nb}")
    assert crlf == "a\nb"
    assert fake_textutil.rtf_to_text(b"\xef\xbb\xbfplain \xc3\xa9") == "plain é"
    with pytest.raises(UnicodeDecodeError):
        fake_textutil.rtf_to_text(b"\xff\xfe\x00\x00")


@pytest.mark.parametrize(
    "text", ["", "key sk-or-v1-FIXTURE", "tab\there", "{a}\\b\n“q” \U0001f600"]
)
def test_text_survives_an_rtf_round_trip(text: str) -> None:
    assert fake_textutil.rtf_to_text(fake_textutil.text_to_rtf(text)) == text


def _run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", fake_textutil.__file__, *args], capture_output=True, check=False
    )


def test_command_line_converts_and_refuses(tmp_path: Path) -> None:
    source = tmp_path / "key.txt"
    source.write_text(f"label {FAKE_KEY}\n", encoding="utf-8")
    rtf = tmp_path / "key.rtf"
    assert _run("-convert", "rtf", str(source), "-output", str(rtf)).returncode == 0
    done = _run("-convert", "txt", "-stdout", str(rtf))
    assert done.returncode == 0 and done.stdout.decode() == f"label {FAKE_KEY}\n"
    assert _run("-convert", "txt", "-stdout", str(tmp_path / "absent")).returncode == 1
    assert _run("-convert", "doc", str(source)).returncode == 2
    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"\xff\xfe\x00\x00")
    assert _run("-convert", "txt", "-stdout", str(binary)).returncode == 1


@pytest.mark.skipif(
    shutil.which("textutil") is None,
    reason="the differential check needs the real macOS textutil, which this host lacks",
)
@pytest.mark.parametrize("text", [FAKE_KEY, f"OpenRouter key:\n\n“{FAKE_KEY}”\n", "a\tb"])
def test_fake_agrees_with_real_textutil(tmp_path: Path, text: str) -> None:
    source = tmp_path / "in.txt"
    source.write_text(text, encoding="utf-8")
    real_rtf = tmp_path / "real.rtf"
    subprocess.run(
        ["textutil", "-convert", "rtf", str(source), "-output", str(real_rtf)],
        check=True,
        capture_output=True,
    )
    real = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(real_rtf)], check=True, capture_output=True
    ).stdout.decode()
    assert fake_textutil.rtf_to_text(real_rtf.read_bytes()).strip() == real.strip()
    fake_rtf = fake_textutil.text_to_rtf(text)
    (tmp_path / "fake.rtf").write_bytes(fake_rtf)
    from_fake = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(tmp_path / "fake.rtf")],
        check=True,
        capture_output=True,
    ).stdout.decode()
    assert from_fake.strip() == text.strip()
