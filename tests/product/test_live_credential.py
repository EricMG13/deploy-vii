"""DC-7 credential loading and redaction; fixture keys only, never the real key file."""

import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from deploy_vii.live import credential
from deploy_vii.live.credential import (
    CredentialError,
    load_key,
    load_key_with_note,
    redact,
    scrub_key,
)
from deploy_vii.live.settings import SettingsError, load_settings
from tests.product.live_support import FAKE_KEY, SECOND_FAKE_KEY, make_rtf_key

requires_textutil = pytest.mark.skipif(
    shutil.which("textutil") is None,
    reason="textutil is macOS-only; the loader fails closed without it (tested separately)",
)


@requires_textutil
def test_rtf_key_is_converted_and_stripped(tmp_path: Path) -> None:
    assert load_key(make_rtf_key(tmp_path)) == FAKE_KEY


@requires_textutil
@pytest.mark.parametrize(
    "text",
    [
        FAKE_KEY,
        f"OpenRouter key: {FAKE_KEY}\n",
        f"OpenRouter key\n\n{FAKE_KEY}\n\nkeep this file private.",
        f'"{FAKE_KEY}"',
        f"“{FAKE_KEY}”",  # TextEdit smart quotes
        f"(key {FAKE_KEY}), issued today.",
        f"key={FAKE_KEY}; scope: Deploy VII",
        f"{FAKE_KEY} second-token",
        f"{FAKE_KEY}\n{FAKE_KEY}",  # one key written twice is one key
        f"xsk-or-v1-NOTAKEY0 then {FAKE_KEY}",  # a glued prefix is not a token
    ],
)
def test_single_key_token_is_extracted_from_prose(tmp_path: Path, text: str) -> None:
    assert load_key(make_rtf_key(tmp_path, text)) == FAKE_KEY


TEXTEDIT_RTF = (
    "{\\rtf1\\ansi\\ansicpg1252\\cocoartf2822\n"
    "\\cocoatextscaling0\\cocoaplatform0{\\fonttbl\\f0\\fswiss\\fcharset0 Helvetica;}\n"
    "{\\colortbl;\\red255\\green255\\blue255;}\n"
    "\\paperw11900\\paperh16840\\margl1440\\margr1440\\vieww11520\\viewh8400\\viewkind0\n"
    "\\pard\\tx566\\tx1133\\pardirnatural\\partightenfactor0\n\n"
    "\\f0\\fs24 \\cf0 OpenRouter key:\\\n\\\n\\'93KEY\\'94\\\n}"
)


@requires_textutil
@pytest.mark.parametrize("line_end", ["\n", "\r\n"])
def test_hand_written_textedit_rtf_with_label_and_smart_quotes(
    tmp_path: Path, line_end: str
) -> None:
    path = tmp_path / "op router.rtf"
    path.write_bytes(TEXTEDIT_RTF.replace("KEY", FAKE_KEY).replace("\n", line_end).encode())
    assert load_key(path) == FAKE_KEY


@pytest.mark.parametrize(
    "stdout",
    [
        b"\xef\xbb\xbf" + FAKE_KEY.encode(),
        b"\xef\xbb\xbfOpenRouter key:\r\n\r\n" + FAKE_KEY.encode() + b"\r\n",
        b"key:\t" + FAKE_KEY.encode() + b"\r\n\r\n",
    ],
)
def test_bom_and_windows_line_endings_are_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: bytes
) -> None:
    monkeypatch.setattr(credential.shutil, "which", lambda _: "/usr/bin/textutil")
    done = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout)
    monkeypatch.setattr(credential.subprocess, "run", lambda *a, **k: done)
    present = tmp_path / "key.rtf"
    present.write_text("placeholder", encoding="utf-8")
    assert load_key(present) == FAKE_KEY


