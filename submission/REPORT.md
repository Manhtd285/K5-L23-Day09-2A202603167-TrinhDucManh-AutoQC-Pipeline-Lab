# Báo cáo Day 09 — Trịnh Đức Mạnh, 2A202603167

## 1. Kết luận trước

Kết luận: Hold (mã thoát 10). Pipeline nhận 224 ảnh đầu vào (data/raw), loại 21 ảnh ở cửa vào (2 CORRUPT_IMAGE, 3 BAD_SIZE, 8 DUP_IMAGE_EXACT, 3 DUP_IMAGE_NEAR, 5 LEAK_TEST) và xuất 203 ảnh ra bản nháp submission/export/clean_v1/. Dù đã sửa hết lỗi bắt buộc (0 ERROR) và dùng hết ngân sách duyệt 80/80 ảnh, vẫn còn 38/203 ảnh (18,7%) mang cảnh báo chưa được người duyệt — vượt ngưỡng 10,0% của cổng chặn nên chưa đủ điều kiện Release.

## 2. Lỗi và phân việc

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `CORRUPT_IMAGE` | 2/224 ảnh | Máy (intake/autofix) | Ảnh hỏng không giải mã được, phải loại bỏ ngay ở cửa vào. |
| `BAD_SIZE` | 3/224 ảnh | Máy (intake/autofix) | Cạnh ngắn `< 250px`, không đạt chuẩn độ phân giải đầu vào. |
| `DUP_IMAGE_EXACT` | 8/224 ảnh | Máy (intake/autofix) | Trùng từng byte (`md5`), quy tắc tất định loại bản sao. |
| `DUP_IMAGE_NEAR` | 3/224 ảnh | Máy (intake/autofix) | Trùng gần đúng (`phash_dist <= 8`), loại bản sao tránh lặp dữ liệu. |
| `LEAK_TEST` | 5/224 ảnh | Máy (intake/autofix) | Trùng với tập `test/val`, phải loại để tránh metric đẹp giả. |
| `MISSING_LABEL_FILE` | 6/203 ảnh | Người (`needs_label`) | Máy không được bịa nhãn; đẩy lên đầu hàng đợi để người gán. |
| `BAD_CLASS_NAME` | 1 file (`data.yaml`, 2 dòng) | Máy (`rename_classes`) | Sai tên/viết hoa trong `data.yaml`, máy sửa lại đúng danh sách lớp chuẩn. |
| `BAD_FORMAT` | 3 dòng (3/203 ảnh) | Máy (`drop_line`) | Dòng thiếu cột / `nan` / sai định dạng số, không cứu được nên xóa dòng. |
| `BAD_CLASS_ID` | 6 dòng (6/203 ảnh) | Máy (`drop_line`) | ID lớp ngoài `0..3` (vd. 93, 4, -1), máy xóa dòng sai quy tắc. |
| `BOX_ZERO` | 4 dòng (4/203 ảnh) | Máy (`drop_line`) | Box có `w <= 0` hoặc `h <= 0`, không có diện tích nên xóa dòng. |
| `DUP_BOX` | 7 dòng (7/203 ảnh) | Máy (`drop_line`) | Hai box cùng lớp trùng lặp (`IoU > 0.9`), xóa dòng lặp phía sau. |
| `BOX_OUT_OF_IMAGE` | 8 dòng (8/203 ảnh) | Máy (`clip_box`) | Box tràn mép ảnh, máy cắt an toàn về `[0, 1]` và giữ nguyên lớp. |
| `EMPTY_LABEL` | 12/203 ảnh | Người (hàng đợi) | File nhãn rỗng: máy không phân biệt được ảnh nền thật hay gán sót. |
| `BOX_TINY` | 6 dòng (4/203 ảnh) | Người (hàng đợi) | Cạnh ngắn `< 12px`, cần người xem nên giữ hay bỏ qua vật quá nhỏ. |
| `BOX_HUGE` | 3 dòng (3/203 ảnh) | Người (hàng đợi) | Box phủ `> 95%` ảnh, cần người kiểm tra có phải box lỗi không. |
| `CLASS_RARE` | 4 dòng (`<dataset>`) | Theo dõi tổng thể | Cảnh báo mức tập dữ liệu do vòng 1 còn ID lớp lạ (`93`, `4`, `-1`). |
| `POSSIBLE_WRONG_CLASS` | 18 dòng (18/203 ảnh) | Người (hàng đợi) | Model lớn nghi nhầm lớp (`car`/`truck`/`bus`), cần người xác nhận ngữ nghĩa. |
| `POSSIBLE_MISSING` | 53 dòng (52/203 ảnh) | Người (hàng đợi) | Model thấy vật nhưng nhãn thiếu, cần người kiểm tra và vẽ bổ sung. |
| `POSSIBLE_LOOSE_BOX` | 28 dòng (24/203 ảnh) | Người (hàng đợi) | Box lệch/lỏng so với model (`IoU < 0.5`), cần người căn chỉnh lại. |
| `POSSIBLE_FALSE_POS` | 25 dòng (24/203 ảnh) | Người (hàng đợi) | Box nhãn không khớp dự đoán nào của model, cần người xem có thừa không. |

