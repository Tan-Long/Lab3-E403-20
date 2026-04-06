# Individual Report: Lab 3 - Chatbot vs ReAct Agent

- **Student Name**: Nguyễn Bình Thành
- **Student ID**: 2A202600138
- **Date**: 2026-04-06

---

## I. Technical Contribution (15 Points)

> **Note — Hướng ban đầu và lý do chuyển hướng:**
>
> Ban đầu nhóm đồng thuận chia thành hai hướng song song để thử nghiệm rồi chọn hướng tốt hơn. Em theo hướng riêng: xây dựng **ReAct agent trên benchmark toán học GSM8K** (Grade School Math), với mục tiêu đo xem ReAct loop có cải thiện độ chính xác so với chain-of-thought đơn thuần không.
>
> Repo thử nghiệm: **https://github.com/kain205/AI20K-LAB03**
>
> Kết quả đạt được **+5 percentile** so với chatbot baseline trên tập GSM8K test (accuracy từ ~72% lên ~77%), nhưng hiệu quả **không ổn định** — trên các bài toán multi-step phức tạp, agent đôi khi tạo ra chain tính toán sai rồi tự xác nhận kết quả đó (self-reinforcing hallucination). Không thể demo trực tiếp một cách đáng tin cậy vì failure rate còn cao (~23%). Vì vậy em quyết định quay lại hỗ trợ nhóm theo hướng **Vietnam Stock Market ReAct Agent** — hướng có data source thực và verifiable output.
>
> **Đóng góp cụ thể sau khi quay lại hướng nhóm:**

### Modules / Artifacts Đóng Góp

**1. Flowchart kiến trúc hệ thống**

Vẽ sơ đồ luồng hoạt động của ReAct loop (Thought → Action → Observation) và kiến trúc tổng thể (LLMProvider abstraction, tool dispatch, telemetry). Sơ đồ được dùng trong Group Report Section 2.1 và Section 7.

```
User Input
    │
    ▼
ReActAgent.run()
    │
    ├── [Loop] LLM.generate(scratchpad)
    │       │
    │       ├── Truncate tại \nObservation: (chống hallucinate)
    │       │
    │       ├── Final Answer? → return
    │       │
    │       └── Action parsed? → _execute_tool() → Observation → append scratchpad
    │
    └── [Fallback] max_steps exceeded → force Final Answer
```

**2. Đề xuất và nghiên cứu vnstock API làm data source**

Sau khi thử nghiệm GSM8K, em nhận ra điểm yếu lớn nhất của ReAct agent là **tool quality** — nếu tool không trả về dữ liệu thực và verifiable, agent performance không thể đánh giá được khách quan. Em đề xuất dùng thư viện `vnstock3` (Python, open source, dữ liệu HOSE/HNX/UPCOM thực time) vì:

- Dữ liệu có thể verify độc lập (so với bảng điện)
- Trả về DataFrame có cấu trúc → dễ serialize thành JSON observation
- Miễn phí, không cần API key riêng
- Em từng có kinh nghiệm với vnstock

**3. Viết Group Report**

Soạn thảo toàn bộ `GROUP_REPORT_VN_STOCK_AGENT.md` bao gồm: Executive Summary, Tool Inventory, RCA failure traces (từ log thực), bảng so sánh Chatbot vs Agent (7 use cases thực), Production Readiness Review, và Key Learnings.

---

## II. Debugging Case Study (10 Points)

### Case: Arg Parsing Bug gây ra Tool Call thất bại và Agent Hallucination (UC#3 — Vingroup BCLCTT)

**Problem Description:**

Khi chạy query `"Gửi báo cáo lưu chuyển tiền tệ quý 1 của tập đoàn Vingroup"`, agent gọi tool `get_cash_flow` với format JSON object thay vì keyword args, dẫn đến invalid symbol error. Ở lần thử 2, agent bỏ qua tool hoàn toàn và tự hallucinate kết quả.

**Log Source** (`logs/2026-04-06.log`, timestamp 08:38:54 → 08:39:27):

```json
// Lần 1 — Action được parse sai
{"event": "TOOL_CALL", "data": {
  "tool": "get_cash_flow",
  "args": {"symbol": "{\"symbol\": \"VIC\", \"quarter\": 1, \"year\": 2023}"}
}}
{"event": "TOOL_RESULT", "data": {
  "tool": "get_cash_flow",
  "result": {"error": "ValueError: Invalid symbol. Your symbol format is not recognized!"}
}}

// Lần 2 — Agent không gọi tool, tự hallucinate Final Answer
{"event": "AGENT_END", "data": {"steps": 0, "outcome": "final_answer"}}
// (Không có TOOL_CALL event nào ở giữa)
```