@requires_textutil
@pytest.mark.parametrize(
    "text, message",
    [
        ("SECRETMARK", "no key-shaped token among 1 non-empty lines"),
        ("sk-or-", "no key-shaped token among 1 non-empty lines"),
        ("sk-or-ABCDE", "no key-shaped token among 1 non-empty lines"),  # under 6 characters
        ("label\n\nxsk-or-v1-SECRETMARK", "no key-shaped token among 2 non-empty lines"),
        ("api-sk-or-v1-SECRETMARK", "no key-shaped token among 1 non-empty lines"),
        ("key_sk-or-v1-SECRETMARK", "no key-shaped token among 1 non-empty lines"),
        ("sk-or-v1-SECRETMARKé", "no key-shaped token among 1 non-empty lines"),
        ("sk-or-é-SECRETMARK", "no key-shaped token among 1 non-empty lines"),
        ("\n\n", "credential file is empty"),
    ],
)
def test_malformed_content_is_refused_without_echo(tmp_path: Path, text: str, message: str) -> None:
    path = make_rtf_key(tmp_path, text)
    with pytest.raises(CredentialError, match=message) as raised:
        load_key(path)
    assert "SECRETMARK" not in str(raised.value)
    assert "sk-or-" not in str(raised.value)
    assert raised.value.__cause__ is None


FIRST, SECOND, THIRD = (f"sk-or-v1-SECRETMARK{n}-fixture" for n in (1, 2, 3))


def _assert_note_is_clean(loaded: object, note: dict[str, int]) -> None:
    text = repr(loaded) + str(loaded) + json.dumps(note)
    assert "sk-or-" not in text and "SECRETMARK" not in text


@requires_textutil
@pytest.mark.parametrize(
    "text, expected, found",
    [
        (f"{FIRST} {SECOND}", FIRST, 2),
        (f"old: {FIRST}\nnew: {SECOND}\n{FIRST}", FIRST, 2),  # a repeat adds no token
        (f"label\n\n{SECOND}\n{FIRST}", SECOND, 2),  # file order, not sort order
        (f"a {FIRST}\nb {SECOND}\nc {THIRD}", FIRST, 3),
        (f"c {THIRD}\nb {SECOND}\na {FIRST}", THIRD, 3),
        (f"xsk-or-v1-NOTATOKEN0 {SECOND} {FIRST}", SECOND, 2),  # a glued prefix is no token
    ],
)
def test_several_distinct_tokens_use_the_first_in_file_order(
    tmp_path: Path, text: str, expected: str, found: int
) -> None:
    """Default credential_token_index 1: the first distinct token in file order."""
    path = make_rtf_key(tmp_path, text)
    loaded = load_key_with_note(path)
    assert loaded.key == expected
    assert (loaded.tokens_found, loaded.index_used) == (found, 1)
    assert loaded.note() == {"key_tokens_found": found, "key_token_used": 1}
    assert load_key(path) == expected  # the string API keeps its signature and choice
    _assert_note_is_clean(loaded, loaded.note())


@requires_textutil
@pytest.mark.parametrize("index, expected", [(1, FIRST), (2, SECOND)])
def test_the_settings_index_selects_the_token_in_file_order(
    tmp_path: Path, index: int, expected: str
) -> None:
    """Probe-1: the first token answered `GET /key` but every chat call was a 401, so the
    choice is now an explicit, recorded setting rather than an implicit first-token rule."""
    path = make_rtf_key(tmp_path, f"old: {FIRST}\nnew: {SECOND}\n")
    loaded = load_key_with_note(path, index=index)
    assert loaded.key == expected
    assert loaded.note() == {"key_tokens_found": 2, "key_token_used": index}
    assert load_key(path, index=index) == expected
    _assert_note_is_clean(loaded, loaded.note())


