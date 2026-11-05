from tp.strategies.ead import EADParams, EarningsDrift
from tp.strategies.fade import FadeParams, FailedBreakoutFade
from tp.strategies.orb import ORBParams, OpeningRangeBreakout
from tp.strategies.pullback import MAPullback, PullbackParams
from tp.strategies.rsi2 import RSI2Params, RSI2Reversion

REGISTRY = {
    "orb": OpeningRangeBreakout,
    "fade": FailedBreakoutFade,
    "rsi2": RSI2Reversion,
    "pullback": MAPullback,
    "ead": EarningsDrift,
}

__all__ = [
    "REGISTRY", "EADParams", "EarningsDrift", "FadeParams", "FailedBreakoutFade", "MAPullback", "ORBParams",
    "OpeningRangeBreakout", "PullbackParams", "RSI2Params", "RSI2Reversion",
]
