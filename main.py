"""
Vietnam Stock Market ReAct Agent — entrypoint
Usage:
    python main.py                  # interactive mode
    python main.py "Giá FPT?"       # single query
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from src.core.openai_provider import OpenAIProvider
from src.agent.agent import ReActAgent

# ── Demo queries covering all use cases ───────────────────────────────────────
DEMO_QUERIES = [
    # Out-of-domain
    "Giá vàng hôm nay như thế nào?",
    "Thời tiết hôm nay ở Hà Nội như thế nào?",
    # In-domain
    "Cho tôi biết giá cổ phiếu FPT đang bao nhiêu tiền?",
    "Phân tích chỉ số tài chính của cổ phiếu FLC",
    "Gửi báo cáo lưu chuyển tiền tệ quý 1 của tập đoàn Vingroup",
    "CEO hiện tại của VietJet Air là ai?",
    "Tôi mua 1.000 cổ phiếu Vinamilk với giá 52.200 VND, giờ nó đang là bao nhiêu?",
]


def build_agent() -> ReActAgent:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("DEFAULT_MODEL", "gpt-4o")
    llm = OpenAIProvider(model_name=model, api_key=api_key)
    return ReActAgent(llm=llm, max_steps=8)


def run_query(agent: ReActAgent, query: str):
    print("\n" + "=" * 70)
    print(f"USER: {query}")
    print("=" * 70)
    answer = agent.run(query)
    print(f"\nAGENT: {answer}\n")


def main():
    agent = build_agent()

    # Single query from CLI argument
    if len(sys.argv) > 1:
        run_query(agent, " ".join(sys.argv[1:]))
        return

    # Interactive mode
    if sys.stdin.isatty():
        print("Vietnam Stock ReAct Agent (nhập 'exit' để thoát, 'demo' để chạy tất cả use case)")
        while True:
            try:
                query = input("\nBạn: ").strip()
            except (KeyboardInterrupt, EOFError):
                break
            if not query:
                continue
            if query.lower() == "exit":
                break
            if query.lower() == "demo":
                for q in DEMO_QUERIES:
                    run_query(agent, q)
            else:
                run_query(agent, query)
    else:
        # Piped input — run demo
        for q in DEMO_QUERIES:
            run_query(agent, q)


if __name__ == "__main__":
    main()