@requires_textutil
@pytest.mark.parametrize(
    "text, index, message",
    [
        (f"old: {FIRST}\nnew: {SECOND}\n", 3, "credential_token_index 3 but only 2 key-shaped"),
        (f"{FIRST}\nagain: {FIRST}\n", 2, "credential_token_index 2 but only 1 key-shaped"),
    ],
    ids=["beyond-two-distinct", "duplicate-is-one-distinct"],
)
def test_an_index_beyond_the_distinct_tokens_fails_closed_without_token_text(
    tmp_path: Path, text: str, index: int, message: str
) -> None:
    with pytest.raises(CredentialError, match=message) as raised:
        load_key_with_note(make_rtf_key(tmp_path, text), index=index)
    assert "sk-or-" not in str(raised.value) and "SECRETMARK" not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("index", [0, -1, True, 1.0, "2"])
def test_a_non_positive_or_non_integer_index_is_refused_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index: object
) -> None:
    """Index 0 or -1 would silently pick the last token through Python's negative indexing."""

    def never(*_a: object, **_k: object) -> None:
        raise AssertionError("the file must not be converted for an invalid index")

    monkeypatch.setattr(credential.subprocess, "run", never)
    present = tmp_path / "present.rtf"
    present.write_text("placeholder", encoding="utf-8")
    with pytest.raises(CredentialError, match="credential_token_index must be an integer >= 1"):
        load_key_with_note(present, index=cast(int, index))  # deliberately ill-typed


@requires_textutil
def test_one_token_written_twice_is_one_of_one(tmp_path: Path) -> None:
    loaded = load_key_with_note(make_rtf_key(tmp_path, f"{FAKE_KEY}\nagain: {FAKE_KEY}"))
    assert loaded.key == FAKE_KEY
    assert loaded.note() == {"key_tokens_found": 1, "key_token_used": 1}
    assert "TESTONLY" not in repr(loaded)


@pytest.mark.parametrize("line_end", [b"\n", b"\r\n", b"\r"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_first_token_is_independent_of_line_endings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line_end: bytes, bom: bytes
) -> None:
    stdout = bom + line_end.join(
        [b"OpenRouter keys:", b"", SECOND.encode(), b"spare: " + FIRST.encode(), b""]
    )
    monkeypatch.setattr(credential.shutil, "which", lambda _: "/usr/bin/textutil")
    done = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout)
    monkeypatch.setattr(credential.subprocess, "run", lambda *a, **k: done)
    present = tmp_path / "key.rtf"
    present.write_text("placeholder", encoding="utf-8")
    loaded = load_key_with_note(present)
    assert loaded.key == SECOND and loaded.note() == {"key_tokens_found": 2, "key_token_used": 1}


@requires_textutil
@pytest.mark.parametrize("line_end", ["\n", "\r\n"])
def test_textedit_rtf_with_two_keys_uses_the_first_for_either_line_ending(
    tmp_path: Path, line_end: str
) -> None:
    path = tmp_path / "op router.rtf"
    two = TEXTEDIT_RTF.replace("KEY", SECOND).removesuffix("}") + f"spare: {FIRST}\\\n}}"
    path.write_bytes(two.replace("\n", line_end).encode())
    loaded = load_key_with_note(path)
    assert loaded.key == SECOND and loaded.tokens_found == 2
    _assert_note_is_clean(loaded, loaded.note())


@requires_textutil
def test_empty_rtf_file_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty.rtf"
    empty.write_bytes(b"")
    with pytest.raises(CredentialError, match="empty"):
        load_key(empty)


def test_missing_file_and_missing_textutil_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(CredentialError, match="does not exist"):
        load_key(tmp_path / "absent.rtf")
    monkeypatch.setattr(credential.shutil, "which", lambda _: None)
    present = tmp_path / "present.rtf"
    present.write_text(FAKE_KEY, encoding="utf-8")
    with pytest.raises(CredentialError, match="fails closed"):
        load_key(present)