- **Cơ chế xếp hạng hàng đợi (`05_review_queue.csv`):** `review_queue.py` cộng dồn điểm ưu tiên theo `weight[code] * (1 + conf)` (nếu có `conf`), trong đó `NEEDS_LABEL = 10` (cao nhất), tiếp theo là lỗi ngữ nghĩa nặng (`POSSIBLE_WRONG_CLASS = 3`, `POSSIBLE_MISSING = 2`, `POSSIBLE_FALSE_POS = 2`, `FIXED_DROP_LINE = 2`, `POSSIBLE_LOOSE_BOX = 1.5`), còn cảnh báo nhẹ như `BOX_TINY = 0.3` xếp cuối. Nhờ vậy, `img_0020` (`priority = 11.524`, vừa bị `FIXED_DROP_LINE` vừa có `POSSIBLE_MISSING` + `POSSIBLE_WRONG_CLASS`) và toàn bộ **6 ảnh thiếu file nhãn** (`NEEDS_LABEL`, `priority = 10.0`) được đẩy lên ngay đầu hàng đợi (vị trí #1–#7) để xử lý hết lỗi `ERROR`, tránh pipeline bị `Rework`.
- **Hiệu quả ngân sách 80 ảnh:** Hàng đợi có tổng cộng **125 ảnh**, ngân sách duyệt **80 ảnh** (64,0%). Đối chiếu từ `04_error_list_v2.csv` sang `07_error_list_v3.csv`, người duyệt đã xử lý được **66/123 lỗi ngữ nghĩa (53,7%)**, tập trung vào các lỗi nặng nhất: `POSSIBLE_WRONG_CLASS` (**15/18**, còn 3), `POSSIBLE_MISSING` (**40/53**, còn 13), `POSSIBLE_LOOSE_BOX` (**8/28**, còn 20), `POSSIBLE_FALSE_POS` (**3/24**, còn 21). Còn **45 ảnh** nằm ngoài ngân sách (trong đó 38 ảnh vẫn còn cảnh báo `WARN`) khiến Gate kết luận `Hold`.

## 3. Calibration (2 ngưỡng)

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 8 | `DUP_IMAGE_NEAR`: `1.00 / 0.50 (F1 0.67)` → `1.00 / 0.67 (F1 0.80)` | Lỗi `DUP_IMAGE_NEAR` / `LEAK_TEST` là lỗi bắt buộc (xóa ảnh) nên phải ưu tiên **Precision = 1.00** để không xóa oan ảnh sạch. Chọn `8` giúp nâng Recall từ `0.50` lên `0.67` so với ngưỡng `2` mà vẫn an toàn trên `raw` (tránh gộp nhầm như `16` hay làm gãy `DUP_IMAGE_EXACT` như `20`). |
| `second_opinion.conf` | 0.25 | 0.6 | `WRONG_CLASS`: `0.56/0.83 (F1 0.67)` → `0.62/0.83 (F1 0.71)`<br>`MISSING`: `0.50/1.00 (F1 0.67)` → `0.57/1.00 (F1 0.73)` | Đây là lỗi cảnh báo đẩy vào hàng đợi người (ngân sách 80 ảnh). Chọn `0.6` giúp tăng Precision (giảm báo động giả tốn công duyệt) mà vẫn giữ nguyên Recall (`0.83` cho `WRONG_CLASS` và `1.00` cho `MISSING`). Nếu tăng lên `0.7–0.8`, Recall của `MISSING` tụt xuống `0.88–0.75` (bỏ sót lỗi). |

 - **Điểm calibration có thể đánh lừa (kèm bằng chứng trên `data/raw`):**
  
  1. **Tập `calib` quá nhỏ (39 ảnh) khiến ngưỡng F1 cao nhất trên `calib` bị quá khớp và xóa nhầm trên `raw`:** Trên bảng sweep `calib`, `phash_dist = 16` đạt `P = 1.00 / R = 0.83 / F1 = 0.91` (cao nhất). Tuy nhiên, khi kiểm tra trực tiếp trên 224 ảnh `data/raw`, `phash_dist = 16` làm số ảnh bị cờ `DUP_IMAGE_NEAR` + `LEAK_TEST` tăng vọt từ 8 ảnh (ở ngưỡng `8`) lên 18 ảnh, và bắt nhầm các ảnh hoàn toàn khác nhau — ví dụ **`img_0011.jpg`** (người chơi tennis) bị coi là trùng với **`img_0008.jpg`** (hai người trượt tuyết) ở khoảng cách `phash = 16`. Trong khi đó ở ngưỡng `8`, cặp **`img_0223.jpg` và `img_0077.jpg`** (`phash = 6`) thực sự là cùng một bức ảnh bị thu nhỏ/nén sáng được bắt chính xác.
  2. **Phân bố lỗi khác nhau giữa `calib` và `raw`:** `calib` dựng từ nhãn người sạch rồi chèn lỗi nhân tạo (như `person → car`) và không có ca `LEAK_TEST`, nên chỉ số Recall trên `calib` không đại diện hoàn toàn cho lỗi tự nhiên trên `raw` (như nhầm lẫn giữa `car` / `truck` / `bus`).

## 4. Cửa chặn và điều pipeline KHÔNG bắt được

- **(a) Chứng minh cửa chặn `Rework` hoạt động đúng:**
  - Chạy thực nghiệm: `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb`
  - Kết quả thực tế: Vì ngân sách duyệt bằng `0`, **6 ảnh** bị lỗi bắt buộc `MISSING_LABEL_FILE` không được người gán nhãn bổ sung. Ở bước QC vòng 3, Gate phát hiện vẫn còn `6 lỗi bắt buộc (ERROR)` nên kết luận **`REWORK`**, trả về **mã thoát `20`** và in thông báo `KHÔNG xuất: còn lỗi bắt buộc (Rework) — trả về bước 3`. Kiểm tra thư mục `work/exp_nb/clean_v1` cho kết quả **không tồn tại (`False`)** — chứng minh lỗi bắt buộc luôn chặn xuất dataset.
- **(b) Các điểm mù pipeline KHÔNG bắt được (kèm bằng chứng):**
  1. **Box lỏng nhẹ có `0.5 <= IoU < 0.65`:** Do ngưỡng `second_opinion.iou_loose = 0.5` (cố định theo quy tắc dự án), mọi box nhãn cùng lớp có `IoU >= 0.5` với dự đoán của `yolo26l` đều không bị cờ `POSSIBLE_LOOSE_BOX`. Kiểm tra thực tế trên `work/run/ds` ghi nhận nhiều ca box lệch/lỏng nhẹ lọt qua im lặng như **`img_0068`** (`person`, `IoU = 0.523`, `conf = 0.85`), **`img_0118`** (`person`, `IoU = 0.563`, `conf = 0.61`), **`img_0021`** (`person`, `IoU = 0.577`, `conf = 0.68`).
  2. **Ảnh trùng biến đổi mạnh (crop sâu / đổi góc / biến đổi lớn) và vật thể nhỏ `< 600 px²`:** Với ngưỡng an toàn `phash_dist = 8`, `duplicates` chỉ đạt Recall `0.67` trên `calib` (bỏ sót các ca biến đổi mạnh để tránh xóa oan ảnh sạch như `img_0011` vs `img_0008` ở ngưỡng `16`). Tương tự, `second_opinion` bỏ qua dự đoán có diện tích `< 600 px²` nên vật thể ở xa bị thiếu nhãn sẽ không bị cờ `POSSIBLE_MISSING`.
  3. **Lỗi ngữ nghĩa nằm ngoài ngân sách duyệt 80 ảnh và lỗi mà cả model `yolo26l` cũng sai:** Khi model lớn `yolo26l` có cùng thiên kiến (nhầm lẫn giữa `truck`/`bus` hoặc tự tin thấp `< 0.6`), `second_opinion` sẽ im lặng. Ngoài ra, 45/125 ảnh cuối hàng đợi (vượt ngân sách 80 ảnh, ví dụ **`img_0018`** bị `BOX_HUGE`, **`img_0026`** bị `BOX_TINY` trong `07_error_list_v3.txt`) không được người duyệt tới nên cảnh báo vẫn tồn tại trong bản nháp `clean_v1`.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)

