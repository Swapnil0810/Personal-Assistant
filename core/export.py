from __future__ import annotations

from io import BytesIO

import pandas as pd

from core.db import CATEGORIES


def to_excel(df: pd.DataFrame) -> bytes:
    out = df[["date", "bank", "category", "amount", "details"]].copy()
    out.columns = ["Date", "Bank", "Category", "Amount", "Details"]
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter", datetime_format="dd-mmm-yyyy") as xw:
        out.to_excel(xw, sheet_name="Entries", index=False)
        wb, ws = xw.book, xw.sheets["Entries"]
        hdr = wb.add_format({"bold": True, "bg_color": "#1F2937", "font_color": "#FFFFFF", "border": 1})
        money = wb.add_format({"num_format": "#,##0.00"})
        bold_money = wb.add_format({"num_format": "#,##0.00", "bold": True})
        bold = wb.add_format({"bold": True})
        for i, col in enumerate(out.columns):
            ws.write(0, i, col, hdr)
        ws.set_column(0, 0, 14)
        ws.set_column(1, 2, 18)
        ws.set_column(3, 3, 14, money)
        ws.set_column(4, 4, 55)
        ws.freeze_panes(1, 0)
        n = len(out)
        if n:
            ws.autofilter(0, 0, n, len(out.columns) - 1)
            ws.write(n + 1, 2, "Total (filtered)", bold)
            ws.write_formula(n + 1, 3, f"=SUBTOTAL(109,D2:D{n + 1})", bold_money)
        summary = out.groupby("Category")["Amount"].sum().reindex(CATEGORIES).fillna(0.0).to_frame("Total")
        summary.to_excel(xw, sheet_name="Summary")
        xw.sheets["Summary"].set_column(0, 0, 20)
        xw.sheets["Summary"].set_column(1, 1, 16, money)
    return buf.getvalue()
