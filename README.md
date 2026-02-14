# SFC View

Flask app (port **5556**) xem dữ liệu **Fail Result** từ SFC, tích hợp Bonepile disposition. Chọn ngày/giờ → Apply Filter → SFC API → parse HTML → analytics (Summary, Tray Summary, SKU, Time Breakdown, Test Flow).

## Cấu trúc

```
SFC_View/
├── config/           # Cấu hình tập trung
│   ├── app_config.py
│   ├── pass_rules.py   # Part number → pass station
│   └── bonepile_config.py
├── sfc/              # SFC API client + parser
├── analytics/        # Logic tính toán (summary, tray, sku, breakdown, test_flow)
├── bonepile_disposition.py  # Upload/parse NV bonepile
└── app.py
```

## Cài đặt

```bash
cd C:\Users\FAswing\SFC_View
pip install -r requirements.txt
```

## Chạy

```bash
python app.py
```

Mở http://localhost:5556

## API chính

- **POST /api/query** – Apply Filter: `{ start_datetime, end_datetime, aggregation? }` → trả summary, tray_summary, sku_rows, breakdown_rows, test_flow
- **POST /api/sn-list** – Drill-down SN: `{ metric, sku?, period?, station?, outcome? }`
- **POST /api/export** – Export CSV (có cột BP)

## Cấu hình (env)

- `SFC_BASE_URL` – Base URL SFC (mặc định `http://10.16.137.110`)
- `SFC_USER` / `SFC_PWD` – User/Password SFC (mặc định SFC / EPD2TJW)

## Config (sửa tại `config/`)

- **pass_rules.py**: `PASS_AT_FCT_PART_NUMBERS`, `get_pass_station_for_part_number`
- **bonepile_config.py**: `BONEPILE_IGNORED_SHEETS` (blacklist: only these sheets are skipped)
