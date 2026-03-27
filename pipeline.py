import json
import re
from pathlib import Path
from ai_client import AIClient
from config import OUTPUT_DIR
from svg_checker import check_svg, format_issues


PROMPTS_DIR = Path(__file__).resolve().parent
OUTLINE_PROMPT_FILE = PROMPTS_DIR / "顶级架构师.md"
SVG_PROMPT_FILE = PROMPTS_DIR / "顶级设计师.md"

CONTENT_SYSTEM = """你是企业级 AI 平台研究员，负责为 PPT 页面输出可直接上页的结论型素材。

你的任务不是罗列搜索结果，而是基于联网检索结果，提炼与当前页面标题强相关的 3-5 条 PPT 要点。

强约束：
1. 必须紧扣页面标题，除非标题明确要求，否则不要展开讲其他平台
2. 每条必须是可直接放进 PPT 的短 bullet，控制在 30-45 字
3. 优先输出结论、能力判断、数据事实、案例结果，不写检索过程
4. 禁止输出 URL、参考文献、脚注编号、来源列表、括号里的长链接
5. 优先使用 2024-2026 的公开事实；不确定就不要编造
6. 最终只输出 3-5 条分点，不要写引言、总结、说明"""

PLAN_SYSTEM = """你是PPT策划稿设计师，负责规划页面布局和元素类型。
输出核心观点、布局规划和元素建议，简洁明确。"""


def load_outline_prompt(page_req: str) -> str:
    template = OUTLINE_PROMPT_FILE.read_text(encoding="utf-8")
    return template.replace("{{PAGE_REQUIREMENTS}}", page_req)


def load_svg_prompt() -> str:
    return SVG_PROMPT_FILE.read_text(encoding="utf-8")


def extract_outline(text: str) -> dict:
    match = re.search(r'\[PPT_OUTLINE\](.*?)\[/PPT_OUTLINE\]', text, re.DOTALL)
    if match:
        return json.loads(match.group(1).strip())
    # 模型未加标签，直接尝试解析 JSON
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))
    raise ValueError("无法从模型输出中提取大纲 JSON")


def extract_svg(text: str) -> str:
    match = re.search(r'<svg.*?</svg>', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0)
    return text


def step1_outline(client: AIClient, topic: str, audience: str,
                  page_req: str, research: str = "") -> dict:
    instructions = load_outline_prompt(page_req)
    user = f"""PPT主题：{topic}
目标受众：{audience}
页数要求：{page_req}
调研信息：{research or '暂无，请根据主题合理规划'}

请生成完整PPT大纲，严格遵循JSON格式。"""
    if client.provider == "openai":
        raw = client.responses(instructions, user)
    else:
        raw = client.chat(instructions, user, temperature=0.6)
    return extract_outline(raw)


def _get_pages(outline: dict) -> list:
    """兼容两种大纲结构：扁平 pages[] 或 ppt_outline 的 cover/toc/parts/end_page。"""
    if "pages" in outline:
        return outline["pages"]
    inner = outline.get("ppt_outline", outline)
    pages = []
    for key in ("cover", "table_of_contents"):
        page = inner.get(key)
        if page:
            pages.append(page)
    for part in inner.get("parts", []):
        pages.extend(part.get("pages", []))
    end_page = inner.get("end_page")
    if end_page:
        pages.append(end_page)
    return pages


def _get_title(page: dict) -> str:
    return page.get("title") or page.get("page_title", f"第{page.get('page','')}页")


def _fallback_page_content(title: str, hint: str) -> str:
    base_points = [
        f"- 围绕“{title}”先给出最核心定义，再说明它为什么重要。",
        f"- 结合页面主题，提炼 2-3 个最直接的判断或事实，不展开冗长背景。",
        f"- 如果涉及时间、用途、差异或价值，只保留最关键的一层信息。",
    ]
    if hint:
        base_points.append(f"- 参考要点：{hint[:60]}{'…' if len(hint) > 60 else ''}")
    return "\n".join(base_points[:4])


