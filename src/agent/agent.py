import json
import re
from typing import Any, Dict, List, Optional

from src.core.llm_provider import LLMProvider
from src.telemetry.logger import logger
from src.telemetry.metrics import tracker


# ── Tool registry ──────────────────────────────────────────────────────────────
TOOL_SPECS = [
    {
        "name": "get_stock_price",
        "description": (
            "Lấy giá cổ phiếu Việt Nam hiện tại (phiên gần nhất). "
            "Tham số: symbol (string) — mã cổ phiếu, ví dụ FPT, VNM, VIC."
        ),
    },
    {
        "name": "get_financial_ratios",
        "description": (
            "Lấy chỉ số tài chính (P/E, P/B, ROE, ROA, EPS...) của một cổ phiếu. "
            "Tham số: symbol (string) — mã cổ phiếu."
        ),
    },
    {
        "name": "get_cash_flow",
        "description": (
            "Lấy báo cáo lưu chuyển tiền tệ (BCLCTT) theo quý. "
            "Tham số: symbol (string), quarter (int 1–4, mặc định 1), year (int, mặc định năm hiện tại)."
        ),
    },
    {
        "name": "get_company_profile",
        "description": (
            "Lấy thông tin công ty: mô tả, ngành nghề, danh sách ban lãnh đạo (CEO, Chủ tịch HĐQT...). "
            "Tham số: symbol (string) — mã cổ phiếu."
        ),
    },
    {
        "name": "get_income_statement",
        "description": (
            "Lấy báo cáo kết quả kinh doanh (doanh thu, lợi nhuận gộp, lợi nhuận ròng, chi phí...). "
            "Tham số: symbol (string) — mã cổ phiếu; period (string, tùy chọn) — 'quarter' (mặc định) hoặc 'year'."
        ),
    },
]

# ── System prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT_TEMPLATE = """Bạn là trợ lý chuyên về **thị trường chứng khoán Việt Nam**.

PHẠM VI HOẠT ĐỘNG:
- CHỈ trả lời các câu hỏi liên quan đến cổ phiếu, tài chính doanh nghiệp niêm yết trên HOSE/HNX/UPCOM.
- Các câu hỏi IN-SCOPE bao gồm: giá cổ phiếu, chỉ số tài chính (P/E, ROE...), báo cáo lưu chuyển tiền tệ (BCLCTT), thông tin ban lãnh đạo, hồ sơ công ty của các mã CP như FPT, VNM, VIC, VJC, HPG, v.v.
- Nếu câu hỏi RÕ RÀNG nằm NGOÀI phạm vi (giá vàng, thời tiết, tin tức chính trị, nấu ăn, v.v.) hãy từ chối lịch sự mà KHÔNG gọi tool nào. Viết:
  Final Answer: Xin lỗi, tôi chỉ hỗ trợ thông tin về chứng khoán Việt Nam. Câu hỏi của bạn nằm ngoài phạm vi của tôi.
- Nếu không chắc, hãy ưu tiên GỌI TOOL để kiểm tra thay vì từ chối.

CÔNG CỤ CÓ SẴN:
{tool_descriptions}

QUY TRÌNH SUY LUẬN (ReAct):
Bạn PHẢI tuân theo định dạng sau, từng bước một:

Thought: <phân tích câu hỏi, xác định domain, lên kế hoạch>
Action: <tên_tool>(<tham số dạng JSON key=value hoặc positional>)
Observation: <kết quả tool — do hệ thống điền>
Thought: <đánh giá kết quả, cần thêm thông tin không?>
... (lặp lại nếu cần)
Final Answer: <câu trả lời cuối cùng, đầy đủ, format đẹp bằng tiếng Việt>

