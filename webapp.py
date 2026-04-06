import os
import json
import socket
from typing import Any, Dict, Tuple

import gradio as gr
from dotenv import load_dotenv

from src.agent.agent import ReActAgent


load_dotenv()


CHATBOT_SYSTEM_PROMPT = """Bạn là một chatbot trả lời ngắn gọn, thân thiện.
Nếu câu hỏi ngoài phạm vi chứng khoán Việt Nam thì từ chối lịch sự.
Không bịa số liệu. Nếu thiếu dữ liệu thì nói rõ không có dữ liệu."""

CSS = """
:root{
  --bg0:#f6f7fb;
  --bg1:#ffffff;
  --panel:#ffffff;
  --panel2:#f1f3f9;
  --border:rgba(15,23,42,.14);
  --text:#0f172a;
  --muted:rgba(15,23,42,.68);
  --accent:#4f46e5;
  --accent2:#059669;
  --shadow: 0 14px 40px rgba(15,23,42,.10);
}

.gradio-container{
  background:
    radial-gradient(900px 520px at 15% 0%, rgba(79,70,229,.16), transparent 55%),
    radial-gradient(820px 520px at 90% 8%, rgba(5,150,105,.12), transparent 55%),
    linear-gradient(180deg, var(--bg0), #eef2ff 45%, #ecfeff 100%);
  color: var(--text);
}

.wrap{ max-width: 1200px !important; }

.hero{
  border: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(79,70,229,.10), rgba(5,150,105,.08));
  border-radius: 18px;
  padding: 16px 18px;
  box-shadow: var(--shadow);
}
.hero h2{ margin:0 0 6px 0; letter-spacing:-0.02em; }
.sub{ color: var(--muted); margin-top:4px; }
.badge{
  display:inline-block; padding: 5px 10px; border-radius: 999px; font-size: 12px; margin-right: 8px;
  background: rgba(255,255,255,.75); border: 1px solid var(--border); color: var(--muted);
}
.kbd{
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px; padding: 2px 8px; border-radius: 8px;
  background: rgba(15,23,42,.05); border: 1px solid rgba(15,23,42,.10); color: var(--text);
}

.panel{
  border: 1px solid var(--border);
  background: var(--panel);
  border-radius: 16px;
  padding: 12px;
  box-shadow: 0 10px 26px rgba(15,23,42,.06);
}
.panel h3{ margin: 0 0 6px 0; letter-spacing: -0.01em; }
.muted{ color: var(--muted); }

.metric-row{ display:flex; gap:10px; flex-wrap:wrap; margin-top:8px; }
.metric{
  flex: 1 1 160px;
  border: 1px solid var(--border);
  background: var(--panel2);
  border-radius: 14px;
  padding: 10px 12px;
}
.metric .k{ color: var(--muted); font-size: 12px; margin-bottom: 2px; }
.metric .v{ font-size: 18px; font-weight: 750; color: var(--text); }

/* Answer cards: increase contrast & readability */
#chatbot_answer, #react_answer{
  border: 1px solid rgba(15,23,42,.16);
  background: rgba(255,255,255,.92);
  border-radius: 16px;
  padding: 12px 14px;
  box-shadow: 0 10px 28px rgba(15,23,42,.08);
}
#chatbot_answer p, #react_answer p{ color: var(--text) !important; font-size: 15px; line-height: 1.5; }

/* Buttons */
.primary-btn button{
  background: linear-gradient(135deg, var(--accent), rgba(5,150,105,.85)) !important;
  border: 0 !important;
  color: #ffffff !important;
  font-weight: 800 !important;
  box-shadow: 0 10px 24px rgba(79,70,229,.25);
}
.primary-btn button:hover{ filter: brightness(1.03); transform: translateY(-1px); }

/* Make textbox easier to read */
textarea, input{
  background: rgba(255,255,255,.92) !important;
  color: var(--text) !important;
  border: 1px solid rgba(15,23,42,.14) !important;
}

/* Trace blocks */
.trace-grid{ display:grid; grid-template-columns: 1fr; gap: 10px; }
.trace-card{
  border: 1px solid rgba(15,23,42,.14);
  background: rgba(255,255,255,.92);
  border-radius: 16px;
  padding: 12px 14px;
  box-shadow: 0 10px 28px rgba(15,23,42,.08);
}
.trace-title{ font-weight: 800; letter-spacing: -0.01em; margin-bottom: 8px; }
.trace-tools{ display:flex; flex-direction:column; gap:8px; }
.trace-tool{
  border: 1px solid rgba(15,23,42,.10);
  background: rgba(79,70,229,.06);
  border-radius: 14px;
  padding: 10px 12px;
}
.trace-tool .n{ font-weight: 800; color: var(--text); }
.trace-tool .a{ color: rgba(15,23,42,.74); margin-top: 2px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size: 12px; }
.trace-empty{ color: var(--muted); }

.codeblock{
  background: #0b1020;
  color: rgba(255,255,255,.92);
  border: 1px solid rgba(255,255,255,.10);
  border-radius: 14px;
  padding: 12px;
  overflow:auto;
  max-height: 380px;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.06);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre;
}
"""