def step2_content(client: AIClient, outline: dict) -> dict:
    pages = _get_pages(outline)
    contents = {}
    for page in pages:
        title = _get_title(page)
        sections = page.get("sections") or page.get("content") or []
        hint = "\n".join(str(s) for s in sections) if sections else ""
        user = f"""页面标题：{title}
页面参考要点：{hint or '无'}

请联网检索后输出适合 PPT 正文的内容，要求：
- 只保留与该页面标题直接相关的信息
- 输出 3-5 条短 bullet
- 每条控制在 30-45 字
- 尽量包含明确数据、能力事实、发布时间点或可验证结论
- 禁止输出网址、来源、脚注编号、参考文献
- 禁止使用“据报道”“有观点认为”“可能”“或许”等模糊表述
- 如果检索结果不足，就输出更稳妥的能力结论，不要硬编

直接输出分点列表。"""
        try:
            if client.provider == "openai":
                tools = [{"type": "web_search", "search_context_size": "high"}]
                contents[title] = client.responses(
                    CONTENT_SYSTEM,
                    user,
                    reasoning_effort="low",
                    tools=tools,
                )
            else:
                contents[title] = client.chat(CONTENT_SYSTEM, user, temperature=0.5)
        except Exception as exc:
            print(f"    [降级] 页面《{title}》联网扩写失败，改用保守内容生成：{exc}")
            fallback_user = f"""页面标题：{title}
页面参考要点：{hint or '无'}

请不要联网，直接基于标题与参考要点，输出适合 PPT 的 2-3 条保守短 bullet。
要求：
- 不要编造具体年份、数据、机构
- 优先输出定义、用途、判断逻辑、常见差异
- 每条控制在 22-35 字
- 只输出分点列表"""
            try:
                contents[title] = client.chat(CONTENT_SYSTEM, fallback_user, temperature=0.3)
            except Exception:
                contents[title] = _fallback_page_content(title, hint)
    return contents


def step3_plan(client: AIClient, title: str, material: str) -> str:
    user = f"""页面标题：{title}
素材内容：{material}
请输出：1.核心观点 2.布局规划 3.元素建议"""
    return client.chat(PLAN_SYSTEM, user, temperature=0.6)