QUY TẮC BẮT BUỘC:
1. Mỗi lần chỉ gọi MỘT Action.
2. Sau mỗi Action, DỪNG HOÀN TOÀN và chờ Observation — TUYỆT ĐỐI không tự bịa số liệu.
3. Với bất kỳ câu hỏi nào về giá cổ phiếu, chỉ số tài chính, BCLCTT, hay thông tin lãnh đạo — bạn PHẢI gọi tool tương ứng, không được dùng kiến thức có sẵn.
4. Nếu tool trả về lỗi (mã CP sai, timeout), thử lại tối đa 1 lần với mã viết hoa.
5. Với UC danh mục (ví dụ: "tôi mua X cổ phiếu Y với giá Z"), sau khi lấy được giá hiện tại, hãy tính: lãi/lỗ = (giá_hiện_tại − giá_mua) × số_lượng.
6. Với BCLCTT, format kết quả thành bảng rõ ràng với đơn vị tỷ VND.
7. Với thông tin lãnh đạo, lọc và hiển thị tên + chức vụ rõ ràng từ kết quả tool.
"""


class ReActAgent:
    """
    ReAct Agent chuyên về thị trường chứng khoán Việt Nam.
    Vòng lặp: Thought → Action → Observation → ... → Final Answer
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_steps: int = 8,
    ):
        self.llm = llm
        self.tools = tools if tools is not None else TOOL_SPECS
        self.max_steps = max_steps

    # ── Prompt builders ────────────────────────────────────────────────────────

    def get_system_prompt(self) -> str:
        tool_descriptions = "\n".join(
            f"- **{t['name']}**: {t['description']}" for t in self.tools
        )
        return SYSTEM_PROMPT_TEMPLATE.format(tool_descriptions=tool_descriptions)

    # ── Tool execution ─────────────────────────────────────────────────────────

    def _execute_tool(self, tool_name: str, args_str: str) -> str:
        """Parse args và gọi tool tương ứng."""
        from src.tools.vnstock_tools import (
            get_cash_flow,
            get_company_profile,
            get_financial_ratios,
            get_income_statement,
            get_stock_price,
        )

        tool_map = {
            "get_stock_price": get_stock_price,
            "get_financial_ratios": get_financial_ratios,
            "get_cash_flow": get_cash_flow,
            "get_company_profile": get_company_profile,
            "get_income_statement": get_income_statement,
        }

        if tool_name not in tool_map:
            return json.dumps({"error": f"Tool '{tool_name}' không tồn tại."}, ensure_ascii=False)

        try:
            kwargs = _parse_args(args_str)
            logger.log_event("TOOL_CALL", {"tool": tool_name, "args": kwargs})
            result = tool_map[tool_name](**kwargs)
            logger.log_event("TOOL_RESULT", {"tool": tool_name, "result": result})
            if "error" in result:
                logger.error(f"TOOL_ERROR tool={tool_name} args={kwargs} error={result['error']}", exc_info=False)
            return json.dumps(result, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            err = {"error": str(e)}
            logger.error(f"TOOL_EXCEPTION tool={tool_name} args={kwargs} error={e}")
            return json.dumps(err, ensure_ascii=False)

    # ── Main ReAct loop ────────────────────────────────────────────────────────

    def run(self, user_input: str) -> str:
        logger.log_event("AGENT_START", {"input": user_input, "model": self.llm.model_name})

        # Conversation history: list of {"role": ..., "content": ...}
        # We'll build a single growing prompt string for simplicity with non-chat providers
        scratchpad = f"Question: {user_input}\n"
        steps = 0

        while steps < self.max_steps:
            # ── 1. Ask LLM ───────────────────────────────────────────────────
            result = self.llm.generate(
                prompt=scratchpad,
                system_prompt=self.get_system_prompt(),
            )
            tracker.track_request(
                provider=result.get("provider", "unknown"),
                model=self.llm.model_name,
                usage=result.get("usage", {}),
                latency_ms=result.get("latency_ms", 0),
            )

            llm_output = result["content"].strip()

            # Truncate at the first self-generated "Observation:" to prevent hallucinated tool results
            obs_idx = llm_output.find("\nObservation:")
            if obs_idx != -1:
                llm_output = llm_output[:obs_idx].strip()

            logger.log_event("LLM_OUTPUT", {"step": steps, "output": llm_output})
            scratchpad += "\n" + llm_output + "\n"

            # ── 2. Check for Final Answer ────────────────────────────────────
            final = _extract_final_answer(llm_output)
            if final is not None:
                logger.log_event("AGENT_END", {"steps": steps, "outcome": "final_answer"})
                return final

            # ── 3. Parse Action ──────────────────────────────────────────────
            action = _extract_action(llm_output)
            if action is None:
                # No action and no final answer — ask LLM to continue
                scratchpad += "Thought: Tôi cần tiếp tục phân tích hoặc đưa ra Final Answer.\n"
                steps += 1
                continue

            tool_name, args_str = action
            logger.log_event("ACTION_PARSED", {"tool": tool_name, "args": args_str})

            # ── 4. Execute tool & append Observation ─────────────────────────
            observation = self._execute_tool(tool_name, args_str)
            scratchpad += f"Observation: {observation}\n"

            steps += 1

        # Fallback: exceeded max steps
        logger.log_event("AGENT_END", {"steps": steps, "outcome": "max_steps_exceeded"})
        fallback_result = self.llm.generate(
            prompt=scratchpad + "\nThought: Đã đủ thông tin. Hãy tổng hợp và trả lời.\nFinal Answer:",
            system_prompt=self.get_system_prompt(),
        )
        return "Final Answer: " + fallback_result["content"].strip()

    def run_with_trace(self, user_input: str) -> Dict[str, Any]:
        """
        Giống run(), nhưng trả về thêm trace để phục vụ UI so sánh.
        Không đổi hành vi của agent; chỉ gom số liệu.

        Returns dict:
          - final_answer: str
          - steps: int
          - llm_calls: list[{content, usage, latency_ms, provider}]
          - tool_calls: list[{tool, args, observation_json}]
          - totals: {prompt_tokens, completion_tokens, total_tokens, latency_ms}
        """
        logger.log_event("AGENT_START", {"input": user_input, "model": self.llm.model_name})

        scratchpad = f"Question: {user_input}\n"
        steps = 0

        llm_calls: List[Dict[str, Any]] = []
        tool_calls: List[Dict[str, Any]] = []

        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        total_latency_ms = 0

        while steps < self.max_steps:
            result = self.llm.generate(
                prompt=scratchpad,
                system_prompt=self.get_system_prompt(),
            )
            tracker.track_request(
                provider=result.get("provider", "unknown"),
                model=self.llm.model_name,
                usage=result.get("usage", {}),
                latency_ms=result.get("latency_ms", 0),
            )

            usage = result.get("usage") or {}
            total_prompt_tokens += int(usage.get("prompt_tokens") or 0)
            total_completion_tokens += int(usage.get("completion_tokens") or 0)
            total_tokens += int(usage.get("total_tokens") or 0)
            total_latency_ms += int(result.get("latency_ms") or 0)

            llm_output = (result.get("content") or "").strip()

            obs_idx = llm_output.find("\nObservation:")
            if obs_idx != -1:
                llm_output = llm_output[:obs_idx].strip()

            llm_calls.append(
                {
                    "content": llm_output,
                    "usage": usage,
                    "latency_ms": result.get("latency_ms", 0),
                    "provider": result.get("provider", "unknown"),
                }
            )

            logger.log_event("LLM_OUTPUT", {"step": steps, "output": llm_output})
            scratchpad += "\n" + llm_output + "\n"

            final = _extract_final_answer(llm_output)
            if final is not None:
                logger.log_event("AGENT_END", {"steps": steps, "outcome": "final_answer"})
                return {
                    "final_answer": final,
                    "steps": steps,
                    "llm_calls": llm_calls,
                    "tool_calls": tool_calls,
                    "totals": {
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_tokens,
                        "latency_ms": total_latency_ms,
                    },
                }

            action = _extract_action(llm_output)
            if action is None:
                scratchpad += "Thought: Tôi cần tiếp tục phân tích hoặc đưa ra Final Answer.\n"
                steps += 1
                continue

            tool_name, args_str = action
            logger.log_event("ACTION_PARSED", {"tool": tool_name, "args": args_str})

            observation = self._execute_tool(tool_name, args_str)
            tool_calls.append(
                {
                    "tool": tool_name,
                    "args": args_str,
                    "observation_json": observation,
                }
            )
            scratchpad += f"Observation: {observation}\n"
            steps += 1

        logger.log_event("AGENT_END", {"steps": steps, "outcome": "max_steps_exceeded"})
        fallback_result = self.llm.generate(
            prompt=scratchpad + "\nThought: Đã đủ thông tin. Hãy tổng hợp và trả lời.\nFinal Answer:",
            system_prompt=self.get_system_prompt(),
        )
        llm_calls.append(
            {
                "content": (fallback_result.get("content") or "").strip(),
                "usage": fallback_result.get("usage") or {},
                "latency_ms": fallback_result.get("latency_ms", 0),
                "provider": fallback_result.get("provider", "unknown"),
            }
        )
        final_answer = (fallback_result.get("content") or "").strip()
        return {
            "final_answer": final_answer,
            "steps": steps,
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "totals": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": total_latency_ms + int(fallback_result.get("latency_ms") or 0),
            },
        }


