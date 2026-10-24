"""The binding maps that ship with the product; ``render`` builds the Front Page from these."""

from deploy_vii.bindings import BindingMap
from deploy_vii.bindings.cp0 import CP0
from deploy_vii.bindings.cp1 import CP1
from deploy_vii.bindings.cp1a import CP1A
from deploy_vii.bindings.cp2 import CP2
from deploy_vii.bindings.cp3 import CP3
from deploy_vii.bindings.cp4 import CP4
from deploy_vii.bindings.cp5 import CP5
from deploy_vii.bindings.cp_model import CP_MODEL

# Task 8.6: CP-2, CP-4, CP-3 and CP-5 in registry order after CP-1A.
SHIPPED_MAPS: tuple[BindingMap, ...] = (CP0, CP1, CP_MODEL, CP1A, CP2, CP4, CP3, CP5)
