# `LOG_ITTOOLS_T` — 15 tham số `LogRecord` (pattern T05 / UpdateErrorFlag)

Bảng `SFISM4.LOG_ITTOOLS_T` được insert bằng:

`INSERT INTO SFISM4.LOG_ITTOOLS_T SELECT <15 giá trị> FROM DUAL`

Thứ tự cột theo code C# `DBAccess.LogRecord` (không có DDL trong repo — ý nghĩa suy ra từ cách dùng).

| Index | Ví dụ (fail ERROR_FLAG) | Ý nghĩa (ước lượng) |
|------:|-------------------------|---------------------|
| `[0]` | `UPDATE` | Loại thao tác: cập nhật dữ liệu |
| `[1]` | `T05` | Mã module / tool (T05 = WIP / error flag…) |
| `[2]` | `WIP查進退` | Tên chức năng / màn hình (tiếng Trung trong app gốc) |
| `[3]` | `修改ERRO_FLAG` | Mô tả hành động cụ thể (sửa ERROR_FLAG) |
| `[4]` | `SYSDATE` | Thời điểm ghi log (Oracle SYSDATE) |
| `[5]` | `SERIAL_NUMBER` | Ngữ cảnh chính: thường là SN |
| `[6]` | `NULL` (T05) | Dong log chi tiet script: **ERROR_DESC cắt tối đa 100 ký tự** (khớp MO_NUMBER VARCHAR2(100)) |
| `[7]` | `NULL` | Trường phụ (chưa dùng) |
| `[8]` | `SFISM4.R_WIP_TRACKING_T` | Bảng bị ảnh hưởng |
| `[9]` | `ERROR_FLAG` | Tên cột thay đổi |
| `[10]` | `NULL` | Giá trị cũ (trước khi đổi) |
| `[11]` | 1 ký tự (T05) / `FLAG=x \| EC=...` (dong log chi tiet script) | T05: cùng giá trị đã UPDATE lên `ERROR_FLAG` |
| `[12]` | `EMP_NO` | Người thực hiện |
| `[13]` | `EMP_NO` | Lặp lại EMP (theo pattern gốc) |
| `[14]` | IP (vd `127.0.0.1`) | IP máy client |

**Lưu ý:** `R_WIP_TRACKING_T.ERROR_FLAG` chỉ **1 ký tự** — script map từ `C_ERROR_CODE_T` trước khi `UPDATE`. Luồng [2]: **PASS (jump)** → fail → log T05 + dòng `ERROR_FULL_LOG` ([6] mô tả ≤100).
