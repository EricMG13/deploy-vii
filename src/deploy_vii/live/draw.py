"""Seeded uniform draw over the eligible members of a pinned pool (testing contract)."""

import random
from dataclasses import dataclass
from typing import Any

from deploy_vii.live.catalog import PinnedPool

ALGORITHM = "python-random-MT19937"
# Decision 0005 amendment (22 Oct 2026): the random draw applies only to a pool of more than one
# model; a one-model pool selects that model for every seed and records the draw as trivial.
TRIVIAL = "trivial-single-model-pool"


class NoEligibleModel(Exception):
    """Every pool member is ineligible: the model test stays blocked."""


@dataclass(frozen=True)
class Draw:
    pool: tuple[str, ...]
    eligible: tuple[str, ...]
    exclusions: tuple[tuple[str, str], ...]
    algorithm: str
    seed: int
    index: int
    slug: str

    def to_record(self) -> dict[str, Any]:
        return {
            "pool": list(self.pool),
            "eligible": list(self.eligible),
            "exclusions": [{"slug": slug, "reason": reason} for slug, reason in self.exclusions],
            "algorithm": self.algorithm,
            "seed": self.seed,
            "index": self.index,
            "slug": self.slug,
        }


def draw(pool: PinnedPool, seed: int) -> Draw:
    """Pick one eligible member with equal probability; record everything before dispatch.

    A pool of one model is not drawn from (`TRIVIAL`); the seed is still recorded."""
    eligible = tuple(item.slug for item in pool.eligible)
    if not eligible:
        raise NoEligibleModel("no eligible model in the pinned pool; the test stays blocked")
    trivial = len(pool.candidates) == 1
    index = 0 if trivial else random.Random(seed).randrange(len(eligible))
    return Draw(
        pool=tuple(item.slug for item in pool.candidates),
        eligible=eligible,
        exclusions=tuple(
            (item.slug, item.exclusion_reason or "unspecified")
            for item in pool.candidates
            if not item.eligible
        ),
        algorithm=TRIVIAL if trivial else ALGORITHM,
        seed=seed,
        index=index,
        slug=eligible[index],
    )
