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
- 主要内容区域（1fr 部分）内部再用 grid 或 flexbox 横向排列卡片，卡片高度设 100% 或 1fr 撑满
- 卡片内部用 flexbox 纵向排列，不设固定高度，让内容自然流动，但通过控制内容量保证不超出
- 禁止在卡片上使用 overflow:hidden 裁切文字！所有文字必须完整可见
- 如果内容放不下 720px，必须主动精简内容（减少 bullet、缩短文案、合并信息），而不是靠 CSS 裁切或让页面撑高
- 底部 footer 区域最多只放 1 张总结卡，禁止再拆成左右 2 张卡，避免与主内容区挤压
- 主内容区如果已经有 3 个以上卡片，底部总结卡高度必须控制在 90-110px 内
- 左右分栏布局中，左侧每张卡片正文最多 2 行 + 最多 3 个 tag；右侧主卡如果已有价格/指标模块，就不要再放太长说明文字
- 禁止底部卡片与主内容卡片在视觉上发生覆盖、贴边或重叠；主内容区与 footer 之间至少保留 14-18px 间距
- 设计前先估算：1280×720 页面扣除标题和页脚后，主内容区大约 500-560px 高，4-6 个卡片，每卡片 3-5 行正文
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


def step4_html(client: AIClient, title: str, material: str,
               plan: str, audience: str) -> str:
    """生成单页 HTML 演示文稿。"""
    user = f"""请将以下内容转化为单页 HTML 演示文稿页面：
页面标题：{title}
核心素材：{material}
布局规划：{plan}
目标受众：{audience}

生成约束：
- 页面固定 1280×720px，html 和 body 设置 width:1280px; height:720px; overflow:hidden; margin:0;
- 视觉风格根据目标受众决定：企业/管理层/政务 → 浅色稳重；学生/年轻群体 → 暗黑酷炫
- 使用 CSS Grid 或 Flexbox 构建卡片式布局
- 禁止在卡片上使用 overflow:hidden！所有文字必须完整可见，不能被 CSS 裁切截断
- 如果内容太多放不下，主动精简内容（减少 bullet、缩短文案），而不是用 CSS 隐藏
- footer 只能有 1 张总结卡，不要生成左右并排 2 张 footer-card
- 如果主内容区已经有 3 张以上卡片，底部总结区必须明显变薄，控制在 90-110px 左右
- 左侧单张卡片正文控制在 2 行以内，tag 最多 3 个；右侧主推卡重点突出 1 个价格模块 + 1 段说明，不要堆太多文字
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
    all_pages = _get_pages(outline)
    idx = 1
    for page in all_pages:
        title = _get_title(page)
        material = contents.get(title, "")
        plan = step3_plan(client, title, material)
        html = step4_html(client, title, material, plan, audience)
        (html_dir / f"{idx:02d}_{title[:20]}.html").write_text(
            html, encoding="utf-8")
        idx += 1

    print("[4/4] 合成 PPT...")
    from html_pipeline.html_builder import build_pptx
    pptx_path = out / f"{topic[:30]}.pptx"
    build_pptx(html_dir, pptx_path)
    print(f"完成！PPT 已保存：{pptx_path}")
    return out
