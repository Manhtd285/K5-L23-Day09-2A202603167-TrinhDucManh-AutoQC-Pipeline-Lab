"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    sc = cfg["second_opinion"]
    n_classes = len(ds.classes)
    issues = []

    for img_path in ds.image_files():
        stem = img_path.stem
        if stem not in preds or not ds.label_path(stem).exists():
            continue
        size = ds.image_size(stem)
        if size is None:
            continue
        W, H = size

        img_preds = preds[stem]
        valid_labels = ds.valid_boxes(stem)

        # 1. Duyệt dự đoán mạnh & đủ lớn của model thứ hai
        for pr in img_preds:
            p_cls, p_conf, pcx, pcy, pw, ph = pr
            area_px = (pw * W) * (ph * H)
            if p_conf < sc["conf"] or area_px < sc["min_area_px"]:
                continue

            p_box = (pcx, pcy, pw, ph)
            cands = []
            for l_cls, lcx, lcy, lw, lh in valid_labels:
                if lw <= 0 or lh <= 0:
                    continue
                iou = iou_xywh(p_box, (lcx, lcy, lw, lh))
                if iou >= sc["iou_missing"]:
                    cands.append((l_cls, iou))

            if not cands:
                issues.append(
                    Issue("second_opinion", WARN, "POSSIBLE_MISSING", stem,
                          f"model thấy lớp {p_cls} (conf={p_conf:.2f}) nhưng nhãn không có box",
                          extra={"conf": round(float(p_conf), 4), "cls": int(p_cls)})
                )
                continue

            same_ious = [iou for l_cls, iou in cands if l_cls == p_cls]
            if same_ious:
                best_same = max(same_ious)
                if best_same < sc["iou_loose"]:
                    issues.append(
                        Issue("second_opinion", WARN, "POSSIBLE_LOOSE_BOX", stem,
                              f"box khớp lớp {p_cls} nhưng lỏng (IoU={best_same:.2f} < {sc['iou_loose']})",
                              extra={"iou": round(float(best_same), 4), "conf": round(float(p_conf), 4)})
                    )
            else:
                best_other = max(iou for _, iou in cands)
                if best_other >= sc["iou_match"]:
                    issues.append(
                        Issue("second_opinion", WARN, "POSSIBLE_WRONG_CLASS", stem,
                              f"khớp vị trí (IoU={best_other:.2f}) nhưng khác lớp với dự đoán {p_cls} (conf={p_conf:.2f})",
                              extra={"conf": round(float(p_conf), 4), "iou": round(float(best_other), 4)})
                    )

        # 2. Duyệt từng dòng nhãn hợp lệ để tìm POSSIBLE_FALSE_POS (giữ số dòng gốc)
        fp_preds = [pr for pr in img_preds if pr[1] >= sc["fp_conf"]]
        for line_no, text in ds.read_label_lines(stem) or []:
            try:
                l_cls, lcx, lcy, lw, lh = parse_yolo_line(text)
            except ValueError:
                continue
            if not (0 <= l_cls < n_classes) or lw <= 0 or lh <= 0:
                continue

            l_box = (lcx, lcy, lw, lh)
            matched = any(
                iou_xywh(l_box, (pr[2], pr[3], pr[4], pr[5])) >= sc["iou_missing"]
                for pr in fp_preds
            )
            if not matched:
                issues.append(
                    Issue("second_opinion", WARN, "POSSIBLE_FALSE_POS", stem,
                          f"box dòng {line_no} không khớp dự đoán nào của model",
                          line=line_no)
                )

    return issues