@requires_textutil
def test_conversion_failures_are_reported_without_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"\xff\xfe\x00\x00")
    with pytest.raises(CredentialError):
        load_key(binary)

    class Done:
        returncode = 0
        stdout = b"\xff\xfe"

    monkeypatch.setattr(credential.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(CredentialError, match="UTF-8") as undecodable:
        load_key(binary)
    assert undecodable.value.__cause__ is None  # the decode error (with bytes) is not chained
    assert str(undecodable.value) == "credential file is not UTF-8 text"

    class Failed:
        returncode = 2
        stdout = b"sk-or-v1-TESTONLY-must-not-surface"
        stderr = b"sk-or-v1-TESTONLY-must-not-surface"

    monkeypatch.setattr(credential.subprocess, "run", lambda *a, **k: Failed())
    with pytest.raises(CredentialError, match="status 2") as failed:
        load_key(binary)
    assert "TESTONLY" not in str(failed.value)
    assert "sk-or-" not in str(failed.value)
    assert failed.value.__cause__ is None and str(failed.value) == "textutil exited with status 2"

    def hang(*args: object, **kwargs: object) -> None:
        raise credential.subprocess.TimeoutExpired(
            cmd=["textutil"], timeout=30, output=b"sk-or-v1-TESTONLY-in-timeout-output"
        )

    monkeypatch.setattr(credential.subprocess, "run", hang)
    with pytest.raises(CredentialError) as timed_out:
        load_key(binary)
    assert str(timed_out.value) == "textutil could not convert the credential file"
    assert timed_out.value.__cause__ is None and "TESTONLY" not in str(timed_out.value)

    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("sk-or-v1-TESTONLY-leak-through-os-error")

    monkeypatch.setattr(credential.subprocess, "run", explode)
    with pytest.raises(CredentialError) as raised_os:
        load_key(binary)
    assert "TESTONLY" not in str(raised_os.value)
    assert "sk-or-" not in str(raised_os.value)
    assert raised_os.value.__cause__ is None


def test_redact_removes_exact_key_key_shapes_and_authorization_values() -> None:
    text = (
        f"Authorization: Bearer {FAKE_KEY}; other {SECOND_FAKE_KEY}; "
        f"{{'Authorization': 'Bearer abc.def-ghi'}} and {FAKE_KEY[:-4]}"
    )
    scrubbed = redact(text, FAKE_KEY)
    assert "TESTONLY" not in scrubbed
    assert FAKE_KEY not in scrubbed and "abc.def" not in scrubbed
    assert "Authorization: [REDACTED]" in scrubbed
    # Ordinary prose and filing text pass through untouched.
    assert redact("nothing to hide", FAKE_KEY) == "nothing to hide"
    assert redact("nothing to hide", "") == "nothing to hide"
    assert redact("Bearer bonds and authorization of the notes", "") == (
        "Bearer bonds and authorization of the notes"
    )


def test_scrub_key_leaves_header_like_prose_alone_but_redact_rewrites_it() -> None:
    prose = "Authorization: the board approved the notes; Authorization = x"
    assert scrub_key(prose, FAKE_KEY) == prose  # evidence and model output stay verbatim
    assert scrub_key(f"{prose} {FAKE_KEY} sk-or-v1-OTHERKEY", FAKE_KEY).count("[REDACTED]") == 2
    assert FAKE_KEY not in scrub_key(FAKE_KEY, FAKE_KEY)
    # redact is for error text only, which is why evidence never goes through it.
    assert redact(prose, FAKE_KEY).startswith("Authorization: [REDACTED] board")


PROSE = "risk-or-reward, task-or-derived and disk-or-network are ordinary words"


def test_scrub_key_never_alters_words_that_merely_contain_the_key_prefix() -> None:
    assert scrub_key(PROSE, FAKE_KEY) == PROSE
    mixed = f"{PROSE}; key={SECOND_FAKE_KEY}; ({SECOND_FAKE_KEY}) 'sk-or-v1-QUOTEDKEY0'"
    scrubbed = scrub_key(mixed, FAKE_KEY)
    assert (
        scrubbed.startswith(PROSE) and "TESTONLY" not in scrubbed and "QUOTEDKEY0" not in scrubbed
    )
    assert scrubbed.count("[REDACTED]") == 3
    assert scrub_key("sk-or-v1-LEADING0 at the start", "") == "[REDACTED] at the start"
    # A key glued on after a hyphen or underscore is still caught.
    assert scrub_key("api-sk-or-v1-GLUED001 and key_sk-or-v1-GLUED002", "") == (
        "api-[REDACTED] and key_[REDACTED]"
    )


def test_project_settings_declare_the_runner_contract() -> None:
    settings = load_settings(Path("settings/project.toml"))
    assert [item.key for item in settings.candidates] == ["luna", "glm", "deepseek"]
    assert settings.candidates[2].resolution == "refresh-latest-suitable-deepseek-before-batch"
    assert settings.default_effort == "high" and settings.complex_effort == "xhigh"
    assert str(settings.caps.cumulative_ceiling) == "200"
    assert str(settings.caps.e1_per_case) == "3"
    assert settings.artifact_root.name == "model-tests"
    assert settings.credential_file.name == "op router.rtf"
    assert settings.credential_token_index == 2  # probe-2: the second token is the inference key
    # Decision 0008 (MC-10): probe-2 measured 5.61 bytes per token; 3.0 keeps a 1.9x margin.
    assert settings.prompt_bytes_per_token_lower_bound == Decimal("3.0")
    assert settings.model_calls_in_ci is False


@pytest.mark.parametrize(
    "toml, message",
    [
        ("[ci]\nmodel_calls = false\n", "missing the \\[model_tests\\]"),
        (
            '[model_tests]\ncredential_file = "x"\n[[model_tests.candidates]]\nkey="a"\n'
            'model_id="m"\nresolution="r"\nrecurring_caps_usd={}\n',
            "needs recurring_caps_usd|needs a text value",
        ),
        (
            '[model_tests]\ncredential_file="k"\nartifact_root="a"\ndefault_effort="high"\n'
            'complex_effort="xhigh"\n',
            "no candidates",
        ),
        (
            '[model_tests]\ncredential_file="k"\nartifact_root="a"\ndefault_effort="high"\n'
            'complex_effort="xhigh"\n[[model_tests.candidates]]\nkey="a"\nmodel_id="m"\n'
            'resolution="r"\n[[model_tests.candidates]]\nkey="a"\nmodel_id="n"\nresolution="r"\n',
            "repeats a candidate key",
        ),
        (
            '[model_tests]\ncredential_file="k"\nartifact_root="a"\ndefault_effort="high"\n'
            'complex_effort="xhigh"\n[[model_tests.candidates]]\nkey="a"\nmodel_id="m"\n'
            'resolution="r"\n',
            "needs recurring_caps_usd",
        ),
        (
            '[model_tests]\ncredential_file="k"\ndefault_effort="high"\ncomplex_effort="xhigh"\n'
            "recurring_caps_usd={e1_per_case=1}\n"
            '[[model_tests.candidates]]\nkey="a"\nmodel_id="m"\nresolution="r"\n',
            "needs a text value for artifact_root",
        ),
        (
            '[model_tests]\ncredential_file="k"\nartifact_root="a"\ndefault_effort="high"\n'
            'complex_effort="xhigh"\nrecurring_caps_usd={e1_per_case="x"}\n'
            "prompt_bytes_per_token_lower_bound=3.0\n"
            '[[model_tests.candidates]]\nkey="a"\nmodel_id="m"\nresolution="r"\n',
            "needs a number",
        ),
    ],
)
def test_settings_failures_are_explicit(tmp_path: Path, toml: str, message: str) -> None:
    path = tmp_path / "project.toml"
    path.write_text(toml, encoding="utf-8")
    with pytest.raises(SettingsError, match=message):
        load_settings(path, root=tmp_path)


RATIO = "prompt_bytes_per_token_lower_bound = 3.0\n"
VALID_SETTINGS = (
    '[model_tests]\ncredential_file="~/k.rtf"\n{index}artifact_root="evidence"\n'
    'default_effort="high"\ncomplex_effort="xhigh"\ncumulative_ceiling_usd=5\n'
    "{ratio}recurring_caps_usd={{e1_per_case=1, e2_per_milestone=2.5, e3_per_week=1}}\n"
    '[[model_tests.candidates]]\nkey="a"\nmodel_id="m"\nresolution="r"\n[ci]\n'
)


def test_settings_read_the_credential_token_index(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    text = VALID_SETTINGS.format(index="credential_token_index = 2\n", ratio=RATIO)
    path.write_text(text, encoding="utf-8")
    assert load_settings(path, root=tmp_path).credential_token_index == 2


@pytest.mark.parametrize("value", ["0", "-1", "true", "1.5", '"2"'])
def test_settings_refuse_a_credential_token_index_that_is_not_a_positive_integer(
    tmp_path: Path, value: str
) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        VALID_SETTINGS.format(index=f"credential_token_index = {value}\n", ratio=RATIO),
        encoding="utf-8",
    )
    with pytest.raises(SettingsError, match="credential_token_index must be an integer >= 1"):
        load_settings(path, root=tmp_path)


def test_settings_resolve_relative_artifact_root_against_given_root(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '[model_tests]\ncredential_file="~/k.rtf"\nartifact_root="evidence"\n'
        'default_effort="high"\ncomplex_effort="xhigh"\ncumulative_ceiling_usd=5\n'
        "prompt_bytes_per_token_lower_bound=3.0\n"
        "recurring_caps_usd={e1_per_case=1, e2_per_milestone=2.5, e3_per_week=1}\n"
        '[[model_tests.candidates]]\nkey="a"\nmodel_id="m"\nresolution="r"\n[ci]\n',
        encoding="utf-8",
    )
    settings = load_settings(path, root=tmp_path)
    assert settings.model_calls_in_ci is False  # an empty [ci] table never enables model calls
    assert settings.artifact_root == tmp_path / "evidence"
    assert not str(settings.credential_file).startswith("~")
    assert settings.credential_token_index == 1  # absent means the first token
    assert str(settings.caps.e2_per_milestone) == "2.5"
    assert json.dumps(str(settings.caps.cumulative_ceiling)) == '"5"'


@pytest.mark.parametrize(
    "line, message",
    [
        ("", "needs a number for prompt_bytes_per_token_lower_bound"),
        ('prompt_bytes_per_token_lower_bound = "3"\n', "needs a number"),
        ("prompt_bytes_per_token_lower_bound = true\n", "needs a number"),
        ("prompt_bytes_per_token_lower_bound = 0\n", "must be a positive number"),
        ("prompt_bytes_per_token_lower_bound = -2.5\n", "must be a positive number"),
        ("prompt_bytes_per_token_lower_bound = nan\n", "must be a positive number"),
        ("prompt_bytes_per_token_lower_bound = inf\n", "must be a positive number"),
    ],
)
def test_settings_require_a_positive_prompt_bytes_per_token_bound(
    tmp_path: Path, line: str, message: str
) -> None:
    """Required, no default: the reservation bound is never silently assumed."""
    path = tmp_path / "project.toml"
    path.write_text(VALID_SETTINGS.format(index="", ratio=line), encoding="utf-8")
    with pytest.raises(SettingsError, match=message):
        load_settings(path, root=tmp_path)
    path.write_text(VALID_SETTINGS.format(index="", ratio=RATIO), encoding="utf-8")
    assert load_settings(path, root=tmp_path).prompt_bytes_per_token_lower_bound == Decimal("3.0")