- **Cấu hình thực nghiệm công bằng (trên Colab T4):** Model `yolo26n.pt`, `20 epochs`, `batch = 16`, `imgsz = 640`, 2 seed (`0, 1`), cùng tập `gold_val` (40 ảnh) và `test` (100 ảnh). Số ảnh train: `raw` = **224 ảnh**, `clean` (`clean_v1` bản nháp `Hold`) = **203 ảnh**.

| biến thể | #ảnh train | số seed | map50 (TB ± độ lệch) | map50_95 (TB ± độ lệch) | precision (TB ± độ lệch) | recall (TB ± độ lệch) |
|---|---|---|---|---|---|---|
| raw | 224 | 2 | 0.726 ± 0.000 | 0.512 ± 0.004 | 0.764 ± 0.061 | 0.649 ± 0.028 |
| clean | 203 | 2 | 0.699 ± 0.025 | 0.486 ± 0.013 | 0.796 ± 0.050 | 0.596 ± 0.049 |

Chênh mAP50 (`clean − raw`) = **-0.027**.

- **So sánh chênh lệch với độ nhiễu & kết luận trung thực:** Chênh lệch `mAP50` giữa `clean` và `raw` (`-0.027`) có độ lớn gần bằng đúng độ lệch chuẩn giữa 2 seed của `clean` (`± 0.025`; riêng ở seed 1, `clean` đạt `0.7163` gần sát `raw` `0.7259`). Vì tập `test` chỉ có 100 ảnh và chênh lệch nằm xấp xỉ ngưỡng nhiễu giữa các seed (trong khi `precision` của `clean` tăng từ `0.764` lên `0.796`, còn `recall` giảm từ `0.649` xuống `0.596`), **chưa thể kết luận `clean` kém hơn hay tốt hơn `raw` một cách chắc chắn**; cần giữ kết luận trung thực là sự khác biệt nằm trong vùng nhiễu thử nghiệm.
- **Giả thuyết giải thích & cách kiểm chứng:**
  1. **Rò rỉ tập test (`LEAK_TEST`) trong `raw` làm metric của `raw` cao giả:** `raw` chứa **5 ảnh trùng trực tiếp với tập `test`** (`img_0049`, `img_0101`, `img_0167`, `img_0174`, `img_0221`) và **11 ảnh trùng lặp** nên model `raw` có lợi thế "nhớ đề" trên tập `test`, trong khi `clean` đã loại bỏ 5 ảnh này. *Cách kiểm chứng:* Đánh giá lại cả 2 model trên tập `test` đã loại 5 ảnh bị rò rỉ (hoặc đo riêng `clean` khi không bị leak) để xem khoảng cách mAP50 có đảo chiều hay không.
  2. **`clean_v1` mới ở trạng thái `Hold` (giảm 21 ảnh train và còn 38/203 ảnh cảnh báo chưa duyệt):** Số lượng ảnh train giảm từ 224 xuống 203 (đặc biệt ở seed 0, AP50 lớp `truck` giảm từ `0.657 → 0.484` trong khi `person` và `bus` lại tăng), đồng thời 45/125 ảnh ngoài ngân sách duyệt 80 ảnh vẫn giữ nhãn máy cũ (có thể sót box làm giảm `recall`). *Cách kiểm chứng:* Duyệt hết 38 ảnh cảnh báo còn lại để đạt `Release` và chạy train với ≥ 3–5 seed (kèm biến thể `oracle`) để tách rõ nhiễu ngẫu nhiên khỏi hiệu ứng dữ liệu.

