"""Claude client for the agent chain.

Live mode streams from the Claude API (Opus 5). If no credential is present the
same interface streams a deterministic sentence derived from the real computed
state, so the system stays demonstrable offline. The UI labels which mode is
running — a simulated agent is never presented as a live one.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, Iterator, Optional

MODEL = os.environ.get("AUTOFLEET_MODEL", "claude-opus-5")

# Agent turns are 1-3 sentences. Opus 5 thinks by default and thinking shares
# this budget with the response, so leave headroom above the visible output.
MAX_TOKENS = 1400

# Low effort: these are fast, tightly-scoped judgement calls on pre-computed
# inputs, not open-ended reasoning. Keeps the chain inside a demo's patience.
EFFORT = os.environ.get("AUTOFLEET_EFFORT", "low")

# A 1-3 sentence answer at low effort returns in a few seconds. The SDK default
# timeout is 10 minutes, which would let one hung call stall an entire incident —
# so cap it hard. One retry, not two: a second failure means degrade, not wait.
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("AUTOFLEET_TIMEOUT", "25"))
MAX_RETRIES = 1


def _load_dotenv() -> None:
    """Read KEY=VALUE lines from a local .env without adding a dependency."""
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if not candidate.is_file():
            continue
        try:
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            pass


class LLM:
    """Streaming wrapper with an honest offline fallback."""

    def __init__(self) -> None:
        _load_dotenv()
        self._client = None
        self._error: Optional[str] = None
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            self._error = "No ANTHROPIC_API_KEY found — running in simulated mode."
            return
        try:
            import anthropic  # imported lazily so offline mode needs no install
            self._client = anthropic.Anthropic(
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=MAX_RETRIES,
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            self._error = f"Anthropic SDK unavailable ({exc}) — simulated mode."

    @property
    def live(self) -> bool:
        return self._client is not None

    @property
    def status(self) -> Dict:
        return {
            "live": self.live,
            "model": MODEL if self.live else "deterministic-fallback",
            "effort": EFFORT if self.live else None,
            "note": self._error or f"Live agents on {MODEL} (effort={EFFORT}).",
        }

    # ----------------------------------------------------------------------

    def stream(
        self, *, system: str, user: str, fallback: str, force_fallback: bool = False
    ) -> Iterator[Dict]:
        """Yield {'text': str} deltas, then one {'done': True, ...} summary.

        `force_fallback` is set by the chain when its wall-clock budget is spent:
        stop asking the model and emit the deterministic answer immediately.
        """
        if not self.live or force_fallback:
            note = (
                "Chain budget spent — resolved from model output without the "
                "language layer."
                if force_fallback else None
            )
            yield from self._stream_fallback(fallback, note=note)
            return

        started = time.perf_counter()
        collected: list[str] = []
        try:
            import anthropic

            with self._client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                output_config={"effort": EFFORT},
                messages=[{"role": "user", "content": user}],
            ) as stream:
                for chunk in stream.text_stream:
                    collected.append(chunk)
                    yield {"text": chunk}
                final = stream.get_final_message()

            text = "".join(collected).strip()
            if final.stop_reason == "refusal" or not text:
                # Safety classifier declined, or the budget went entirely to
                # thinking. Fall back rather than emit an empty agent card.
                reason = "declined by safety classifier" if final.stop_reason == "refusal" \
                    else "empty completion"
                yield {"text": fallback}
                yield {
                    "done": True,
                    "text": fallback,
                    "ms": int((time.perf_counter() - started) * 1000),
                    "source": "fallback",
                    "note": f"Live call returned no usable text ({reason}).",
                }
                return

            usage = getattr(final, "usage", None)
            yield {
                "done": True,
                "text": text,
                "ms": int((time.perf_counter() - started) * 1000),
                "source": "live",
                "model": getattr(final, "model", MODEL),
                "tokens": {
                    "input": getattr(usage, "input_tokens", None),
                    "output": getattr(usage, "output_tokens", None),
                } if usage else None,
            }
            return

        except Exception as exc:  # network, auth, rate limit
            detail = type(exc).__name__
            if collected:
                text = "".join(collected).strip()
                yield {
                    "done": True,
                    "text": text,
                    "ms": int((time.perf_counter() - started) * 1000),
                    "source": "live-partial",
                    "note": f"Stream interrupted ({detail}).",
                }
                return
            yield {"text": fallback}
            yield {
                "done": True,
                "text": fallback,
                "ms": int((time.perf_counter() - started) * 1000),
                "source": "fallback",
                "note": f"Live call failed ({detail}); used deterministic fallback.",
            }

    def _stream_fallback(self, fallback: str, note: Optional[str] = None) -> Iterator[Dict]:
        started = time.perf_counter()
        # No typing delay when degrading — the point is to finish fast.
        delay = 0.0 if note else 0.018
        words = fallback.split(" ")
        for i, word in enumerate(words):
            if delay:
                time.sleep(delay)
            yield {"text": word if i == 0 else " " + word}
        yield {
            "done": True,
            "text": fallback,
            "ms": int((time.perf_counter() - started) * 1000),
            "source": "degraded" if note else "fallback",
            "note": note or "Deterministic text derived from computed fleet state.",
        }
