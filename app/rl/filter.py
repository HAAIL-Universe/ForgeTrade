"""Live trade filter — wraps trained PPO model for production use.

Provides:
- ``RLTradeFilter``: Load model, assess signals, return action + confidence.
- ``ShadowLogger``: Record decisions in shadow mode for later analysis.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from stable_baselines3 import PPO

from app.rl.features import STATE_DIM

logger = logging.getLogger("forgetrade.rl.filter")


class RLTradeFilter:
    """Wraps a trained PPO model for live trade filtering.

    Thread-safe for inference. Stateless per-call.
    """

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.6,
    ) -> None:
        self.model = PPO.load(model_path)
        self.threshold = confidence_threshold
        self._model_path = model_path
        logger.info("ForgeAgent loaded from %s (threshold=%.2f)", model_path, confidence_threshold)

    def assess(self, state: np.ndarray) -> tuple[int, float]:
        """Assess a trade signal.

        Args:
            state: ForgeState as numpy array, shape (27,).

        Returns:
            (action, confidence) where:
            - action: 0 (VETO) or 1 (TAKE)
            - confidence: probability of the chosen action [0.5, 1.0]
        """
        if state.shape != (STATE_DIM,):
            raise ValueError(f"Expected state shape ({STATE_DIM},), got {state.shape}")

        action, _states = self.model.predict(state, deterministic=True)

        # Extract probabilities for confidence
        obs_tensor = torch.as_tensor(state).float().unsqueeze(0)
        with torch.no_grad():
            dist = self.model.policy.get_distribution(
                self.model.policy.obs_to_tensor(state)[0]
            )
            probs = dist.distribution.probs.cpu().numpy()[0]

        confidence = float(probs[int(action)])
        return int(action), confidence

    def should_take(self, state: np.ndarray) -> bool:
        """Convenience: return True if the agent recommends TAKE."""
        action, confidence = self.assess(state)
        return action == 1 and confidence >= self.threshold


class ShadowLogger:
    """Records ForgeAgent decisions in shadow mode for later analysis.

    Writes JSONL format to ``data/rl_shadow_log.jsonl``.
    """

    def __init__(self, log_path: str = "data/rl_shadow_log.jsonl"):
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        timestamp: str,
        instrument: str,
        direction: str,
        entry_price: float,
        action: int,
        confidence: float,
        state_hash: Optional[str] = None,
    ) -> None:
        """Append a shadow decision to the log."""
        record = {
            "timestamp": timestamp,
            "instrument": instrument,
            "direction": direction,
            "entry_price": entry_price,
            "agent_action": "TAKE" if action == 1 else "VETO",
            "confidence": round(confidence, 4),
            "state_hash": state_hash,
        }
        with open(self._path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def log_outcome(
        self,
        timestamp: str,
        instrument: str,
        actual_outcome: str,
        r_multiple: float,
    ) -> None:
        """Log the actual trade outcome (for retrospective analysis)."""
        record = {
            "timestamp": timestamp,
            "instrument": instrument,
            "outcome": actual_outcome,
            "r_multiple": round(r_multiple, 3),
            "type": "outcome",
        }
        with open(self._path, "a") as f:
            f.write(json.dumps(record) + "\n")
