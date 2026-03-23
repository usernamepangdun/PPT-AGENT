"""SVG 文本溢出检测器

解析 SVG 中的卡片（rect）和文本（text/tspan），
检测文本是否超出所属卡片的边界（水平溢出、垂直溢出、文本重叠）。
"""

import re
import unicodedata
import xml.etree.ElementTree as ET

NS = {"svg": "http://www.w3.org/2000/svg"}


def _parse_translate(transform: str) -> tuple[float, float]:
    """从 transform 属性中提取 translate(x, y)。"""
    if not transform:
        return 0.0, 0.0
    m = re.search(r"translate\(\s*([-\d.]+)[\s,]+([-\d.]+)\s*\)", transform)
    if m:
        return float(m.group(1)), float(m.group(2))
    # translate(x) 只有一个参数
    m = re.search(r"translate\(\s*([-\d.]+)\s*\)", transform)
    if m:
        return float(m.group(1)), 0.0
    return 0.0, 0.0


def _get_ancestor_offset(elem, parent_map: dict) -> tuple[float, float]:
    """递归累积所有祖先 <g> 的 translate 偏移。"""
    ox, oy = 0.0, 0.0
    current = elem
    while current in parent_map:
        parent = parent_map[current]
        tag = parent.tag.split("}")[-1] if "}" in parent.tag else parent.tag
        if tag == "g":
            tx, ty = _parse_translate(parent.get("transform", ""))
            ox += tx
            oy += ty
        current = parent
    return ox, oy


def _char_width_ratio(ch: str) -> float:
    """估算单个字符相对于 font-size 的宽度比。"""
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 0.95  # 中文/全角
    if ch in " \t":
        return 0.25
    if ch in ".,;:!?·、，。；：！？""''（）(){}[]【】":
        return 0.5
    return 0.55  # 英文/半角


def _estimate_text_width(text: str, font_size: float) -> float:
    """估算一段文本的渲染宽度（px）。"""
    if not text:
        return 0.0
    return sum(_char_width_ratio(ch) for ch in text) * font_size


def _parse_font_size(elem, style_map: dict) -> float:
    """从元素的 font-size 属性或 class 样式中提取字号。"""
    # 直接属性
    fs = elem.get("font-size")
    if fs:
        return float(re.sub(r"[^0-9.]", "", fs) or "16")
    # 从 class 查找
    cls = elem.get("class", "")
    for c in cls.split():
        if c in style_map:
            return style_map[c]
    return 16.0


def _parse_style_block(root) -> dict[str, float]:
    """从 <style> 块中提取 class -> font-size 映射。"""
    result = {}
    for style_elem in root.iter():
        tag = style_elem.tag.split("}")[-1] if "}" in style_elem.tag else style_elem.tag
        if tag == "style" and style_elem.text:
            for m in re.finditer(r"\.(\w+)\s*\{([^}]+)\}", style_elem.text):
                cls_name = m.group(1)
                props = m.group(2)
                fs_match = re.search(r"font-size\s*:\s*([\d.]+)", props)
                if fs_match:
                    result[cls_name] = float(fs_match.group(1))
    return result


def _collect_rects(root, parent_map: dict, canvas_w: float, canvas_h: float) -> list[dict]:
    """收集所有 rect 元素及其全局坐标（排除画布背景）。"""
    rects = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag != "rect":
            continue
        w = float(elem.get("width", 0))
        h = float(elem.get("height", 0))
        if w < 60 or h < 50:
            continue  # 跳过小装饰 rect（胶囊、badge、标签等）
        if w >= canvas_w and h >= canvas_h:
            continue  # 跳过画布背景 rect
        x = float(elem.get("x", 0))
        y = float(elem.get("y", 0))
        ox, oy = _get_ancestor_offset(elem, parent_map)
        rects.append({
            "x": x + ox, "y": y + oy,
            "w": w, "h": h,
            "right": x + ox + w, "bottom": y + oy + h,
        })
    return rects


def _find_containing_rect(tx: float, ty: float, rects: list[dict]) -> dict | None:
    """找到包含文本起点坐标的最小 rect。"""
    candidates = []
    for r in rects:
        if r["x"] <= tx <= r["right"] and r["y"] <= ty <= r["bottom"]:
            candidates.append(r)
    if not candidates:
        return None
    # 选面积最小的（最紧密的卡片）
    return min(candidates, key=lambda r: r["w"] * r["h"])


