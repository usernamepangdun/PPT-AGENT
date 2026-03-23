from pathlib import Path
import io
from pptx import Presentation
from pptx.util import Inches

SLIDE_W = Inches(13.33)
SLIDE_H = Inches(7.5)


def html_to_png_bytes(html_path: Path) -> bytes:
    """用 playwright 将 HTML 文件渲染为 1280×720 PNG。"""
    from playwright.sync_api import sync_playwright
    html_content = html_path.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(html_content, wait_until="networkidle")
        png = page.screenshot(type="png", clip={
            "x": 0, "y": 0, "width": 1280, "height": 720,
        })
        browser.close()
    return png


def build_pptx(html_dir: Path, output_path: Path) -> Path:
    """将 HTML 目录中的所有 HTML 文件转换为 PPTX。"""
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    blank_layout = prs.slide_layouts[6]

    html_files = sorted(html_dir.glob("*.html"))
    if not html_files:
        raise ValueError(f"HTML 目录为空: {html_dir}")

    for html_path in html_files:
        print(f"  插入: {html_path.name}")
        slide = prs.slides.add_slide(blank_layout)
        try:
            png_bytes = html_to_png_bytes(html_path)
            slide.shapes.add_picture(
                io.BytesIO(png_bytes), left=0, top=0,
                width=SLIDE_W, height=SLIDE_H,
            )
        except Exception as e:
            print(f"  [警告] {html_path.name} 失败: {e}，跳过")

    prs.save(str(output_path))
    print(f"PPT 已保存: {output_path}")
    return output_path