## 6. Quyết định và ghi chú AI

- **(a) Quyết định cuối cùng & điều kiện chuyển thành `Release`:**
  - **Quyết định cuối cùng:** **`Hold`** (mã thoát `10`) — chỉ xuất bản **nháp** `submission/export/clean_v1/` để thử nghiệm train, **không** phát hành chính thức.
  - **Điều kiện để chuyển thành `Release`:** Duy trì `0` lỗi bắt buộc (`ERROR`) và giảm số ảnh cảnh báo chưa duyệt từ **38/203 (18,7%)** xuống dưới ngưỡng `10,0%` (`<= 20/203` ảnh), tức cần phân bổ thêm ngân sách để người duyệt kiểm tra bổ sung ít nhất **18 ảnh** tiếp theo trong `05_review_queue.csv` (hoặc duyệt hết toàn bộ 45 ảnh còn lại ngoài ngân sách 80 ảnh).
- **(b) Nhật ký sử dụng AI:**
  1. **Prompt chính:** Dán docstring chuẩn của từng module (`label_format`, `gate`, `autofix`, `second_opinion`) kèm unit test mẫu và 4 ràng buộc an toàn (chỉ đọc từ `ds`/`cfg`, không sửa `data/raw` hay file bảo vệ SHA-1, không đọc đáp án `MANIFEST`/`review_reference`, giữ nguyên số dòng gốc khi có dòng trống).
  2. **Cách kiểm tra code AI:** Đọc lướt từng dòng kiểm tra thao tác xóa/ghi file và xử lý ngoại lệ, chạy `pytest` từng module đến khi xanh toàn bộ `79 passed`, đối chiếu kết quả trên tập `data/calib/` (`calibration_report.md`) và mở xem ảnh thực tế trên `data/raw` bằng `viz_labels.py`.
  3. **1 lần AI sai/sót & cách sửa:** Ở `second_opinion.py`, nếu dùng `ds.valid_boxes(stem)` để kiểm `POSSIBLE_FALSE_POS` sẽ bị mất chỉ số dòng gốc khi file nhãn có dòng trống hoặc dòng hỏng xen giữa (làm sai `Issue.line`); đã sửa lại bằng cách duyệt `ds.read_label_lines(stem)` kết hợp `parse_yolo_line` trong `try/except` để giữ chính xác số dòng gốc. *(Ngoài ra, sau khi cập nhật `configs/pipeline.yaml` đã chạy lại đầy đủ lệnh `pipeline.calibrate` kèm đủ 2 cờ `--sweep` để `calibration.json` không bị trống mục `sweeps`.)*

*(Thưởng +2, tùy chọn)* CVAT: lọc `width < 20`, ảnh/số box khớp, đối chiếu `BOX_TINY` (xem docs/CVAT_FILTER.md), 1 câu về `can_review`.