# ── Parsing helpers ────────────────────────────────────────────────────────────

_ACTION_RE = re.compile(
    r"Action\s*:\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_FINAL_RE = re.compile(r"Final\s*Answer\s*:\s*(.*)", re.IGNORECASE | re.DOTALL)


def _extract_action(text: str):
    """Return (tool_name, args_str) or None."""
    m = _ACTION_RE.search(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None


def _extract_final_answer(text: str) -> Optional[str]:
    """Return the final answer text or None."""
    m = _FINAL_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


def _parse_args(args_str: str) -> dict:
    """
    Parse tool arguments.  Supports:
      - JSON object: {"symbol": "FPT"}
      - keyword:  symbol="FPT", quarter=1
      - positional single value: "FPT"  →  {symbol: "FPT"}
    """
    args_str = args_str.strip()
    if not args_str:
        return {}

    # Try JSON object first
    if args_str.startswith("{"):
        try:
            parsed = json.loads(args_str)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Try keyword args: key=value pairs
    kv_pattern = re.compile(r'(\w+)\s*=\s*(".*?"|\'.*?\'|\S+)')
    matches = kv_pattern.findall(args_str)
    if matches:
        result = {}
        for key, val in matches:
            val = val.strip("'\"")
            # Try int/float coercion
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    pass
            result[key] = val
        return result

    # Positional single-value (e.g. "FPT" or FPT)
    single = args_str.strip("'\"")
    return {"symbol": single}
