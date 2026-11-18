"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict

import yaml

from ..common import ERROR, parse_yolo_line

REMOVE_IMAGE_CODES = {
    "DUP_IMAGE_EXACT",
    "DUP_IMAGE_NEAR",
    "LEAK_TEST",
    "CORRUPT_IMAGE",
    "BAD_SIZE",
}
DROP_LINE_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}


def _fix_row(image, line, action, before, after):
    return {
        "image": image,
        "line": "" if line is None else line,
        "action": action,
        "before": before,
        "after": after,
    }


def fix(ds, issues, cfg):
    err_issues = [i for i in issues if i.severity == ERROR]
    fixes = []
    removed = set()

    # 1. Xoá ảnh lỗi ở cửa vào (ảnh hỏng, kích thước nhỏ, trùng, rò rỉ test)
    for i in err_issues:
        if i.code in REMOVE_IMAGE_CODES:
            stem = i.image
            if stem in removed:
                continue
            ip = ds.image_path(stem)
            if ip is not None and ip.exists():
                ip.unlink()
            lp = ds.label_path(stem)
            if lp.exists():
                lp.unlink()
            removed.add(stem)
            fixes.append(_fix_row(stem, None, "remove_image", stem, "(đã xoá ảnh và nhãn)"))

    # 2. Sửa tên lớp trong data.yaml (tối đa 1 lần cho cả batch)
    if any(i.code == "BAD_CLASS_NAME" for i in err_issues):
        before_names = ds.yaml_names()
        data = {}
        if ds.yaml_path.exists():
            data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            data = {}
        new_names = {idx: name for idx, name in enumerate(cfg["classes"])}
        data["names"] = new_names
        ds.yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        fixes.append(_fix_row("data.yaml", None, "rename_classes", str(before_names), str(new_names)))

    # 3. Ảnh thiếu file nhãn -> chuyển người gán, KHÔNG tạo file rỗng
    for i in err_issues:
        if i.code == "MISSING_LABEL_FILE" and i.image not in removed:
            fixes.append(_fix_row(i.image, None, "needs_label", "(không có file)", "chuyển người gán"))

    # 4. Gom lỗi cấp dòng theo từng file nhãn rồi xử lý một lần
    per_file = defaultdict(lambda: defaultdict(set))
    for i in err_issues:
        if i.image in removed or i.line is None:
            continue
        if i.code in DROP_LINE_CODES or i.code == "BOX_OUT_OF_IMAGE":
            per_file[i.image][i.line].add(i.code)

    for stem in sorted(per_file):
        lp = ds.label_path(stem)
        if not lp.exists():
            continue
        orig_lines = lp.read_text(encoding="utf-8", errors="replace").splitlines()
        new_lines = []
        changed = False

        for line_no, raw_ln in enumerate(orig_lines, 1):
            codes = per_file[stem].get(line_no)
            if not codes:
                new_lines.append(raw_ln)
                continue

            if codes & DROP_LINE_CODES:
                fixes.append(_fix_row(stem, line_no, "drop_line", raw_ln, "(đã xoá)"))
                changed = True
                continue

            if "BOX_OUT_OF_IMAGE" in codes:
                try:
                    cls_id, cx, cy, w, h = parse_yolo_line(raw_ln)
                except ValueError:
                    fixes.append(_fix_row(stem, line_no, "drop_line", raw_ln, "(đã xoá)"))
                    changed = True
                    continue

                x1 = max(0.0, min(1.0, cx - w / 2))
                y1 = max(0.0, min(1.0, cy - h / 2))
                x2 = max(0.0, min(1.0, cx + w / 2))
                y2 = max(0.0, min(1.0, cy + h / 2))
                nw = x2 - x1
                nh = y2 - y1

                if nw <= 1e-6 or nh <= 1e-6:
                    fixes.append(_fix_row(stem, line_no, "drop_line", raw_ln, "(đã xoá: ngoài ảnh)"))
                    changed = True
                    continue

                ncx, ncy = (x1 + x2) / 2, (y1 + y2) / 2
                clipped = f"{cls_id} {ncx:.6f} {ncy:.6f} {nw:.6f} {nh:.6f}"
                new_lines.append(clipped)
                fixes.append(_fix_row(stem, line_no, "clip_box", raw_ln, clipped))
                changed = True

        if changed:
            content = "\n".join(new_lines) + "\n" if new_lines else ""
            lp.write_text(content, encoding="utf-8")

    return fixes