def _build_llm():
    provider = os.getenv("DEFAULT_PROVIDER", "openai").strip().lower()
    model = os.getenv("DEFAULT_MODEL", "gpt-4o").strip()

    if provider == "openai":
        from src.core.openai_provider import OpenAIProvider
        api_key = os.getenv("OPENAI_API_KEY")
        return OpenAIProvider(model_name=model, api_key=api_key)
    if provider in ("google", "gemini"):
        from src.core.gemini_provider import GeminiProvider
        api_key = os.getenv("GEMINI_API_KEY")
        return GeminiProvider(model_name=model, api_key=api_key)
    if provider == "local":
        from src.core.local_provider import LocalProvider
        model_path = os.getenv("LOCAL_MODEL_PATH")
        return LocalProvider(model_name=model, model_path=model_path)

    raise ValueError(f"DEFAULT_PROVIDER không hợp lệ: {provider}")


def _fmt_usage(usage: Dict[str, Any]) -> str:
    if not usage:
        return "usage: (none)"
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    tt = usage.get("total_tokens", 0)
    return f"usage: prompt={pt}, completion={ct}, total={tt}"


def compare_once(prompt: str) -> Tuple[str, str, str, str, str, str, str, str, str]:
    prompt = (prompt or "").strip()
    if not prompt:
        return "", "", "", "", "", "", "", "", ""

    llm = _build_llm()
    agent = ReActAgent(llm=llm, max_steps=8)

    # 1) Baseline chatbot (single-shot, no tools)
    chatbot_result = llm.generate(prompt=prompt, system_prompt=CHATBOT_SYSTEM_PROMPT)
    chatbot_answer = (chatbot_result.get("content") or "").strip()
    chatbot_provider = chatbot_result.get("provider", "")
    chatbot_latency = str(chatbot_result.get("latency_ms", 0))
    chatbot_usage = chatbot_result.get("usage") or {}
    chatbot_tokens = str(chatbot_usage.get("total_tokens", chatbot_usage.get("prompt_tokens", 0) + chatbot_usage.get("completion_tokens", 0)))
    chatbot_meta = f"**Provider/Model:** `{chatbot_provider} / {llm.model_name}`  \n**Latency:** `{chatbot_latency} ms`  \n**{_fmt_usage(chatbot_usage)}**"

    # 2) ReAct agent with tools + trace
    trace = agent.run_with_trace(prompt)
    react_answer = trace.get("final_answer", "").strip()
    totals = trace.get("totals") or {}
    react_steps = str(trace.get("steps", 0))
    react_latency = str(totals.get("latency_ms", 0))
    react_tokens = str(totals.get("total_tokens", 0) or (totals.get("prompt_tokens", 0) + totals.get("completion_tokens", 0)))
    tool_calls_count = str(len(trace.get("tool_calls") or []))
    react_meta = (
        f"**Provider/Model:** `{chatbot_provider} / {llm.model_name}`  \n"
        f"**Steps:** `{react_steps}`  \n"
        f"**Total latency:** `{react_latency} ms`  \n"
        f"**Tokens:** `prompt={totals.get('prompt_tokens',0)}, completion={totals.get('completion_tokens',0)}, total={totals.get('total_tokens',0)}`  \n"
        f"**Tool calls:** `{tool_calls_count}`"
    )

    # Render trace as HTML blocks (easier to style/read)
    tool_calls = trace.get("tool_calls") or []
    if tool_calls:
        tool_items = []
        for i, tc in enumerate(tool_calls, start=1):
            tool = (tc.get("tool") or "").strip()
            args = (tc.get("args") or "").strip()
            tool_items.append(
                f"<div class='trace-tool'>"
                f"<div class='n'>{i}. {tool}</div>"
                f"<div class='a'>{args}</div>"
                f"</div>"
            )
        tools_html = "<div class='trace-tools'>" + "".join(tool_items) + "</div>"
    else:
        tools_html = "<div class='trace-empty'>(Không có tool calls)</div>"

    raw_json = json.dumps(trace, ensure_ascii=False, indent=2)
    trace_html = (
        "<div class='trace-grid'>"
        "<div class='trace-card'>"
        "<div class='trace-title'>Tool use</div>"
        f"{tools_html}"
        "</div>"
        "<div class='trace-card'>"
        "<div class='trace-title'>Raw trace (JSON)</div>"
        f"<div class='codeblock'>{raw_json}</div>"
        "</div>"
        "</div>"
    )

    return (
        chatbot_answer,
        chatbot_meta,
        react_answer,
        react_meta,
        trace_html,
        chatbot_latency,
        chatbot_tokens,
        tool_calls_count,
    )


