# Individual Report: Lab 3 - Chatbot vs ReAct Agent

- **Student Name**: Tan Long
- **Student ID**: 2A202600168
- **Date**: 2026-04-06

---

## I. Technical Contribution (15 Points)

### Modules Implemented

| File | Contribution |
| :--- | :--- |
| `src/agent/agent.py` | Fixed `_parse_args()`, improved system prompt, added `TOOL_ERROR` logging |
| `src/tools/vnstock_tools.py` | Full rewrite with dual-source fallback, 5 tools, shared helpers |
| `src/telemetry/logger.py` | Used as-is; integrated `SOURCE_FALLBACK` and `TOOL_ERROR` event types |

---

### `_parse_args()` — Argument Parser Fix

The agent's argument parser only handled `key=value` and positional formats. When GPT-4o emitted JSON-style arguments like `get_company_profile({"symbol": "VJC"})`, the entire JSON string was passed as the `symbol` value, crashing the tool.

**Fix** — added JSON detection as the first branch:

```python
def _parse_args(args_str: str) -> dict:
    args_str = args_str.strip()
    if not args_str:
        return {}

    # NEW: try JSON object first
    if args_str.startswith("{"):
        try:
            parsed = json.loads(args_str)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # existing: key=value regex
    kv_pattern = re.compile(r'(\w+)\s*=\s*(".*?"|\'.*?\'|\S+)')
    ...
```

This single addition eliminated the most common parse failure class in the logs.

---

### Dual-Source Fallback Pattern — `vnstock_tools.py`

All data tools follow the same resilience pattern: try primary source, log `SOURCE_FALLBACK` if it fails, retry with secondary source, return a descriptive error only if both fail.

```python
def get_income_statement(symbol: str, period: str = "quarter") -> Dict[str, Any]:
    sym = symbol.upper().strip()

    # Primary: KBS (structured long format)
    try:
        df = _finance_kbs(sym).income_statement(period=period)
        if df is not None and not df.empty:
            pivot = _kbs_pivot(df, n_periods=2)
            if pivot["periods"]:
                return {"symbol": sym, "source": "KBS", **pivot}
    except Exception as e:
        _warn_fallback("get_income_statement", "KBS", "VCI", e)  # logs SOURCE_FALLBACK

    # Fallback: VCI
    try:
        s = _stock(sym)
        df = s.finance.income_statement(period=period, lang="vi")
        ...
        return {"symbol": sym, "source": "VCI", "periods": periods, "data": data}
    except Exception:
        pass

    return {"error": f"Không thể lấy KQKD cho mã {sym}."}
```

Each tool returns a `"source"` field so the agent and logs can distinguish which data source was actually used.

---

### `get_company_profile()` — API Migration

The skeleton called `s.company.profile()` which appears in `dir()` via Python's `__getattr__` but raises `AttributeError` at runtime because the VCI data source does not implement it. I discovered this by inspecting the traceback from the log and calling `dir(s.company)` interactively.

```python
# Before (broken)
profile_df = s.company.profile()

# After (correct)
overview_df = s.company.overview()   # returns DataFrame with company_profile, icb_name3, etc.
officers_df = s.company.officers()  # unchanged
```

---

### `get_financial_ratios()` — MultiIndex Serialization Fix

The original `s.finance.ratio()` returns a DataFrame with MultiIndex columns (category, metric name as tuple). Calling `json.dumps()` on this dict raises `TypeError: keys must be str, not tuple`.

Replaced with `Finance(symbol, source="KBS").ratio()` which returns a clean long-format DataFrame with `item_id` string keys. Added VCI fallback that flattens the MultiIndex with:

```python
df.columns = [
    " ".join(filter(None, col)).strip() if isinstance(col, tuple) else col
    for col in df.columns
]
```

---

### Telemetry Integration — `SOURCE_FALLBACK` and `TOOL_ERROR`

Added two new event types to the log:

