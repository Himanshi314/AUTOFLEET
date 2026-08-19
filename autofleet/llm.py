"""Model clients for the agent chain — Anthropic or Groq, same interface.

Three implementations behind one contract:

  · `AnthropicLLM` — Claude via the official SDK (default)
  · `GroqLLM`      — Groq's OpenAI-compatible API over **stdlib urllib only**,
                     so it needs no pip install at all
  · the shared fallback in `LLM` — deterministic text derived from real computed
    state, used when there is no credential, when the chain's budget is spent, or
    when a live call fails

Pick with `AUTOFLEET_PROVIDER=anthropic|groq`. Everything provider-specific lives
in this file: the rest of the project only ever calls `llm.stream()` and reads
`llm.status`, which is why swapping providers is one class and not a refactor.

Self-test your setup before a demo:

    python -m autofleet.llm
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterator, List, Optional

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def _load_dotenv() -> None:
    """Read KEY=VALUE lines from a local .env without adding a dependency.

    This MUST run before the constants below are evaluated. They are module-level,
    so if .env is only read later (say, inside a constructor) then
    AUTOFLEET_PROVIDER and AUTOFLEET_MODEL have already been fixed to their
    defaults and the file silently has no effect.
    """
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if not candidate.is_file():
            continue
        try:
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                # Tolerate `KEY = value` and quoted values — a stray space after
                # the equals sign is the most common way to get this wrong.
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            pass


_load_dotenv()   # before anything reads os.environ

PROVIDER = os.environ.get("AUTOFLEET_PROVIDER", "anthropic").strip().lower()

ANTHROPIC_MODEL = os.environ.get("AUTOFLEET_MODEL", "claude-opus-5")

# Groq retires model ids without notice — llama-3.3-70b-versatile was the
# default here and has since been removed from the free tier, which surfaces as
# a 404 and silently drops every agent to the deterministic fallback. Confirm
# what your account can actually reach before trusting a default:
#     python -m autofleet.llm --models
# gpt-oss-120b is the largest currently-listed chat model that supports the
# strict tool calling the Resource agent needs. Override with AUTOFLEET_MODEL.
GROQ_MODEL = os.environ.get("AUTOFLEET_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

# urllib's default User-Agent is fingerprint-blocked by Cloudflare in front of
# Groq (surfaces as Error 1010 / 403 before the request ever reaches the API),
# so every request from this module must identify itself properly.
_USER_AGENT = f"AutoFleetAI/{__import__('autofleet').__version__} (+python-urllib)"

# Agent turns are 1-3 sentences. Every number is pre-computed by the models, so
# there is no long-form reasoning to leave room for.
MAX_TOKENS = 1400

# Groq's free tier caps TOKENS PER MINUTE (8000), not requests (1000). A six-call
# chain therefore lives or dies on tokens-per-call, and MAX_TOKENS=1400 is a
# loaded gun: a chatty model will fill it and one incident exhausts the minute.
# Measured need is ~110 output tokens for a 1-3 sentence turn, so this is a
# generous ceiling that still fits ~5 chains per minute.
GROQ_MAX_TOKENS = int(os.environ.get("AUTOFLEET_GROQ_MAX_TOKENS", "400"))

# gpt-oss models emit hidden reasoning tokens that are billed as output and
# counted against the same budget. At default effort they spend most of the
# allowance thinking and return a SHORTER answer; at "low" they produce more
# usable text for fewer tokens. Measured, same prompt:
#   default effort -> 307 tokens total, 119 chars of answer, 541 of reasoning
#   reasoning=low  -> 253 tokens total, 291 chars of answer, 130 of reasoning
_REASONING_MODEL_HINTS = ("gpt-oss", "qwen3", "deepseek-r1")

EFFORT = os.environ.get("AUTOFLEET_EFFORT", "low")

# A short answer returns in seconds. The Anthropic SDK default timeout is 10
# minutes, which would let one hung call stall an entire incident.
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("AUTOFLEET_TIMEOUT", "25"))
MAX_RETRIES = 1

# `output_config.effort` is rejected on the Haiku tier and on older Sonnet, and
# has no equivalent on Groq. AUTOFLEET_MODEL exists so a cheaper model can be
# swapped in, so this has to be conditional or the cheap path breaks immediately.
_NO_EFFORT_PREFIXES = ("claude-haiku", "claude-3")
_NO_EFFORT_EXACT = {"claude-sonnet-4-5"}


# --------------------------------------------------------------------------
# Base: the contract, plus the fallback both providers share
# --------------------------------------------------------------------------

class LLM:
    """Interface + the deterministic fallback. Subclasses add a live path."""

    provider = "none"
    model = "deterministic-fallback"

    def __init__(self) -> None:
        self._error: Optional[str] = None

    # -- to be provided by subclasses --------------------------------------

    @property
    def live(self) -> bool:
        """A key is CONFIGURED. This is not proof the provider works.

        A configured key can still fail on every call — wrong key, retired
        model id, network block — and the chain then runs entirely on
        deterministic fallbacks. Only probe() proves the path works, and only
        an agent event's source == "live" proves a given turn used the model.
        Never report the system as live on the strength of this flag alone.
        """
        return False

    def _stream_live(
        self, *, system: str, user: str, fallback: str, tool: Optional[Dict],
        fallback_tool_input: Optional[Dict],
    ) -> Iterator[Dict]:
        raise NotImplementedError

    def probe(self) -> Dict:
        """One cheap call to prove the credential and model actually work."""
        return {"ok": False, "detail": "no live provider configured"}

    # -- shared ------------------------------------------------------------

    @property
    def status(self) -> Dict:
        return {
            "live": self.live,
            "provider": self.provider,
            "model": self.model if self.live else "deterministic-fallback",
            "effort": None,
            "note": self._error or f"Live agents on {self.model}.",
        }

    def stream(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        force_fallback: bool = False,
        tool: Optional[Dict] = None,
        fallback_tool_input: Optional[Dict] = None,
    ) -> Iterator[Dict]:
        """Yield {'text': ...} deltas, then one {'done': True, ...} summary.

        `force_fallback` is set by the chain when its wall-clock budget is spent.
        `tool` forces a schema-validated tool call instead of prose, and the
        terminal event then carries `tool_input`.
        """
        if not self.live or force_fallback:
            note = (
                "Chain budget spent — resolved from model output without the "
                "language layer." if force_fallback else None
            )
            yield from self._stream_fallback(
                fallback, note=note, tool_input=fallback_tool_input
            )
            return
        yield from self._stream_live(
            system=system, user=user, fallback=fallback,
            tool=tool, fallback_tool_input=fallback_tool_input,
        )

    def _stream_fallback(
        self, fallback: str, note: Optional[str] = None,
        tool_input: Optional[Dict] = None,
    ) -> Iterator[Dict]:
        started = time.perf_counter()
        delay = 0.0 if note else 0.018  # no typing delay when degrading — finish fast
        words = fallback.split(" ")
        for i, word in enumerate(words):
            if delay:
                time.sleep(delay)
            yield {"text": word if i == 0 else " " + word}
        yield {
            "done": True,
            "text": fallback,
            "tool_input": tool_input,
            "ms": int((time.perf_counter() - started) * 1000),
            "source": "degraded" if note else "fallback",
            "note": note or "Deterministic text derived from computed fleet state.",
        }

    def _fail_to_fallback(
        self, *, started: float, fallback: str, tool: Optional[Dict],
        fallback_tool_input: Optional[Dict], detail: str, reason: str,
    ) -> Iterator[Dict]:
        """Every live failure lands here, so a provider error costs the prose and
        never the resolution."""
        yield {"text": fallback}
        yield {
            "done": True,
            "text": fallback,
            "tool_input": fallback_tool_input,
            "tool_name": tool["name"] if tool else None,
            "ms": int((time.perf_counter() - started) * 1000),
            "source": "fallback",
            "note": f"{reason} ({detail}); used deterministic output instead.",
        }


# --------------------------------------------------------------------------
# Anthropic
# --------------------------------------------------------------------------

class AnthropicLLM(LLM):
    provider = "anthropic"
    model = ANTHROPIC_MODEL

    def __init__(self) -> None:
        super().__init__()
        self._client = None
        if not os.environ.get("ANTHROPIC_API_KEY"):
            self._error = "No ANTHROPIC_API_KEY found — running in simulated mode."
            return
        try:
            import anthropic  # lazy so offline mode needs no install
            self._client = anthropic.Anthropic(
                timeout=REQUEST_TIMEOUT_SECONDS, max_retries=MAX_RETRIES
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            self._error = f"Anthropic SDK unavailable ({exc}) — simulated mode."

    @property
    def live(self) -> bool:
        return self._client is not None

    @property
    def supports_effort(self) -> bool:
        return (
            not self.model.startswith(_NO_EFFORT_PREFIXES)
            and self.model not in _NO_EFFORT_EXACT
        )

    @property
    def status(self) -> Dict:
        effort = EFFORT if (self.live and self.supports_effort) else None
        return {
            "live": self.live,
            "provider": self.provider,
            "model": self.model if self.live else "deterministic-fallback",
            "effort": effort,
            "note": self._error or (
                f"Live agents on {self.model}"
                + (f" (effort={effort})." if effort
                   else " (this model has no effort parameter).")
            ),
        }

    def _kwargs(self) -> Dict:
        return {"output_config": {"effort": EFFORT}} if self.supports_effort else {}

    def probe(self) -> Dict:
        if not self.live:
            return {"ok": False, "detail": self._error or "not configured"}
        try:
            r = self._client.messages.create(
                model=self.model, max_tokens=16,
                messages=[{"role": "user", "content": "Reply with the word OK."}],
                **self._kwargs(),
            )
            text = next((b.text for b in r.content if b.type == "text"), "")
            return {"ok": True, "detail": f"replied {text.strip()[:40]!r}"}
        except Exception as exc:
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:300]}

    def _stream_live(
        self, *, system: str, user: str, fallback: str, tool: Optional[Dict],
        fallback_tool_input: Optional[Dict],
    ) -> Iterator[Dict]:
        started = time.perf_counter()
        collected: List[str] = []
        try:
            req = dict(
                model=self.model, max_tokens=MAX_TOKENS, system=system,
                messages=[{"role": "user", "content": user}], **self._kwargs(),
            )
            if tool is not None:
                req["tools"] = [tool]
                req["tool_choice"] = {"type": "tool", "name": tool["name"]}

            with self._client.messages.stream(**req) as stream:
                if tool is None:
                    for chunk in stream.text_stream:
                        collected.append(chunk)
                        yield {"text": chunk}
                else:
                    # Drain raw events so the SDK's timeout protection applies;
                    # the payload is on the assembled final message.
                    for _ in stream:
                        pass
                final = stream.get_final_message()

            usage = getattr(final, "usage", None)
            tokens = {
                "input": getattr(usage, "input_tokens", None),
                "output": getattr(usage, "output_tokens", None),
            } if usage else None

            if tool is not None:
                call = next(
                    (b for b in final.content
                     if getattr(b, "type", None) == "tool_use"), None
                )
                if call is None or not isinstance(getattr(call, "input", None), dict):
                    raise ValueError("model returned no tool_use block")
                data = call.input
                text = str(data.get("rationale") or "").strip() or fallback
                yield {"text": text}
                yield {
                    "done": True, "text": text, "tool_input": data,
                    "tool_name": tool["name"],
                    "ms": int((time.perf_counter() - started) * 1000),
                    "source": "live", "model": getattr(final, "model", self.model),
                    "tokens": tokens,
                }
                return

            text = "".join(collected).strip()
            if final.stop_reason == "refusal" or not text:
                reason = ("declined by safety classifier"
                          if final.stop_reason == "refusal" else "empty completion")
                yield from self._fail_to_fallback(
                    started=started, fallback=fallback, tool=tool,
                    fallback_tool_input=fallback_tool_input,
                    detail=reason, reason="Live call returned no usable text",
                )
                return

            yield {
                "done": True, "text": text,
                "ms": int((time.perf_counter() - started) * 1000),
                "source": "live", "model": getattr(final, "model", self.model),
                "tokens": tokens,
            }

        except Exception as exc:
            if collected and tool is None:
                text = "".join(collected).strip()
                yield {
                    "done": True, "text": text,
                    "ms": int((time.perf_counter() - started) * 1000),
                    "source": "live-partial",
                    "note": f"Stream interrupted ({type(exc).__name__}).",
                }
                return
            yield from self._fail_to_fallback(
                started=started, fallback=fallback, tool=tool,
                fallback_tool_input=fallback_tool_input,
                detail=f"{type(exc).__name__}: {exc}"[:160],
                reason="Live call failed",
            )


# --------------------------------------------------------------------------
# Groq — OpenAI-compatible, over stdlib urllib (no pip install required)
# --------------------------------------------------------------------------

class GroqLLM(LLM):
    provider = "groq"
    model = GROQ_MODEL

    def __init__(self) -> None:
        super().__init__()
        self._key = os.environ.get("GROQ_API_KEY")
        if not self._key:
            self._error = "No GROQ_API_KEY found — running in simulated mode."

    @property
    def live(self) -> bool:
        return bool(self._key)

    @property
    def status(self) -> Dict:
        return {
            "live": self.live,
            "provider": self.provider,
            "model": self.model if self.live else "deterministic-fallback",
            "effort": None,
            "note": self._error or f"Live agents on Groq · {self.model}.",
        }

    # -- transport ---------------------------------------------------------

    def _body(self, **over) -> Dict:
        """Base request body: model, a bounded token cap, and reasoning effort.

        Centralised so every call site (probe, tool call, stream) gets the same
        token discipline. Getting this wrong on one path is invisible until that
        path is the one that 429s mid-demo.
        """
        payload: Dict = {"model": self.model, "max_tokens": GROQ_MAX_TOKENS}
        if any(h in self.model.lower() for h in _REASONING_MODEL_HINTS):
            payload["reasoning_effort"] = EFFORT
        payload.update(over)
        return payload

    def _post(self, payload: Dict, *, stream: bool):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            GROQ_URL, data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if stream else "application/json",
                # Cloudflare sits in front of the Groq API and rejects urllib's
                # default "Python-urllib/3.x" signature with Error 1010 (access
                # denied) before the request ever reaches Groq — which looks
                # exactly like an auth failure but isn't. Identify properly.
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            return urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            # 429 is the expected failure on a free tier: the budget is
            # tokens-per-minute, so a burst of agents in one chain can hit it
            # even with plenty of requests left. Groq tells us how long to wait;
            # honour it once if it fits inside a single call's timeout, rather
            # than dropping the agent to a fallback the audience can see.
            if exc.code != 429:
                raise
            wait = self._retry_after_seconds(exc)
            if wait is None or wait > REQUEST_TIMEOUT_SECONDS:
                raise
            time.sleep(wait)
            return urllib.request.urlopen(
                urllib.request.Request(
                    GROQ_URL, data=body, method="POST",
                    headers=dict(req.headers),
                ),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

    @staticmethod
    def _retry_after_seconds(exc: urllib.error.HTTPError) -> Optional[float]:
        """Seconds Groq asks us to wait, from Retry-After or the reset header."""
        for header in ("retry-after", "x-ratelimit-reset-tokens",
                       "x-ratelimit-reset-requests"):
            raw = exc.headers.get(header) if exc.headers else None
            if not raw:
                continue
            raw = str(raw).strip()
            try:
                return float(raw)          # plain seconds
            except ValueError:
                pass
            # Groq also uses compact durations like "33.45s", "1m26.4s", "600ms"
            match = re.fullmatch(
                r"(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?|(\d+(?:\.\d+)?)ms",
                raw,
            )
            if not match:
                continue
            minutes, seconds, millis = match.groups()
            if millis is not None:
                return float(millis) / 1000.0
            if minutes or seconds:
                return float(minutes or 0) * 60.0 + float(seconds or 0)
        return None

    @staticmethod
    def _explain(exc: Exception) -> str:
        """Turn an HTTPError into something actionable rather than a bare code."""
        if isinstance(exc, urllib.error.HTTPError):
            try:
                detail = json.loads(exc.read().decode("utf-8", "replace"))
                msg = (detail.get("error") or {}).get("message") or str(detail)
            except Exception:
                msg = exc.reason
            # Status code first — it is the reliable signal. Matching on message
            # text before it means a 401 whose body happens to mention "model"
            # gets told to check its model instead of its key.
            hints = {
                401: " — check GROQ_API_KEY",
                403: " — key rejected; check GROQ_API_KEY permissions",
                404: " — check console.groq.com/docs/models and set AUTOFLEET_MODEL",
                429: " — free-tier rate limit; wait and retry",
            }
            hint = hints.get(exc.code, "")
            # A Cloudflare edge block is not an auth problem, and saying "check
            # your key" would send you hunting in the wrong place.
            if "1010" in str(msg) or "cloudflare" in str(msg).lower():
                hint = (" — Cloudflare edge block, not an auth failure. The "
                        "request never reached Groq; check the User-Agent header.")
            elif not hint and "model" in str(msg).lower():
                hint = " — check console.groq.com/docs/models and set AUTOFLEET_MODEL"
            return f"HTTP {exc.code}: {str(msg)[:180]}{hint}"
        return f"{type(exc).__name__}: {exc}"[:200]

    @staticmethod
    def _to_openai_tool(tool: Dict) -> Dict:
        """Anthropic tool shape -> OpenAI function shape.

        Anthropic nests the schema under `input_schema` and puts `strict` at the
        top level; OpenAI wraps everything in a `function` object and calls the
        schema `parameters`.
        """
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool["input_schema"],
            },
        }

    def probe(self) -> Dict:
        if not self.live:
            return {"ok": False, "detail": self._error or "not configured"}
        try:
            with self._post(self._body(
                max_tokens=96,
                messages=[{"role": "user", "content": "Reply with the word OK."}],
            ), stream=False) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            text = (data["choices"][0]["message"].get("content") or "").strip()
            return {"ok": True, "detail": f"replied {text[:40]!r}"}
        except Exception as exc:
            return {"ok": False, "detail": self._explain(exc)}

    # -- live path ---------------------------------------------------------

    def _stream_live(
        self, *, system: str, user: str, fallback: str, tool: Optional[Dict],
        fallback_tool_input: Optional[Dict],
    ) -> Iterator[Dict]:
        started = time.perf_counter()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        # Tool path: one non-streaming call. The arguments arrive as a JSON
        # *string* that has to be parsed, unlike Anthropic's pre-parsed dict.
        if tool is not None:
            try:
                with self._post(self._body(
                    messages=messages,
                    tools=[self._to_openai_tool(tool)],
                    tool_choice={"type": "function",
                                 "function": {"name": tool["name"]}},
                ), stream=False) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))

                calls = (data["choices"][0]["message"] or {}).get("tool_calls") or []
                if not calls:
                    raise ValueError("model returned no tool_calls")
                args = calls[0]["function"]["arguments"]
                parsed = json.loads(args) if isinstance(args, str) else args
                if not isinstance(parsed, dict):
                    raise ValueError("tool arguments were not an object")

                text = str(parsed.get("rationale") or "").strip() or fallback
                usage = data.get("usage") or {}
                yield {"text": text}
                yield {
                    "done": True, "text": text, "tool_input": parsed,
                    "tool_name": tool["name"],
                    "ms": int((time.perf_counter() - started) * 1000),
                    "source": "live", "model": data.get("model", self.model),
                    "tokens": {"input": usage.get("prompt_tokens"),
                               "output": usage.get("completion_tokens")},
                }
                return
            except Exception as exc:
                yield from self._fail_to_fallback(
                    started=started, fallback=fallback, tool=tool,
                    fallback_tool_input=fallback_tool_input,
                    detail=self._explain(exc), reason="Groq tool call failed",
                )
                return

        # Text path: server-sent events, parsed off the raw socket.
        collected: List[str] = []
        model_used = self.model
        try:
            with self._post(self._body(
                messages=messages, stream=True,
            ), stream=True) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        event = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    model_used = event.get("model", model_used)
                    for choice in event.get("choices", []):
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            collected.append(piece)
                            yield {"text": piece}

            text = "".join(collected).strip()
            if not text:
                yield from self._fail_to_fallback(
                    started=started, fallback=fallback, tool=None,
                    fallback_tool_input=fallback_tool_input,
                    detail="empty completion",
                    reason="Groq returned no usable text",
                )
                return

            yield {
                "done": True, "text": text,
                "ms": int((time.perf_counter() - started) * 1000),
                "source": "live", "model": model_used,
            }

        except Exception as exc:
            if collected:
                yield {
                    "done": True, "text": "".join(collected).strip(),
                    "ms": int((time.perf_counter() - started) * 1000),
                    "source": "live-partial",
                    "note": f"Stream interrupted ({type(exc).__name__}).",
                }
                return
            yield from self._fail_to_fallback(
                started=started, fallback=fallback, tool=None,
                fallback_tool_input=fallback_tool_input,
                detail=self._explain(exc), reason="Groq call failed",
            )


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

PROVIDERS = {"anthropic": AnthropicLLM, "groq": GroqLLM}


def make_llm() -> LLM:
    """Build the configured provider. An unknown name falls back to Anthropic
    rather than crashing the server on a typo."""
    cls = PROVIDERS.get(PROVIDER)
    if cls is None:
        client = AnthropicLLM()
        client._error = (
            f"Unknown AUTOFLEET_PROVIDER={PROVIDER!r} (expected "
            f"{'/'.join(PROVIDERS)}) — simulated mode."
        )
        client._client = None
        return client
    return cls()


def list_groq_models() -> None:
    """Print the models this Groq key can actually reach.

    Groq removes ids from the free tier without warning, and a retired id looks
    exactly like a working setup until you check an agent's source field. This
    asks the account rather than trusting a hardcoded default.
    """
    import urllib.error
    import urllib.request

    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        print("  GROQ_API_KEY is not set — nothing to list.")
        return
    req = urllib.request.Request(
        GROQ_MODELS_URL,
        headers={"Authorization": f"Bearer {key}", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ids = sorted(m["id"] for m in json.load(r).get("data", []))
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} listing models: {e.read().decode('utf-8', 'replace')[:200]}")
        return
    except Exception as e:  # network, DNS, TLS
        print(f"  {type(e).__name__} listing models: {e}")
        return

    skip = ("whisper", "tts", "guard", "embed", "orpheus")
    chat = [i for i in ids if not any(k in i.lower() for k in skip)]
    print(f"  {len(ids)} models on this account, {len(chat)} usable for chat:\n")
    for i in chat:
        mark = "  <-- configured" if i == GROQ_MODEL else ""
        print(f"    {i}{mark}")
    if GROQ_MODEL not in ids:
        print(f"\n  !! AUTOFLEET_MODEL / default '{GROQ_MODEL}' is NOT in this list.")
        print("     That is a 404 on every agent call, and the chain will run")
        print("     entirely on deterministic fallbacks. Pick one from above.")


if __name__ == "__main__":  # python -m autofleet.llm
    if "--models" in sys.argv:
        print()
        print("AutoFleet AI — models reachable with this key")
        print("=" * 58)
        list_groq_models()
        print("=" * 58)
        print()
        raise SystemExit(0)

    client = make_llm()
    s = client.status
    print()
    print("AutoFleet AI — model setup check")
    print("=" * 58)
    print(f"  provider  {s['provider']}")
    print(f"  model     {s['model']}")
    print(f"  key set   {s['live']}   (configured — NOT yet proven to work)")
    print(f"  note      {s['note']}")
    if client.live:
        print("  probing   ...", end=" ", flush=True)
        r = client.probe()
        print("OK" if r["ok"] else "FAILED")
        print(f"            {r['detail']}")
        if r["ok"]:
            print()
            print("  VERIFIED — agents will use the model. This is the only")
            print("  output that proves it; a key being set does not.")
        else:
            print()
            print("  NOT VERIFIED. The chain still runs, but every agent falls")
            print("  back to deterministic text — the demo will look fine while")
            print("  using no AI at all. Each agent card is labelled 'simulated'.")
            print()
            print("  See what this account can actually reach:")
            print("    python -m autofleet.llm --models")
    else:
        print()
        print("  Set a key to go live:")
        print("    Anthropic  ANTHROPIC_API_KEY=...   (AUTOFLEET_PROVIDER=anthropic)")
        print("    Groq       GROQ_API_KEY=...        (AUTOFLEET_PROVIDER=groq)")
    print("=" * 58)
    print()
