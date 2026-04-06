# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
cp .env.example .env   # fill in API keys
pip install -r requirements.txt
```

Required `.env` variables:
- `DEFAULT_PROVIDER`: `openai` | `google` | `local`
- `DEFAULT_MODEL`: e.g. `gpt-4o`
- `OPENAI_API_KEY` or `GEMINI_API_KEY` (depending on provider)
- `LOCAL_MODEL_PATH`: path to `.gguf` file (only for `local` provider)

## Running

There is no single entrypoint script in the skeleton — students build one. The test for the local provider is runnable directly:

```bash
python tests/test_local.py
```

Run pytest (no test suite is currently configured beyond the local smoke test):

```bash
pytest tests/
```

## Architecture

This is a lab skeleton for a **ReAct (Reasoning + Acting) Agent** on top of an abstracted LLM provider layer.

### Provider layer (`src/core/`)

`LLMProvider` (abstract base) defines two methods all providers must implement:
- `generate(prompt, system_prompt)` → `dict` with keys `content`, `usage`, `latency_ms`, `provider`
- `stream(prompt, system_prompt)` → generator of string tokens

Three concrete providers:
- `OpenAIProvider` — uses `openai` SDK, passes system prompt as a system message
- `GeminiProvider` — uses `google-generativeai`, prepends system prompt as `"System: ..."` text
- `LocalProvider` — uses `llama-cpp-python` with GGUF models; formats prompts in Phi-3 chat template (`<|system|>`, `<|user|>`, `<|assistant|>` tags); stops on `<|end|>` or `Observation:`

### Agent (`src/agent/agent.py`)

`ReActAgent` is the main skeleton to implement. It holds:
- `self.llm`: a `LLMProvider` instance
- `self.tools`: list of dicts with `name` and `description` keys
- `self.history`: conversation accumulator
- `get_system_prompt()`: builds the ReAct format instruction with tool list
- `run(user_input)`: the main loop — **this is the core TODO**
- `_execute_tool(tool_name, args)`: dispatches to tool functions — **also a TODO**

The ReAct loop pattern expected: `Thought → Action → Observation` cycles, terminating on `Final Answer`.

### Telemetry (`src/telemetry/`)

- `logger.py` exports a global `logger` (`IndustryLogger`); logs JSON-structured events to `logs/YYYY-MM-DD.log` and console
- `metrics.py` exports a global `tracker` (`PerformanceTracker`); call `tracker.track_request(provider, model, usage, latency_ms)` after each LLM call

### Extension point

`src/tools/` is the designated directory for custom tool implementations (currently empty in skeleton).

## Key implementation notes

- `LLMProvider.generate()` returns a `dict`, not a string — access `.content` for the text
- The `LocalProvider` stop sequence includes `"Observation:"` to prevent the local model from self-hallucinating tool results
- `GeminiProvider` accesses token counts via `response.usage_metadata` (not `.usage` like OpenAI)
- Logs accumulate in `logs/` daily; inspect them for failure analysis (hallucinations, parse errors, infinite loops)

## Lab deliverables

See `SCORING.md` for grading. Reports go in:
- `report/group_report/` (use `TEMPLATE_GROUP_REPORT.md`)
- `report/individual_reports/` (use `TEMPLATE_INDIVIDUAL_REPORT.md`)