def _collect_text_lines(root, parent_map: dict, style_map: dict) -> list[dict]:
    """收集所有文本行及其全局坐标和估算宽度。"""
    lines = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag != "text":
            continue

        ox, oy = _get_ancestor_offset(elem, parent_map)
        base_x = float(elem.get("x", 0)) + ox
        base_y = float(elem.get("y", 0)) + oy
        font_size = _parse_font_size(elem, style_map)
        anchor = elem.get("text-anchor", "start")

        # 检查是否有 tspan 子元素
        tspans = [ch for ch in elem if (ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag) == "tspan"]

        if tspans:
            # 按行分组：有 x 属性或 dy!=0 的 tspan 开始新行，否则归入当前行
            current_line_parts = []
            current_line_x = base_x
            current_line_y = base_y
            current_line_anchor = anchor
            cum_dy = 0.0

            def _flush_line():
                if not current_line_parts:
                    return
                full_text = "".join(current_line_parts)
                if not full_text.strip():
                    return
                width = _estimate_text_width(full_text, font_size)
                a = current_line_anchor
                if a == "middle":
                    left = current_line_x - width / 2
                elif a == "end":
                    left = current_line_x - width
                else:
                    left = current_line_x
                lines.append({
                    "text": full_text.strip(), "x": left, "y": current_line_y,
                    "width": width, "right": left + width,
                    "top": current_line_y - font_size * 0.85,
                    "bottom": current_line_y + font_size * 0.3,
                    "font_size": font_size,
                })

            for i, ts in enumerate(tspans):
                ts_x = ts.get("x")
                ts_dy = ts.get("dy", "0")
                dy_val = float(ts_dy)
                has_new_x = ts_x is not None
                has_dy = dy_val != 0

                # 判断是否开始新行
                if i > 0 and (has_new_x or has_dy):
                    _flush_line()
                    current_line_parts = []

                if has_dy:
                    cum_dy += dy_val
                if has_new_x:
                    current_line_x = float(ts_x) + ox
                current_line_y = base_y + cum_dy
                current_line_anchor = ts.get("text-anchor") or anchor

                ts_fs = _parse_font_size(ts, style_map)
                if ts_fs != font_size and ts_fs != 16.0:
                    font_size = ts_fs

                # 收集本 tspan 的文本（包括 tail）
                part = (ts.text or "") + "".join((sub.tail or "") for sub in ts)
                if ts.tail:
                    part += ts.tail
                current_line_parts.append(part)

            _flush_line()
        else:
            # 纯 text 元素，可能包含混合内容（text + 内联 tspan）
            parts = []
            if elem.text and elem.text.strip():
                parts.append(elem.text.strip())
            for child in elem:
                if child.text and child.text.strip():
                    parts.append(child.text.strip())
                if child.tail and child.tail.strip():
                    parts.append(child.tail.strip())
            text = "".join(parts)
            if not text:
                continue
            width = _estimate_text_width(text, font_size)
            if anchor == "middle":
                left = base_x - width / 2
            elif anchor == "end":
                left = base_x - width
            else:
                left = base_x
            lines.append({
                "text": text, "x": left, "y": base_y,
                "width": width, "right": left + width,
                "top": base_y - font_size * 0.85,
                "bottom": base_y + font_size * 0.3,
                "font_size": font_size,
            })
    return lines


