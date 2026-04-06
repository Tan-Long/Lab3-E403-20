# Báo Cáo Cá Nhân: Lab 3 - Chatbot vs ReAct Agent

- **Họ và Tên**: Nguyễn Hữu Quang
- **Mã Số Sinh Viên**: 2A202600167
- **Ngày thực hiện**: 06/04/2026

---

## I. Đóng Góp Kỹ Thuật (15 Điểm)

Trong bài lab này, tôi tập trung vào việc xây dựng một **Financial Analysis ReAct Agent** chuyên biệt cho thị trường chứng khoán Việt Nam. Các đóng góp chính của tôi bao gồm việc chọn đề tài, tích hợp nguồn dữ liệu thực tế và thực hiện kiểm thử hiệu năng (stress test) cho khả năng suy luận của mô hình.

- **Các Module đã triển khai**:
  - `src/tools/vnstock_tools.py`: Phát triển bộ công cụ tài chính sử dụng thư viện `vnstock3`, bao gồm: `get_stock_price`, `get_financial_ratios`, `get_cash_flow`, `get_income_statement`, và `get_company_profile`.
  - `src/agent/agent.py`: Tối ưu hóa logic thực thi công cụ để xử lý các kiểu dữ liệu trả về phức tạp và ghi log telemetry chính xác.
- **Điểm nhấn mã nguồn**:
  - Triển khai cơ chế xử lý lỗi chặt chẽ trong `vnstock_tools.py` bằng `traceback`, giúp Agent có đủ ngữ cảnh để "tự sửa lỗi" hoặc giải thích lỗi cho người dùng một cách chuyên nghiệp.
  - Xử lý dữ liệu tùy chỉnh trong `get_financial_ratios` để trích xuất dữ liệu quý gần nhất từ các DataFrame đa chỉ mục (multi-indexed) trả về bởi API VNStock.
- **Tài liệu hướng dẫn**: 
  - Agent sử dụng vòng lặp ReAct: Khối **Thought** phân tích yêu cầu tài chính (VD: "Tính lợi nhuận cho 1000 cổ phiếu VNM").
  - **Action** gọi các công cụ VNStock.
  - **Observation** cung cấp dữ liệu thô (giá đóng cửa, EPS, v.v.).
  - Agent thực hiện tính toán cuối cùng dựa trên các quan sát này để đưa ra câu trả lời.

---

## II. Case Study về Debugging (10 Điểm)

Trong quá trình phát triển và thực hiện stress test, tôi đã gặp một lỗi nghiêm trọng liên quan đến việc tuần tự hóa dữ liệu (serialization).

- **Mô tả vấn đề**: Agent bị crash với lỗi `TypeError` khi cố gắng ghi log kết quả trả về từ công cụ.
- **Nguồn log**: `logs/2026-04-06.log`
  ```json
  Tool execution error: keys must be str, int, float, bool or None, not tuple
  Traceback (most recent call last):
    File "src/agent/agent.py", line 125, in _execute_tool
      logger.log_event("TOOL_RESULT", {"tool": tool_name, "result": result})
    File "src/telemetry/logger.py", line 36, in log_event
      self.logger.info(json.dumps(payload))
  TypeError: keys must be str, int, float, bool or None, not tuple
  ```
- **Chẩn đoán**: Thư viện `vnstock` đôi khi trả về các dictionary từ Pandas DataFrame chứa các "tuple" làm key (do cơ chế multi-indexing). Khi hệ thống telemetry của Agent cố gắng `json.dumps()` các kết quả này để ghi log, trình mã hóa JSON chuẩn bị lỗi vì nó không hỗ trợ key dạng tuple.
- **Giải pháp**: Tôi đã cập nhật triển khai các công cụ trong `src/tools/vnstock_tools.py` để xử lý các key của dictionary, đảm bảo tất cả các key được chuyển thành chuỗi (string) trước khi trả về kết quả cho Agent. Tôi cũng thêm hàm `dropna()` để ngăn chặn các giá trị `NaN` làm hỏng quá trình serialization.

---

## III. Phân Tích Cá Nhân: Chatbot vs ReAct (10 Điểm)

1.  **Khả năng suy luận (Reasoning)**: Khối `Thought` là một cuộc cách mạng cho các tác vụ tài chính. Một chatbot thông thường có thể "đoán" giá hoặc đưa ra thông tin cũ. Ngược lại, ReAct Agent "nhận ra" nó cần dữ liệu cụ thể (VD: "Tôi cần giá hiện tại của VJC và hồ sơ công ty để xác định CEO") và thực hiện các bước một cách tuần tự.
2.  **Độ tin cậy (Reliability)**: Agent hoạt động kém hơn khi gặp **API không nhất quán**. Ví dụ, khi `s.company.profile()` ném ra lỗi `AttributeError` do phiên bản `vnstock` thay đổi API nội bộ, Agent tiếp tục thử lại hành động đó (vòng lặp vô hạn) cho đến khi đạt giới hạn bước, trong khi chatbot đơn giản có thể đã báo không biết.
3.  **Quan sát (Observation)**: Phản hồi từ môi trường là cực kỳ quan trọng. Trong một trường hợp, LLM đã truyền một chuỗi định dạng JSON làm đối số: `get_cash_flow({"symbol": "VIC", ...})`. Công cụ trả về lỗi `ValueError`. Agent đã quan sát lỗi này, hiểu rằng "định dạng mã chứng khoán không được nhận dạng" và tự sửa lỗi ở bước tiếp theo bằng cách truyền chuỗi đơn giản `"VIC"`.

---

## IV. Cải Tiến Trong Tương Lai (5 Điểm)

Để mở rộng hệ thống này thành một cố vấn tài chính cấp độ chuyên nghiệp, tôi sẽ triển khai:

- **Khả năng mở rộng (Scalability)**: Thêm một **Lớp Caching** (như Redis) cho giá cổ phiếu. Dữ liệu tài chính không nhất thiết phải thay đổi từng giây cho các phân tích hàng ngày, việc cache sẽ giúp giảm đáng kể chi phí API và độ trễ.
- **Khả năng chịu tải (Stress Test Resilience)**: Triển khai cơ chế **Rate Limiting** (giới hạn tốc độ) và mô hình "Circuit Breaker". Trong quá trình stress test, các truy vấn dồn dập đôi khi dẫn đến việc bị nhà cung cấp dữ liệu chặn IP tạm thời.
- **Hiệu năng (Performance)**: Nâng cao logic **Trích xuất dữ liệu (Data Extraction)**. Thay vì truyền toàn bộ dữ liệu tài chính về cho LLM (gây tốn token), tôi sẽ xây dựng một công cụ "Data Analyst" thực hiện tính toán cục bộ và chỉ trả về kết quả cuối cùng hoặc bản tóm tắt ngắn gọn.

---