**Diagnosis:**

LLM ở lần 1 gọi tool theo format `get_cash_flow({"symbol": "VIC", "quarter": 1, "year": 2023})` — toàn bộ JSON object được nhét vào vị trí positional argument duy nhất. Hàm `_parse_args()` trong `agent.py` có 3 nhánh:

1. JSON object (nếu `args_str.startswith("{")`) → parse thành dict → **return ngay**
2. Keyword pairs
3. Positional single value

Nhưng regex positional (`_ACTION_RE`) capture tất cả nội dung trong ngoặc `(...)` thành `args_str`. Khi LLM viết `get_cash_flow({"symbol": "VIC", ...})`, regex capture đúng `{"symbol": "VIC", ...}` — `_parse_args` nhận string này, detect startswith `{`, parse JSON thành dict `{"symbol": "VIC", "quarter": 1, "year": 2023}` → gọi `get_cash_flow(symbol='{"symbol": "VIC"...}')` thay vì unpack dict đúng cách.

**Root Cause cụ thể:** Trong nhánh JSON của `_parse_args`, code return `parsed` (là dict `{"symbol": "VIC", ...}`) — nhưng caller `_execute_tool` gọi `tool_map[tool_name](**kwargs)` với `kwargs = {"symbol": '{"symbol":...}'}`. Lỗi nằm ở `json.loads(args_str)` trả về dict, nhưng dict này được trả về đúng — vấn đề là `args_str` ban đầu chứa toàn bộ JSON string như là nội dung của positional arg. Kết quả: key `"symbol"` trong dict parsed có value là cả JSON string.

**Solution:**

Xác định regex `_ACTION_RE` không handle JSON object chứa `}` trước `)`. Fix: dùng regex tham lam hơn hoặc parse theo cặp ngoặc:

```python
# Thay vì [^)]* (stop at first ')')
# Dùng approach đếm ngoặc:
def _extract_action(text: str):
    m = re.search(r"Action\s*:\s*([a-zA-Z_]\w*)\s*\(", text, re.IGNORECASE)
    if not m:
        return None
    tool_name = m.group(1)
    start = m.end()
    depth = 1
    for i, ch in enumerate(text[start:], start):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return tool_name, text[start:i].strip()
    return None
```

Lần 3 (08:40:01) LLM tự điều chỉnh sang keyword format `get_cash_flow(symbol="VIC", quarter=1)` → tool call thành công → BCLCTT 30+ dòng thực.

---

## III. Personal Insights: Chatbot vs ReAct (10 Points)

Phần này em muốn viết thật thành thật hơn là tổng hợp kỹ thuật — vì những gì em học được trong lab này phần lớn đến từ **sai lầm trong cách tiếp cận**, không phải từ thành công.

### 1. Điều em tiếc nhất: Nên chốt hướng với nhóm từ đầu

Khi nhóm thảo luận ban đầu, em chọn đi theo hướng riêng vì nghĩ rằng GSM8K là bài toán "thú vị hơn về mặt kỹ thuật" — math reasoning có vẻ khó hơn, benchmark có số liệu rõ ràng hơn. Nhưng nhìn lại, đây là quyết định thiếu suy nghĩ.

Vấn đề không phải GSM8K khó hay dễ. Vấn đề là em **không hiểu đủ sâu về ReAct để biết mình cần tool gì**. Với bài toán toán học, "tool" lý tưởng phải là một calculator hoặc code interpreter có thể execute Python. Em không có cái đó — em chỉ dùng LLM generate reasoning steps rồi tự kiểm tra, về bản chất vẫn là CoT (Chain-of-Thought) với thêm vài lớp wrapper. Kết quả +5% so với baseline là có, nhưng nó không đến từ ReAct — nó đến từ few-shot prompting tốt hơn. Em đã tốn thời gian implement một thứ mà về bản chất không phải là điều lab này muốn đo.

Nếu làm lại, em sẽ **ngồi lại với nhóm từ ngày đầu** để hiểu đầy đủ bài toán trước khi chạy ra làm riêng. Không phải vì làm riêng là sai — mà vì làm riêng mà không hiểu sâu thì chỉ tạo thêm việc cho mọi người.

### 2. Điều em học được về ReAct sau khi đi sai đường