```python
# In vnstock_tools.py — when primary source fails
logger.log_event("SOURCE_FALLBACK", {
    "tool": tool,
    "primary": primary,
    "fallback": fallback,
    "reason": f"{type(exc).__name__}: {str(exc)[:120]}",
})

# In agent.py — when tool returns {"error": ...}
if "error" in result:
    logger.error(
        f"TOOL_ERROR tool={tool_name} args={kwargs} error={result['error']}",
        exc_info=False,
    )
```

This made failures visible without crashing the agent — the log now clearly distinguishes between "source fell back silently" and "both sources failed".

---

## II. Debugging Case Study (10 Points)

### Problem: JSON Argument Not Parsed — `get_company_profile` Always Fails

**Description**: Every query asking about company leadership (CEO, chairman) failed silently. The agent would retry once then give up with "Xin lỗi, không thể lấy thông tin".

**Log Evidence** (`logs/2026-04-06.log`):

```json
{"event": "LLM_OUTPUT", "data": {"step": 0,
  "output": "Action: get_company_profile({\"symbol\": \"VJC\"})"}}

{"event": "TOOL_CALL", "data": {
  "tool": "get_company_profile",
  "args": {"symbol": "{\"symbol\": \"VJC\"}"}}}

{"event": "TOOL_RESULT", "data": {"result": {
  "error": "ValueError: Invalid symbol. Your symbol format is not recognized!"}}}
```

The smoking gun is in the `TOOL_CALL` event: `args.symbol` is `'{"symbol": "VJC"}'` — the entire JSON string, not `"VJC"`. This means `_parse_args()` received `{"symbol": "VJC"}` and because it couldn't match `key=value` regex on JSON, fell through to the positional fallback which returned `{"symbol": '{"symbol": "VJC"}'}`.

**Diagnosis**: `_parse_args()` was written expecting LLM output like `symbol="VJC"` or just `VJC`. GPT-4o frequently generates function calls as Python-dict literals: `func({"key": "val"})`. Neither branch of the original parser handled this case.

**Solution**: Prepend a `json.loads()` attempt before the regex. If `args_str` starts with `{` and is valid JSON returning a `dict`, use it directly. The fix is 6 lines and covers the most common LLM calling convention.

**Outcome**: After fix, `ACTION_PARSED` correctly shows `args: {"symbol": "VJC"}` and `TOOL_CALL` receives `{"symbol": "VJC"}`. All leadership queries succeed.

---

## III. Personal Insights: Chatbot vs ReAct (10 Points)

### 1. Reasoning: How `Thought` blocks improve answer quality

A plain chatbot (GPT-4o with no tools) answers "Giá FPT hôm nay?" by retrieving from training data — which is frozen at the knowledge cutoff. It will confidently state an outdated price with no indication of staleness.

The ReAct agent's `Thought` block forces a different reasoning path:

```
Thought: Câu hỏi về giá cổ phiếu FPT hiện tại.
         Tôi cần dùng get_stock_price để lấy dữ liệu thực.
Action: get_stock_price(symbol="FPT")
Observation: {"close_vnd": 96400, "date": "2025-12-31", ...}
Thought: Đã có giá. Trả lời.
Final Answer: Giá FPT phiên gần nhất (31/12/2025) là 96,400 VND.
```

The `Thought` step acts as an explicit planning gate — the model must decide *which tool* answers the question before acting. This separates "what I know" from "what I should look up", preventing the model from blending training-time facts with real-time queries.

### 2. Reliability: When the Agent performs worse than the Chatbot

The agent has observable failure modes the chatbot avoids:

