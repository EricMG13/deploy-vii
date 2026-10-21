"""The binding maps that ship with the product; ``render`` builds the Front Page from these."""

from deploy_vii.bindings import BindingMap
from deploy_vii.bindings.cp0 import CP0
from deploy_vii.bindings.cp1 import CP1

SHIPPED_MAPS: tuple[BindingMap, ...] = (CP0, CP1)
