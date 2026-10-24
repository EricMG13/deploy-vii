"""User-supplied input files and their self-checks (`deploy-vii validate-input <kind> <file>`).

`KINDS` maps each input kind the CLI accepts to its validator; a new kind is one entry here.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from deploy_vii.inputs.rv_quotes import ValidationReport, validate_rv_quotes

KINDS: Mapping[str, Callable[[Path], ValidationReport]] = {"rv": validate_rv_quotes}