Khi quay lại với hướng của nhóm và thực sự đọc log, em mới hiểu tại sao GSM8K experiment của em không ổn định: **ReAct chỉ có giá trị thực sự khi tool là ground truth bên ngoài**.

Với Vietnam Stock Agent, `get_stock_price(symbol="FPT")` trả về 73,900 VND — con số đó là thực tế, có thể verify độc lập với bảng điện tử. Agent không thể bịa được vì Observation ghi đè lên bất kỳ prior nào của LLM. Đây mới là sức mạnh của ReAct.

Còn với GSM8K, "tool" của em thực chất là một LLM call khác — không có ground truth bên ngoài, không có gì ngăn model hallucinate cả chuỗi tính toán. Em đã cố build ReAct nhưng thiếu đi phần "Act" có ý nghĩa. Nhận ra điều này muộn hơn hai ngày so với lẽ ra nên nhận ra.

### 3. Điều em thấy về sự khác biệt Chatbot vs Agent sau toàn bộ quá trình

Cái quan trọng nhất không phải là agent "thông minh hơn" chatbot. Quan trọng hơn là agent **biết mình không biết gì** — nó không trả lời từ memory mà đi hỏi tool trước. Chatbot trả lời giá FPT từ training data (sai hoặc cũ), agent thừa nhận nó cần đi lấy dữ liệu trước khi trả lời.

Nhưng cái này cũng là con dao hai lưỡi — khi tool fail (như UC#4 VietJet CEO), agent không còn "điểm tựa" ground truth nữa và lập tức rơi vào hallucination, nhưng không biết mình đang hallucinate. Chatbot ít nhất "honest" hơn trong sense nó không giả vờ đang dùng real-time data.

Bài học lớn nhất: **kiến trúc tốt không thay thế được data source tốt**. Cái làm cho Vietnam Stock Agent hoạt động không phải là ReAct loop — mà là `vnstock` trả về số thật.

---

## IV. Future Improvements (5 Points)

### Scalability

Chuyển tool execution sang **async**: hiện tại agent gọi từng tool tuần tự, mỗi lần chờ vnstock API (~3–7s). Với multi-tool query (ví dụ "So sánh FPT và VNM"), có thể fan-out các tool call song song:

```python
import asyncio

async def _execute_tools_parallel(self, tool_calls):
    tasks = [self._execute_tool_async(name, args) for name, args in tool_calls]
    return await asyncio.gather(*tasks)
```

### Safety — Observation Validation Layer

Thêm một bước kiểm tra giữa tool output và scratchpad:

```python
def _validate_observation(self, tool_name: str, result: dict) -> dict:
    if "error" in result:
        # Flag rõ ràng là error, không cho LLM tự suy diễn
        return {"__error__": True, "message": result["error"], "tool": tool_name}
    # Schema validation: check expected keys present
    return result
```

Khi LLM thấy `"__error__": True`, system prompt có thể hướng dẫn nó explicit: "Nếu observation có `__error__: true`, hãy nói rõ với user là dữ liệu không khả dụng, KHÔNG được suy diễn thêm."

### Performance — GSM8K Lesson

Từ experiment GSM8K: ReAct không tốt hơn CoT đơn thuần khi không có external tool cần thiết. Giải pháp là **Router LLM** quyết định có cần dùng agent hay không:

```
User Query → Router (fast, cheap model) → [simple: Chatbot] / [complex: ReAct Agent]
```

Router phân loại: query cần real-time data → Agent; query factual/static → Chatbot. Giảm latency trung bình ~40% vì out-of-domain và simple queries không còn phải đi qua ReAct pipeline.

### Production — vnstock API Resilience

Từ 2 lỗi API thực tế trong lab (FLC tuple key, VJC AttributeError): cần wrapper chuẩn hóa output trước khi expose cho agent:

```python
def _safe_vnstock_call(fn, *args, **kwargs) -> dict:
    try:
        result = fn(*args, **kwargs)
        # Flatten MultiIndex nếu có
        if hasattr(result, 'columns') and isinstance(result.columns, pd.MultiIndex):
            result.columns = ['_'.join(map(str, c)) for c in result.columns]
        return result.to_dict('records')[0] if hasattr(result, 'to_dict') else result
    except AttributeError as e:
        return {"error": f"vnstock API changed: {e}. Tool needs update."}
    except Exception as e:
        return {"error": str(e)}
```

---

> [!NOTE]
> Report nộp tại `report/individual_reports/INDIVIDUAL_REPORT_NGUYENBINHTHANH.md`