- **Latency**: Every agent response requires 2–3 LLM calls + tool API calls. P50=1,359ms vs. a chatbot's ~600ms single call. For simple factual questions already in training data (e.g., "Vinamilk là công ty gì?"), the agent is slower for no gain.
- **Argument hallucination**: The LLM occasionally invents plausible-but-wrong arguments. Example: when asked about FLC cash flow, the model called `get_cash_flow(symbol="FLC", quarter=2, year=2024)` without being asked for Q2/2024 specifically. A chatbot would have asked for clarification.
- **Cascading errors**: When a tool returns `{"error": ...}`, the LLM sometimes retries with the identical arguments (same bug, same error) before giving up — consuming tokens and time. The chatbot simply does not have this failure mode.
- **False refusals (before prompt fix)**: The system prompt's aggressive out-of-scope rule caused the agent to refuse "Gửi tôi báo cáo lưu chuyển tiền tệ FPT Q4 2025" — a perfectly valid stock question — because the phrasing was unusual. The chatbot would have answered it (albeit with potentially stale data).

### 3. Observation: How environment feedback shapes next steps

Observations are the mechanism by which the agent self-corrects. Two concrete examples from the session:

**Positive feedback loop**: After receiving a real stock price from `get_stock_price`, the agent in the portfolio P&L case correctly computed `(giá_hiện_tại − giá_mua) × số_lượng` in the next `Thought` block — demonstrating that numerical observation data was integrated into arithmetic reasoning.

**Negative feedback (partial)**: When `get_company_profile` returned `{"error": "ValueError: Invalid symbol"}`, the agent's observation was the error string. Its next `Thought` was to retry — but without changing the argument format (since it didn't know the root cause was the parser, not the symbol). This shows the limit of environment feedback: the agent can observe *that* something failed, but not always *why* at the implementation level. The fix had to come from the developer (adding JSON parsing), not from the agent's own reasoning.

---

## IV. Future Improvements (5 Points)

### Scalability — Async Tool Execution

The current loop executes tools synchronously, one at a time. For multi-step queries that require independent data (e.g., "So sánh P/E của FPT và VNM"), two `get_financial_ratios` calls could run in parallel. Using `asyncio.gather()` or a ThreadPoolExecutor would cut wall-clock time roughly in half for such cases.

A more complete solution would migrate to **LangGraph**, which natively supports parallel branches, conditional routing (e.g., only fetch cash flow if financial ratio query fails), and human-in-the-loop checkpoints for high-stakes operations.

### Safety — Argument Validation Layer

Currently, tool arguments are parsed and passed directly to the vnstock API. A validation layer between `_parse_args()` and `_execute_tool()` would enforce:

- **Symbol whitelist check**: Reject symbols not found in the HOSE/HNX/UPCOM listing (call `Vnstock().stock_screener()` once at startup and cache).
- **Type coercion**: Ensure `quarter` is always `int` in `[1, 4]`, `year` is a plausible range.
- **Input length cap**: Prevent prompt injection via long `symbol` strings.

A "Supervisor LLM" pattern (a second, cheaper model that audits tool calls before execution) would catch semantic errors — e.g., the agent calling `get_cash_flow` when the user asked about dividends.

### Performance — Tool Retrieval with Vector DB

With 5 tools the full spec fits comfortably in the system prompt (~300 tokens). At 50+ tools, this becomes expensive and degrades reasoning quality. The standard solution is **tool retrieval**: embed all tool descriptions into a vector DB (e.g., Qdrant, pgvector), then at each step retrieve the top-k most relevant tools based on the current `Thought` and inject only those into the prompt.

This reduces prompt token cost per call and keeps the LLM's attention focused on the tools actually needed, reducing hallucinated tool names.

### Reliability — Cost-Aware Retry Budget

The current retry logic is fixed (try primary → try fallback → return error). A production system should track a per-request budget: total tokens consumed, cost estimate, and number of tool failures. If the budget is exceeded mid-session, the agent should summarize what it has learned so far and explain what it could not complete, rather than silently giving up or continuing to spend tokens retrying a broken data source.

---

> [!NOTE]
> Submitted as `REPORT_TanLong.md` in `report/individual_reports/`.
