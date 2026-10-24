"""Share the product suite's `textutil` test double with the devtools tests.

`tests/devtools/test_loop_differential.py` builds RTF credential fixtures through
`tests.product.live_support.make_rtf_key`, which needs a `textutil` on PATH. Hosted CI runs
Linux without the macOS tool; `tests/product/conftest.py` puts the double first on PATH for the
product tests only, so the fixtures are re-exported here (pytest discovers them by name).
"""

from tests.product.conftest import fake_textutil_dir, textutil_on_path

__all__ = ["fake_textutil_dir", "textutil_on_path"]
