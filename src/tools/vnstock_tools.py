"""
Vietnam Stock Market tools powered by vnstock3.
All prices are returned in VND.
"""
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict


def _warn_fallback(tool: str, primary: str, fallback: str, exc: Exception):
    """Log a warning when falling back to secondary source."""
    try:
        from src.telemetry.logger import logger
        logger.log_event("SOURCE_FALLBACK", {
            "tool": tool,
            "primary": primary,
            "fallback": fallback,
            "reason": f"{type(exc).__name__}: {str(exc)[:120]}",
        })
    except Exception:
        pass


def _stock(symbol: str):
    from vnstock import Vnstock
    return Vnstock().stock(symbol=symbol.upper().strip(), source="VCI")


def _finance_kbs(symbol: str):
    from vnstock import Finance
    return Finance(symbol=symbol.upper().strip(), source="KBS")


def _to_native(val):
    """Convert numpy scalar to Python native for JSON serialization."""
    if val is None or str(val) in ("nan", "None"):
        return None
    return float(val) if hasattr(val, "item") else val


def _clean_row(row: dict, skip_keys=()) -> dict:
    return {
        k: _to_native(v)
        for k, v in row.items()
        if k not in skip_keys and _to_native(v) is not None
    }


# ── VCI wide-format helpers ────────────────────────────────────────────────────

def _vci_filter_quarter(df, year: int, quarter: int):
    """Filter VCI wide-format df for a specific year/quarter."""
    df = df.reset_index(drop=True)
    col_year = next((c for c in df.columns if str(c).lower() in ("năm", "year")), None)
    col_q = next((c for c in df.columns if str(c).lower() in ("kỳ", "quarter")), None)
    if col_year and col_q:
        mask = (df[col_year] == year) & (df[col_q] == quarter)
        filtered = df[mask]
        if filtered.empty:
            filtered = df[df[col_q] == quarter].head(1)
        return filtered
    return df.head(1)


def _vci_period_label(row: dict) -> str:
    yr = row.get("Năm", row.get("year", ""))
    ky = row.get("Kỳ", row.get("quarter", ""))
    return f"{yr}-Q{ky}" if ky else str(yr)


# ── KBS long-format helper ────────────────────────────────────────────────────

def _kbs_pivot(df, n_periods: int = 2) -> dict:
    """Convert KBS long-format df into {periods, data} dict."""
    quarter_cols = [c for c in df.columns if c not in ("item", "item_id")]
    selected = quarter_cols[:n_periods]
    data = {}
    for _, row in df.iterrows():
        key = row["item_id"]
        data[key] = {
            col: _to_native(row[col])
            for col in selected
            if _to_native(row[col]) is not None
        }
    return {"periods": selected, "data": data}


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ══════════════════════════════════════════════════════════════════════════════

def get_stock_price(symbol: str) -> Dict[str, Any]:
    """
    Lấy giá cổ phiếu hiện tại (phiên giao dịch gần nhất).
    Tham số: symbol — mã cổ phiếu (VD: FPT, VNM, VIC)
    """
    sym = symbol.upper().strip()

    # ── Primary: VCI ──────────────────────────────────────────────────────────
    try:
        s = _stock(sym)
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        df = s.quote.history(start=start, end=end, interval="1D")
        if df is not None and not df.empty:
            row = df.iloc[-1]
            def to_vnd(val):
                return round(float(val) * 1000)
            return {
                "symbol": sym,
                "source": "VCI",
                "date": str(row.get("time", row.name)),
                "close_vnd": to_vnd(row["close"]),
                "open_vnd": to_vnd(row["open"]),
                "high_vnd": to_vnd(row["high"]),
                "low_vnd": to_vnd(row["low"]),
                "volume": int(row["volume"]),
            }
    except Exception as e:
        _warn_fallback("get_stock_price", "VCI", "KBS", e)

    # ── Fallback: KBS history ─────────────────────────────────────────────────
    try:
        f = _finance_kbs(sym)
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        df = f.history(start=start, end=end, interval="1D")
        if df is not None and not df.empty:
            row = df.iloc[-1]
            return {
                "symbol": sym,
                "source": "KBS",
                "date": str(row.get("time", row.name)),
                "close_vnd": round(float(row["close"]) * 1000),
                "open_vnd": round(float(row["open"]) * 1000),
                "high_vnd": round(float(row["high"]) * 1000),
                "low_vnd": round(float(row["low"]) * 1000),
                "volume": int(row["volume"]),
            }
    except Exception:
        pass

    return {"error": f"Không thể lấy giá cổ phiếu cho mã {sym}."}


