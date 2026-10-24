"""The binding maps that ship with the product; ``render`` builds the Front Page from these."""

from deploy_vii.bindings import BindingMap
from deploy_vii.bindings.cp0 import CP0
from deploy_vii.bindings.cp1 import CP1
from deploy_vii.bindings.cp1a import CP1A
from deploy_vii.bindings.cp_model import CP_MODEL

SHIPPED_MAPS: tuple[BindingMap, ...] = (CP0, CP1, CP_MODEL, CP1A)