def step4_svg(client: AIClient, title: str, material: str, plan: str, audience: str) -> str:
    user = f"""请将以下内容转化为专业SVG演示文稿页面：
页面标题：{title}
核心素材：{material}
布局规划：{plan}
目标受众：{audience}

生成约束：
- 最终视觉风格必须根据目标受众决定；如果受众偏企业、管理层、政务或 ToB，则更稳重克制；如果受众偏高校、学生或年轻群体，则可以更轻快，但仍需专业。
- 所有文本必须严格落在画布与卡片安全边界内，不能越出卡片、贴边、裁切或压到装饰元素上。
- 垂直方向同样重要：多行 tspan 堆叠后的总高度不得超出所属卡片的底边；放置文本前先计算 y + 行数×dy 是否超过卡片 y+height-16，超过时必须减少行数、缩小 dy 或增大卡片高度。
- 标题、副标题、注释等不同文本块之间必须保留足够的 y 间距，避免上下文字区域重叠。标题 dy 不得小于 font-size 的 1.2 倍。
- 页面标题与卡片标题如偏长，必须自动拆为 2 行内；正文不得出现明显超宽单行。
- 长正文优先拆成 2-3 行，多行文本优先使用 <tspan> 排版，不要把长句直接塞进单行 <text>。
- 如果内容过长，优先减少 bullet 数量、合并相近信息、减少卡片数量或提炼结论，不要靠无限缩小字号硬塞。
- 标签、胶囊、页脚说明、注释文字使用更保守的长度控制，避免出现超长单行。
- 标签与胶囊只能承载非常短的分类词、状态词或关键词；单个标签优先控制在 4-8 个中文字符或 1-3 个英文词内。
- 同一区域不要堆太多小标签；若标签过多、过长或显得杂乱，优先删减，只保留 2-4 个最关键标签，或改成普通正文。
- 不要把转折句、结论句、流程说明句塞进胶囊；这类内容应改用普通文本或分组标题表达。
- 时间信息优先拆成”时间小标签 + 普通说明文字”，不要把时间和整句说明做成同一个长胶囊。
- 阶段名称、能力环节、流程节点优先使用简洁中文短词，除非英文术语本身不可替换。
- 底部流程、对比链、闭环示意优先保留 3-4 个核心节点；如果节点过多会显得拥挤，应主动删减。
- 页脚说明默认拆成 2 行内，优先使用 <tspan> 换行，不要把整段补充说明压成一整条长句。
- 请使用更丰富但专业的配色，并明确区分标题、正文、说明、标签、数字的颜色层级。
- 卡片需要有统一的圆角、描边、阴影和内边距系统，确保页面层次清晰且风格一致。"""
    raw = client.chat(load_svg_prompt(), user, temperature=0.4)
    svg = extract_svg(raw)

    # 检查文本溢出
    issues = check_svg(svg)
    if not issues:
        return svg

    # 有溢出，尝试让 AI 修复一次
    fix_prompt = format_issues(issues)
    n_h = sum(1 for i in issues if i["direction"] == "horizontal")
    n_v = sum(1 for i in issues if i["direction"] == "vertical")
    n_o = sum(1 for i in issues if i["direction"] == "overlap")
    desc = "、".join(filter(None, [
        f"水平溢出{n_h}处" if n_h else "",
        f"垂直溢出{n_v}处" if n_v else "",
        f"文本重叠{n_o}处" if n_o else "",
    ]))
    print(f"    [检查] 检测到 {desc}，正在修复...")
    fix_user = f"""以下是一份已生成的 SVG 演示文稿页面，但存在排版问题（可能包括：文本水平超出卡片宽度、文本垂直超出卡片底边、文本之间区域重叠）。
请在保持整体设计不变的前提下，只修复问题部分，输出完整的修复后 SVG 代码。

原始 SVG：
{svg}

{fix_prompt}"""
    fix_raw = client.chat(load_svg_prompt(), fix_user, temperature=0.3)
    fixed_svg = extract_svg(fix_raw)

    # 再次检查，若仍有问题再修一轮
    remaining = check_svg(fixed_svg)
    if not remaining:
        print("    [检查] 修复完成，所有排版问题已解决")
        return fixed_svg

    # 第二轮修复
    fix_prompt2 = format_issues(remaining)
    print(f"    [检查] 第一轮修复后仍有 {len(remaining)} 处问题，进行第二轮修复...")
    fix_user2 = f"""以下 SVG 仍存在排版问题，请继续修复。注意：这是第二轮修复，请更大胆地调整布局（如增大卡片高度、拉开文本间距、缩短文案）来彻底解决问题。

原始 SVG：
{fixed_svg}

{fix_prompt2}"""
    fix_raw2 = client.chat(load_svg_prompt(), fix_user2, temperature=0.3)
    fixed_svg2 = extract_svg(fix_raw2)

    remaining2 = check_svg(fixed_svg2)
    if remaining2:
        print(f"    [检查] 第二轮修复后仍有 {len(remaining2)} 处问题，使用当前版本继续")
    else:
        print("    [检查] 第二轮修复完成，所有排版问题已解决")
    return fixed_svg2


def run_pipeline(topic: str, audience: str = "通用受众",
                 page_req: str = "12-15页", provider: str | None = None,
                 research: str = "") -> Path:
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

    print("[3/4] 生成策划稿 + SVG...")
    svg_dir = out / "svg"
    svg_dir.mkdir(exist_ok=True)
    all_pages = _get_pages(outline)
    idx = 1
    for page in all_pages:
        title = _get_title(page)
        material = contents.get(title, "")
        plan = step3_plan(client, title, material)
        svg = step4_svg(client, title, material, plan, audience)
        (svg_dir / f"{idx:02d}_{title[:20]}.svg").write_text(
            svg, encoding="utf-8")
        idx += 1

    print("[4/4] 合成 PPT...")
    from pptx_builder import build_pptx
    pptx_path = out / f"{topic[:30]}.pptx"
    build_pptx(svg_dir, pptx_path)
    print(f"完成！PPT 已保存：{pptx_path}")
    return out
