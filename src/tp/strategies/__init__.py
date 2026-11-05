from tp.strategies.fade import FadeParams, FailedBreakoutFade
from tp.strategies.orb import ORBParams, OpeningRangeBreakout

REGISTRY = {"orb": OpeningRangeBreakout, "fade": FailedBreakoutFade}

__all__ = ["REGISTRY", "FadeParams", "FailedBreakoutFade", "ORBParams", "OpeningRangeBreakout"]
