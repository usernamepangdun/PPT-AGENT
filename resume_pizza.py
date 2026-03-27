"""续跑脚本：从已有 outline.json 开始，完成披萨的由来 PPT 生成。"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_client import AIClient
from config import OUTPUT_DIR, REVIEW_ENABLED, REVIEW_PROVIDER, REVIEW_MODEL, REVIEW_REASONING_EFFORT
from pipeline import step2_content, step3_plan, _get_pages, _get_title
from html_pipeline.pipeline import (
    step4_html, _infer_page_role, _validate_and_optionally_regenerate,
    _review_and_optionally_fix,
)

TOPIC = "披萨的由来"
AUDIENCE = "销售团队"
POLISH = os.getenv("HTML_POLISH_MODE", "false").lower() in {"1", "true", "yes", "on"}

def main():
    out = Path(OUTPUT_DIR) / TOPIC
    outline_path = out / "outline.json"

    print(f"加载已有大纲：{outline_path}")
    outline = json.loads(outline_path.read_text(encoding="utf-8"))

    client = AIClient(None)
    review_client = None
    if REVIEW_ENABLED:
        review_client = AIClient(REVIEW_PROVIDER)
        if REVIEW_MODEL:
            review_client.model = REVIEW_MODEL

    print("[2/4] 扩写内容...")
    contents = step2_content(client, outline)
    (out / "contents.json").write_text(
        json.dumps(contents, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> contents.json 已保存，共 {len(contents)} 页")

    print("[3/4] 生成策划稿 + HTML...")
    html_dir = out / "html"
    html_dir.mkdir(exist_ok=True)
    slide_status = {}
    for old_html in html_dir.glob("*.html"):
        old_html.unlink()

    all_pages = _get_pages(outline)
    total_pages = len(all_pages)
    idx = 1
    for page in all_pages:
        title = _get_title(page)
        material = contents.get(title, "")
        plan = step3_plan(client, title, material)
        page_role = _infer_page_role(idx, total_pages, title, plan, material)
        html_path = html_dir / f"{idx:02d}_{title[:20]}.html"
        print(f"  [{idx}/{total_pages}] {title[:30]}...")
        html = step4_html(client, title, material, plan, AUDIENCE, page_role)
        html_path.write_text(html, encoding="utf-8")
        validation_report = _validate_and_optionally_regenerate(
            client, html_path, title, material, plan, AUDIENCE, page_role, POLISH
        )
        review_result = _review_and_optionally_fix(
            client, review_client, html_path, idx, title, material, plan, AUDIENCE, page_role, validation_report
        )
        final_validation_status = review_result.get("post_fix_validation_status", validation_report.get("status"))
        final_issues_count = review_result.get("post_fix_final_issues", len(validation_report.get("final_issues") or []))
        export_ready = final_validation_status == "pass" and review_result.get("result") != "REVISE"
        slide_status[f"{idx:02d}"] = {
            "title": title,
            "page_role": page_role,
            "validation_status": final_validation_status,
            "final_issues_count": final_issues_count,
            "review_status": review_result.get("result"),
            "review_rounds": review_result.get("review_rounds", 0),
            "review_path": review_result.get("review_path"),
            "export_ready": export_ready,
        }
        from html_pipeline.html_builder import write_slide_status
        write_slide_status(out, slide_status)
        idx += 1

    print("[4/4] 合成 PPT...")
    from html_pipeline.html_builder import build_pptx
    pptx_path = out / f"{TOPIC[:30]}.pptx"
    build_pptx(html_dir, pptx_path)
    print(f"\n完成！PPT 已保存：{pptx_path}")


if __name__ == "__main__":
    main()