def get_financial_ratios(symbol: str) -> Dict[str, Any]:
    """
    Lấy các chỉ số tài chính của cổ phiếu (P/E, P/B, ROE, ROA, EPS...).
    Tham số: symbol — mã cổ phiếu
    """
    sym = symbol.upper().strip()

    # ── Primary: KBS (long format, clean item_id keys) ────────────────────────
    try:
        df = _finance_kbs(sym).ratio(period="quarter")
        if df is not None and not df.empty:
            quarter_cols = [c for c in df.columns if c not in ("item", "item_id")]
            if quarter_cols:
                latest_col = quarter_cols[0]
                result = {"symbol": sym, "source": "KBS", "period": latest_col}
                for _, row in df.iterrows():
                    val = _to_native(row[latest_col])
                    if val is not None:
                        result[row["item_id"]] = val
                return result
    except Exception as e:
        _warn_fallback("get_financial_ratios", "KBS", "VCI", e)

    # ── Fallback: VCI (wide format, flatten MultiIndex) ───────────────────────
    try:
        s = _stock(sym)
        df = s.finance.ratio(period="year", lang="vi")
        if df is not None and not df.empty:
            # Flatten MultiIndex columns
            df.columns = [
                " ".join(filter(None, col)).strip() if isinstance(col, tuple) else col
                for col in df.columns
            ]
            row = df.iloc[0].dropna().to_dict()
            yr = row.get("Meta Năm", row.get("Meta Year", ""))
            ky = row.get("Meta Kỳ", row.get("Meta Quarter", ""))
            period_label = f"{yr}-Q{ky}" if ky else str(yr)
            result = {"symbol": sym, "source": "VCI", "period": period_label}
            skip = {c for c in df.columns if c.startswith("Meta")}
            for k, v in row.items():
                if k not in skip:
                    val = _to_native(v)
                    if val is not None:
                        result[k] = val
            return result
    except Exception:
        pass

    return {"error": f"Không thể lấy chỉ số tài chính cho mã {sym}."}


def get_cash_flow(symbol: str, quarter: int = 1, year: int = None) -> Dict[str, Any]:
    """
    Lấy báo cáo lưu chuyển tiền tệ theo quý.
    Tham số:
      symbol  — mã cổ phiếu
      quarter — quý cần lấy (1–4), mặc định quý 1
      year    — năm cần lấy, mặc định năm hiện tại
    """
    sym = symbol.upper().strip()
    if year is None:
        year = datetime.now().year

    # ── Primary: VCI ──────────────────────────────────────────────────────────
    try:
        s = _stock(sym)
        df = s.finance.cash_flow(period="quarter", lang="vi")
        if df is not None and not df.empty:
            filtered = _vci_filter_quarter(df, year, quarter)
            if not filtered.empty:
                row = filtered.iloc[0].dropna().to_dict()
                return {
                    "symbol": sym,
                    "source": "VCI",
                    **_clean_row(row, skip_keys=("CP",)),
                }
    except Exception as e:
        _warn_fallback("get_cash_flow", "VCI", "KBS", e)

    # ── Fallback: KBS ─────────────────────────────────────────────────────────
    try:
        df = _finance_kbs(sym).cash_flow(period="quarter")
        if df is not None and not df.empty:
            pivot = _kbs_pivot(df, n_periods=1)
            period_key = pivot["periods"][0] if pivot["periods"] else "latest"
            flat = {k: v.get(period_key) for k, v in pivot["data"].items() if v.get(period_key) is not None}
            return {"symbol": sym, "source": "KBS", "period": period_key, **flat}
    except Exception:
        pass

    return {"error": f"Không thể lấy BCLCTT cho mã {sym} Q{quarter}/{year}."}


def get_income_statement(symbol: str, period: str = "quarter") -> Dict[str, Any]:
    """
    Lấy báo cáo kết quả kinh doanh (doanh thu, lợi nhuận gộp, lợi nhuận ròng...).
    Tham số:
      symbol — mã cổ phiếu
      period — 'quarter' (mặc định) hoặc 'year'
    """
    sym = symbol.upper().strip()

    # ── Primary: KBS ──────────────────────────────────────────────────────────
    try:
        df = _finance_kbs(sym).income_statement(period=period)
        if df is not None and not df.empty:
            pivot = _kbs_pivot(df, n_periods=2)
            if pivot["periods"]:
                return {"symbol": sym, "source": "KBS", **pivot}
    except Exception as e:
        _warn_fallback("get_income_statement", "KBS", "VCI", e)

    # ── Fallback: VCI ─────────────────────────────────────────────────────────
    try:
        s = _stock(sym)
        df = s.finance.income_statement(period=period, lang="vi")
        if df is None or df.empty:
            return {"error": f"Không tìm thấy KQKD cho mã {sym}."}
        df = df.reset_index(drop=True)
        rows = df.head(2).to_dict(orient="records")
        periods = [_vci_period_label(r) for r in rows]
        data = [_clean_row(r, skip_keys=("CP", "Năm", "Kỳ")) for r in rows]
        return {"symbol": sym, "source": "VCI", "periods": periods, "data": data}
    except Exception:
        pass

    return {"error": f"Không thể lấy KQKD cho mã {sym}."}


def get_company_profile(symbol: str) -> Dict[str, Any]:
    """
    Lấy thông tin công ty: mô tả, ngành, ban lãnh đạo (CEO, HĐQT...).
    Tham số: symbol — mã cổ phiếu
    """
    sym = symbol.upper().strip()

    # ── Primary: VCI ──────────────────────────────────────────────────────────
    try:
        s = _stock(sym)
        overview_df = s.company.overview()
        officers_df = s.company.officers()

        profile = {}
        if overview_df is not None and not overview_df.empty:
            profile = overview_df.iloc[0].dropna().to_dict()

        officers = []
        if officers_df is not None and not officers_df.empty:
            officers = officers_df.to_dict(orient="records")

        if profile or officers:
            return {
                "symbol": sym,
                "source": "VCI",
                "profile": {k: (str(v) if hasattr(v, "item") else v) for k, v in profile.items()},
                "officers": [
                    {k: (str(v) if hasattr(v, "item") else v) for k, v in o.items()}
                    for o in officers
                ],
            }
    except Exception:
        pass

    return {"error": f"Không thể lấy thông tin công ty cho mã {sym}."}