def check_svg(svg_str: str) -> list[dict]:
    """检查 SVG 中的文本问题：水平溢出、垂直溢出、文本重叠。

    返回问题列表，每项包含:
      direction: "horizontal" | "vertical" | "overlap"
      text: 溢出的文本内容（overlap 时为 text1）
      text2: 重叠的另一文本（仅 overlap）
      overflow / overflow_y / overlap_area: 溢出量或重叠面积
    空列表表示无问题。
    """
    try:
        root = ET.fromstring(svg_str)
    except ET.ParseError:
        return []

    # 获取画布尺寸用于排除背景 rect
    canvas_w = float(root.get("width", 1280))
    canvas_h = float(root.get("height", 720))

    parent_map = {child: parent for parent in root.iter() for child in parent}
    style_map = _parse_style_block(root)
    rects = _collect_rects(root, parent_map, canvas_w, canvas_h)
    text_lines = _collect_text_lines(root, parent_map, style_map)

    issues = []
    padding = 16  # 卡片内边距安全阈值

    # 为每个 text line 记录其所属 rect，供后续重叠检测使用
    line_rects = []
    for line in text_lines:
        rect = _find_containing_rect(line["x"], line["y"], rects)
        line_rects.append(rect)
        if not rect:
            continue
        # 水平溢出检测
        card_right = rect["right"] - padding
        if line["right"] > card_right:
            overflow = round(line["right"] - card_right, 1)
            issues.append({
                "direction": "horizontal",
                "text": line["text"],
                "card_width": round(rect["w"]),
                "text_width": round(line["width"]),
                "overflow": overflow,
                "text_x": round(line["x"]),
                "text_y": round(line["y"]),
                "card_x": round(rect["x"]),
                "card_y": round(rect["y"]),
            })
        # 垂直溢出检测
        card_bottom = rect["bottom"] - padding
        if line["bottom"] > card_bottom:
            overflow_y = round(line["bottom"] - card_bottom, 1)
            issues.append({
                "direction": "vertical",
                "text": line["text"],
                "card_height": round(rect["h"]),
                "overflow_y": overflow_y,
                "text_x": round(line["x"]),
                "text_y": round(line["y"]),
                "card_x": round(rect["x"]),
                "card_y": round(rect["y"]),
                "card_bottom": round(rect["bottom"]),
            })

    # 文本重叠检测（仅检测属于同一 rect 的文本对）
    overlap_threshold = 50  # 重叠面积阈值（px²）
    for i in range(len(text_lines)):
        for j in range(i + 1, len(text_lines)):
            ri, rj = line_rects[i], line_rects[j]
            # 跳过不属于同一 rect 的文本对（含无 rect 的）
            if ri is None or rj is None or ri is not rj:
                continue
            a, b = text_lines[i], text_lines[j]
            # 计算水平重叠
            h_overlap = min(a["right"], b["right"]) - max(a["x"], b["x"])
            if h_overlap <= 0:
                continue
            # 计算垂直重叠
            v_overlap = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
            if v_overlap <= 0:
                continue
            area = round(h_overlap * v_overlap, 1)
            if area >= overlap_threshold:
                issues.append({
                    "direction": "overlap",
                    "text": a["text"],
                    "text2": b["text"],
                    "overlap_area": area,
                    "text1_xy": f"({round(a['x'])},{round(a['y'])})",
                    "text2_xy": f"({round(b['x'])},{round(b['y'])})",
                    "card_x": round(ri["x"]),
                    "card_y": round(ri["y"]),
                })

    return issues


def format_issues(issues: list[dict]) -> str:
    """将检测问题格式化为给 AI 的修复提示。"""
    if not issues:
        return ""

    h_issues = [i for i in issues if i["direction"] == "horizontal"]
    v_issues = [i for i in issues if i["direction"] == "vertical"]
    o_issues = [i for i in issues if i["direction"] == "overlap"]

    parts = []
    idx = 1

    if h_issues:
        parts.append("【水平溢出】以下文本超出了所属卡片的宽度边界：")
        for iss in h_issues:
            t = iss["text"][:30] + ("…" if len(iss["text"]) > 30 else "")
            parts.append(
                f"{idx}. 文本「{t}」位于({iss['text_x']},{iss['text_y']})，"
                f"估算宽度 {iss['text_width']}px，超出卡片（x={iss['card_x']},y={iss['card_y']},"
                f"w={iss['card_width']}）右边界约 {iss['overflow']}px"
            )
            idx += 1

    if v_issues:
        parts.append("")
        parts.append("【垂直溢出】以下文本底部超出了所属卡片的底边：")
        for iss in v_issues:
            t = iss["text"][:30] + ("…" if len(iss["text"]) > 30 else "")
            parts.append(
                f"{idx}. 文本「{t}」位于({iss['text_x']},{iss['text_y']})，"
                f"超出卡片（x={iss['card_x']},y={iss['card_y']},h={iss['card_height']}，"
                f"底边y={iss['card_bottom']}）约 {iss['overflow_y']}px"
            )
            idx += 1

    if o_issues:
        parts.append("")
        parts.append("【文本重叠】以下文本之间存在区域重叠：")
        for iss in o_issues:
            t1 = iss["text"][:20] + ("…" if len(iss["text"]) > 20 else "")
            t2 = iss["text2"][:20] + ("…" if len(iss["text2"]) > 20 else "")
            parts.append(
                f"{idx}. 文本「{t1}」{iss['text1_xy']}与"
                f"「{t2}」{iss['text2_xy']}重叠（面积约 {iss['overlap_area']}px²），"
                f"所属卡片位于({iss['card_x']},{iss['card_y']})"
            )
            idx += 1

    parts.append("")
    parts.append("修复要求：")
    parts.append("- 只调整问题文本部分，保持页面其他设计不变")
    parts.append("- 优先通过缩短文案、拆成更多行来解决，不要缩小字号")
    if v_issues:
        parts.append("- 垂直溢出可通过减少行数、缩小行间距 dy 或增大卡片高度来修复")
    if o_issues:
        parts.append("- 文本重叠可通过调整 y 坐标拉开间距、或为文本分配独立卡片区域来修复")
    parts.append("- 确保修复后所有文本都在卡片安全边界内且互不重叠")
    parts.append("- 输出完整的修复后 SVG 代码")
    return "\n".join(parts)
