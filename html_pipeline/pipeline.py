import json
import re
import sys
from pathlib import Path

# 添加项目根目录到 path 以导入共享模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_client import AIClient
from config import OUTPUT_DIR
from pipeline import (
    step1_outline, step2_content, step3_plan,
    _get_pages, _get_title,
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent
HTML_PROMPT_FILE = PROMPTS_DIR / "html-ppt优化提示词.md"

HTML_SYSTEM = """你是顶级 PPT 视觉设计师，负责将结构化素材转化为单页 HTML 演示文稿页面。

核心约束：
1. 输出一个完整的、自包含的 HTML 文件（包含 <style> 内联样式）
2. 页面固定尺寸 1280×720px（16:9），禁止滚动
3. 不使用任何外部 CDN（无 Tailwind、无 Font Awesome、无 Chart.js）
4. 所有样式必须写在 <style> 标签内
5. 字体栈：'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif

布局要求：
- 使用 CSS Grid 或 Flexbox 构建卡片式 Bento Grid 布局
- 卡片必须有圆角（12-16px）、适当内边距（16-24px）、轻微阴影或边框
- 卡片内容使用 flexbox 纵向排列

内容适配（极其重要）：
- 页面整体用 html,body { width:1280px; height:720px; overflow:hidden; margin:0; }
- 页面必须有一个 .slide 容器，设置 width:1280px; height:720px; display:grid; 用 grid 分配空间
- .slide 的 grid-template-rows 禁止使用多个 auto！应使用如 auto 1fr auto 这样的模式，让主要内容区域用 1fr 自适应填充剩余空间
- 页头必须压缩：标题区总高度控制在 110px 内；长标题优先缩小到 30-32px，并限制副标题为 1 行短句
- 主内容区（1fr 部分）必须明确设置 min-height:0，内部卡片区域也必须设置 min-height:0，禁止子项把父容器撑破
- 主要内容区域（1fr 部分）内部再用 grid 或 flexbox 横向排列卡片，卡片高度设 100% 或 1fr 撑满
- 卡片内部用 flexbox 纵向排列，不设固定高度，让内容自然流动，但通过控制内容量保证不超出
- 禁止在卡片上使用 overflow:hidden 裁切文字！所有文字必须完整可见
- 如果内容放不下 720px，必须主动精简内容（减少 bullet、缩短文案、合并信息），而不是靠 CSS 裁切或让页面撑高
- 底部 footer 区域最多只放 1 张总结卡，禁止再拆成左右 2 张卡，避免与主内容区挤压
- 主内容区如果已经有 3 个以上卡片，底部总结卡高度必须控制在 84-96px 内，内边距同步减小
- 左右分栏布局中，左侧每张卡片正文最多 2 行 + 最多 3 个 tag；右侧主卡如果已有价格/指标模块，就不要再放太长说明文字
- 中间“步骤/路径”类卡片最多 3 步；每步正文必须控制在 1-2 行内，数字块不宜过大
- 右侧“指标/时间/结论”类卡片中，只保留 1 个大数字或 1 个日期模块 + 1 段说明 + 最多 3 个标签，禁止再叠加第二层总结大段文字
- 禁止底部卡片与主内容卡片在视觉上发生覆盖、贴边或重叠；主内容区与 footer 之间至少保留 16px 间距
- 设计前先估算：1280×720 页面扣除标题和页脚后，主内容区大约 500-540px 高，3 列布局时每列内容必须按这个高度预算压缩
- 数字强调用大号字体但控制在一行，配合简短说明文字

视觉层级：
- 页面标题：28-36px，粗体
- 卡片标题：20-24px，粗体
- 正文：14-16px，常规
- 注释/标签：12-13px
- 数字强调：30-40px，超粗体，使用主色
- 标签/胶囊：圆角背景色块，12-13px 粗体

配色系统：
- 根据受众自动选择主题：
  - 企业/管理层/政务/ToB → 浅色主题：白色背景 #F7F8FA，卡片 #FFFFFF，正文 #1F2937
  - 学生/高校/年轻群体 → 暗黑主题：背景 #000000，卡片 #1a1a1a，正文 #E5E7EB
  - 通用/销售 → 浅色主题
- 1 个主色（根据内容自动选择）+ 1-2 个辅助色 + 中性灰

输出格式：
- 直接输出完整 HTML 代码，以 <!DOCTYPE html> 开头
- 不要输出任何解释、注释或 markdown 包裹"""


def extract_html(text: str) -> str:
    """从 AI 输出中提取 HTML 代码。"""
    match = re.search(r'<!DOCTYPE html>.*?</html>', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0)
    match = re.search(r'<html.*?</html>', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0)
    return text


def _infer_page_role(index: int, total_pages: int, title: str, plan: str, material: str) -> str:
    text = f"{title}\n{plan}\n{material}".lower()
    if any(keyword in text for keyword in ["脉络", "发展史", "演变", "阶段", "timeline", "历史"]):
        return "timeline"
    if index == 1 or any(keyword in text for keyword in ["封面", "cover"]):
        return "cover"
    if index == total_pages or any(keyword in text for keyword in ["总结", "结论", "展望", "thanks", "thank", "ending"]):
        return "ending"
    if any(keyword in text for keyword in ["目录", "agenda", "toc"]):
        return "toc"
    if any(keyword in text for keyword in ["总结", "结论", "判断", "建议", "表达", "路线", "路径"]):
        return "summary"
    return "content"


def _build_role_guidance(page_role: str) -> str:
    common = "- 页眉与页脚属于框架区，优先保证稳定；主要变化只能发生在中间内容区\n"
    if page_role == "cover":
        return common + """- 当前页是封面页：优先单焦点布局，不要堆太多卡片
- 标题可以更强，但正文必须极少
- footer 如非必要可以弱化或不单独成卡"""
    if page_role == "toc":
        return common + """- 当前页是目录页：以清晰分组和节奏感为主
- 不要使用复杂三栏对比；优先 1 个主卡 + 2-4 个简洁目录项"""
    if page_role == "summary":
        return common + """- 当前页是总结/判断页：优先两栏或“上主下结论”结构，不要用拥挤三栏
- footer 必须是薄条总结区，不能与主内容区抢高度
- 中间步骤/路径类模块最多 2-3 步
- 右侧结论区只能保留 1 个指标/日期模块 + 1 段说明，禁止再叠加第二个总结块"""
    if page_role == "timeline":
        return common + """- 当前页是发展脉络/时间线页：优先 4 个以内阶段节点，不要堆 5 个以上密集时间点
- 如果既有时间线又有右侧指标卡，优先减少节点数量、缩短节点文案、压缩右侧卡片层级
- 时间线节点每个只保留：阶段名 + 时间 + 1 句说明
- 右侧辅助区最多保留 2 个指标块或 1 个指标块 + 1 个总结块，不要再叠加多层信息"""
    if page_role == "ending":
        return common + """- 当前页是结尾页：强调收束感，不要铺满信息
- 优先单结论或双区块结构，避免复杂卡片矩阵
- footer 只做轻量收尾，不要厚重"""
    return common + """- 当前页是内容页：根据内容密度决定 2 栏还是 3 栏
- 当存在步骤、日期、指标、总结同时出现时，优先降为 2 栏，避免 footer 被挤压"""


def step4_html(client: AIClient, title: str, material: str,
               plan: str, audience: str, page_role: str,
               layout_feedback: str = "") -> str:
    """生成单页 HTML 演示文稿。"""
    role_guidance = _build_role_guidance(page_role)
    feedback_block = ""
    if layout_feedback:
        feedback_block = f"""

上一次生成结果的真实布局问题（来自浏览器检测）：
{layout_feedback}

请严格修正以上问题，并使用更保守的结构：
- 优先减少模块数量，而不是只缩小字号
- 优先把 3 栏降为 2 栏或“上主下辅”结构
- 如果是时间线/发展脉络页，优先减少节点数量到 4 个以内，并压缩右侧辅助区
- 保持主题和视觉风格不变，但必须先保证框架稳定、footer 安全、主内容区不重叠"""

    user = f"""请将以下内容转化为单页 HTML 演示文稿页面：
页面标题：{title}
核心素材：{material}
布局规划：{plan}
目标受众：{audience}
页面角色：{page_role}

页面角色与结构指导：
{role_guidance}{feedback_block}

生成约束：
- 页面固定 1280×720px，html 和 body 设置 width:1280px; height:720px; overflow:hidden; margin:0;
- 视觉风格根据目标受众决定：企业/管理层/政务 → 浅色稳重；学生/年轻群体 → 暗黑酷炫
- 使用 CSS Grid 或 Flexbox 构建卡片式布局
- 标题区总高度控制在 110px 内；长标题优先缩小字号，副标题压缩成 1 行短句
- 主内容区必须设置 min-height:0；如果使用 grid/flex，子容器也必须设置 min-height:0，避免把 footer 顶上去
- 页脚/总结区视为固定框架的一部分，优先固定，再让主内容区适配剩余空间
- 禁止在卡片上使用 overflow:hidden！所有文字必须完整可见，不能被 CSS 裁切截断
- 如果内容太多放不下，主动精简内容（减少 bullet、缩短文案、减少步骤、减少卡片），而不是用 CSS 隐藏
- footer 只能有 1 张总结卡，不要生成左右并排 2 张 footer-card
- 如果主内容区已经有 3 张以上卡片，底部总结区必须明显变薄，控制在 84-96px 左右，内边距同步减小
- 左侧单张卡片正文控制在 2 行以内，tag 最多 3 个；右侧主推卡重点突出 1 个价格模块 + 1 段说明，不要堆太多文字
- 中间“步骤/路径”类卡片最多 3 步，每步正文控制在 1-2 行
- 右侧“指标/时间/结论”类卡片中，只保留 1 个日期或数字模块 + 1 段说明 + 最多 3 个标签，不要再额外放一大段总结
- 主内容卡片与 footer 之间必须留出清晰空隙，绝不能视觉重叠
- 卡片使用圆角、内边距、轻微边框或阴影
- 标签/胶囊控制在 4-8 个中文字符
- 直接输出完整 HTML 代码"""

    raw = client.chat(HTML_SYSTEM, user, temperature=0.4)
    return extract_html(raw)


def run_pipeline(topic: str, audience: str = "通用受众",
                 page_req: str = "12-15页", provider: str | None = None,
                 research: str = "") -> Path:
    """运行 HTML 版本的 PPT 生成 pipeline。"""
    client = AIClient(provider)
    out = Path(OUTPUT_DIR) / topic.replace(" ", "_")
    out.mkdir(parents=True, exist_ok=True)

    print("[1/4] 生成大纲...")
    outline = step1_outline(client, topic, audience, page_req, research)
    (out / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[2/4] 扩写内容...")
    contents = step2_content(client, outline)
    (out / "contents.json").write_text(
        json.dumps(contents, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[3/4] 生成策划稿 + HTML...")
    html_dir = out / "html"
    html_dir.mkdir(exist_ok=True)
    for old_html in html_dir.glob("*.html"):
        old_html.unlink()
    from html_pipeline.html_builder import render_html_with_validation
    all_pages = _get_pages(outline)
    total_pages = len(all_pages)
    idx = 1
    for page in all_pages:
        title = _get_title(page)
        material = contents.get(title, "")
        plan = step3_plan(client, title, material)
        page_role = _infer_page_role(idx, total_pages, title, plan, material)
        html_path = html_dir / f"{idx:02d}_{title[:20]}.html"

        html = step4_html(client, title, material, plan, audience, page_role)
        html_path.write_text(html, encoding="utf-8")

        _, report = render_html_with_validation(html_path)
        if report["compact_applied"]:
            print(f"    [检查] {html_path.name} 轻微超限，截图前可通过紧凑模式修正")

        if report["status"] == "regenerate":
            issue_lines = report["final_issues"] or report["initial_issues"]
            issue_text = "\n".join(f"- {line}" for line in issue_lines[:8])
            print(f"    [检查] {html_path.name} 存在结构性布局问题，执行一次重生成...")
            html = step4_html(client, title, material, plan, audience, page_role, layout_feedback=issue_text)
            html_path.write_text(html, encoding="utf-8")
            _, report = render_html_with_validation(html_path)
            if report["compact_applied"]:
                print(f"    [检查] {html_path.name} 重生成后仍需紧凑模式辅助")
            if report["final_issues"]:
                print(f"    [检查] {html_path.name} 重生成后仍有 {len(report['final_issues'])} 个问题，使用当前最优版本继续")
            else:
                print(f"    [检查] {html_path.name} 重生成后通过布局检查")

        idx += 1

    print("[4/4] 合成 PPT...")
    from html_pipeline.html_builder import build_pptx
    pptx_path = out / f"{topic[:30]}.pptx"
    build_pptx(html_dir, pptx_path)
    print(f"完成！PPT 已保存：{pptx_path}")
    return out