def _pick_port() -> int:
    """
    Chọn port cho Gradio:
    - Nếu có env GRADIO_SERVER_PORT thì dùng port đó.
    - Nếu không, dò từ 7860..7890 và chọn port trống đầu tiên.
    """
    env_port = os.getenv("GRADIO_SERVER_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass

    for port in range(7860, 7891):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port

    return 7860


def main():
    theme = gr.themes.Soft(
        primary_hue="violet",
        secondary_hue="emerald",
        neutral_hue="slate",
        radius_size=gr.themes.sizes.radius_lg,
        font=[gr.themes.GoogleFont("Manrope"), "ui-sans-serif", "system-ui"],
        font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "SFMono-Regular"],
    )

    with gr.Blocks(title="Chatbot vs ReAct Agent (Self-host)", theme=theme, css=CSS) as demo:
        provider = os.getenv("DEFAULT_PROVIDER", "openai").strip()
        model = os.getenv("DEFAULT_MODEL", "gpt-4o").strip()

        gr.HTML(
            f"""
            <div class="hero">
              <div style="display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; align-items:flex-end;">
                <div>
                  <h2>Chatbot vs ReAct Agent</h2>
                  <div class="sub">Self-host để <b>prompt</b> và <b>so sánh</b> output + metrics (latency/tokens/steps/tool calls).</div>
                </div>
                <div>
                  <span class="badge">DEFAULT_PROVIDER: <span class="kbd">{provider}</span></span>
                  <span class="badge">DEFAULT_MODEL: <span class="kbd">{model}</span></span>
                </div>
              </div>
            </div>
            """
        )

        with gr.Row():
            with gr.Column(scale=8):
                prompt = gr.Textbox(
                    label="Prompt",
                    lines=3,
                    placeholder="Ví dụ: Mua 100 cổ phiếu VNM hiện tại mất bao tiền?",
                )
            with gr.Column(scale=4):
                run_btn = gr.Button("So sánh", elem_classes=["primary-btn"])
                samples = gr.Examples(
                    label="Gợi ý prompt",
                    examples=[
                        ["Mua 100 cổ phiếu VNM hiện tại mất bao tiền?"],
                        ["Cho tôi biết giá cổ phiếu FPT đang bao nhiêu tiền?"],
                        ["CEO hiện tại của VietJet Air là ai?"],
                        ["Giá vàng hôm nay như thế nào?"],
                    ],
                    inputs=[prompt],
                )

        with gr.Row():
            with gr.Column():
                gr.HTML("<div class='panel'><h3>Baseline Chatbot</h3><div class='muted'>1 lượt gọi LLM, không tool.</div></div>")
            with gr.Column():
                gr.HTML("<div class='panel'><h3>ReAct Agent</h3><div class='muted'>Thought→Action→Observation, có tool và trace.</div></div>")

        with gr.Row(equal_height=True):
            with gr.Column(scale=6):
                out_chatbot = gr.Markdown(elem_id="chatbot_answer")
                out_chatbot_meta = gr.Markdown()
            with gr.Column(scale=6):
                out_react = gr.Markdown(elem_id="react_answer")
                out_react_meta = gr.Markdown()

        with gr.Row():
            chatbot_latency_card = gr.HTML()
            chatbot_tokens_card = gr.HTML()
            react_toolcalls_card = gr.HTML()

        with gr.Accordion("Trace (tool calls + JSON)", open=False):
            trace = gr.HTML()

        def _decorate(
            chatbot_answer: str,
            chatbot_meta: str,
            react_answer: str,
            react_meta: str,
            trace_html: str,
            chatbot_latency: str,
            chatbot_tokens: str,
            tool_calls_count: str,
        ):
            latency_html = f"<div class='metric'><div class='k'>Chatbot latency</div><div class='v'>{chatbot_latency} ms</div></div>"
            tokens_html = f"<div class='metric'><div class='k'>Chatbot total tokens</div><div class='v'>{chatbot_tokens}</div></div>"
            tools_html = f"<div class='metric'><div class='k'>ReAct tool calls</div><div class='v'>{tool_calls_count}</div></div>"

            latency_wrap = f"<div class='metric-row'>{latency_html}</div>"
            tokens_wrap = f"<div class='metric-row'>{tokens_html}</div>"
            tools_wrap = f"<div class='metric-row'>{tools_html}</div>"

            return (
                chatbot_answer or "_(chưa có kết quả)_",
                chatbot_meta or "",
                react_answer or "_(chưa có kết quả)_",
                react_meta or "",
                trace_html or "",
                latency_wrap,
                tokens_wrap,
                tools_wrap,
            )

        run_btn.click(
            fn=compare_once,
            inputs=[prompt],
            outputs=[
                out_chatbot,
                out_chatbot_meta,
                out_react,
                out_react_meta,
                trace,
                chatbot_latency_card,
                chatbot_tokens_card,
                react_toolcalls_card,
            ],
        ).then(
            fn=_decorate,
            inputs=[
                out_chatbot,
                out_chatbot_meta,
                out_react,
                out_react_meta,
                trace,
                chatbot_latency_card,
                chatbot_tokens_card,
                react_toolcalls_card,
            ],
            outputs=[
                out_chatbot,
                out_chatbot_meta,
                out_react,
                out_react_meta,
                trace,
                chatbot_latency_card,
                chatbot_tokens_card,
                react_toolcalls_card,
            ],
        )

    demo.launch(server_name="127.0.0.1", server_port=_pick_port())


if __name__ == "__main__":
    main()
