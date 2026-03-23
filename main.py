import argparse
import os
import sys
from pipeline import run_pipeline
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="PPT Agent - AI 驱动的 PPT 生成工具"
    )
    parser.add_argument("--topic", "-t", default=None, help="PPT 主题（默认读取 .env DEFAULT_TOPIC）")
    parser.add_argument("--audience", "-a", default=None, help="目标受众（默认读取 .env DEFAULT_AUDIENCE）")
    parser.add_argument("--pages", "-p", default=None, help="页数要求（默认读取 .env DEFAULT_PAGES）")
    parser.add_argument(
        "--provider", "-m",
        choices=["openai", "claude", "domestic"],
        default=None,
        help="AI 接口 (默认读取 .env DEFAULT_PROVIDER)",
    )
    parser.add_argument("--research", "-r", default="", help="补充调研信息（可选）")
    args = parser.parse_args()
    topic = args.topic or os.getenv("DEFAULT_TOPIC")
    audience = args.audience or os.getenv("DEFAULT_AUDIENCE", "通用受众")
    pages = args.pages or os.getenv("DEFAULT_PAGES", "12-15页")

    if not topic:
        print("[错误] 未提供 PPT 主题。请通过 --topic 传入或在 .env 中设置 DEFAULT_TOPIC。", file=sys.stderr)
        sys.exit(1)

    print(f"主题：{topic}")
    print(f"受众：{audience}")
    print(f"页数：{pages}")
    print(f"模型：{os.getenv('OPENAI_MODEL', 'gpt-4o')}")
    print("-" * 40)

    try:
        out = run_pipeline(
            topic=topic,
            audience=audience,
            page_req=pages,
            provider=args.provider,
            research=args.research,
        )
        print(f"\n喵~任务完成，SVG 文件已保存至：{out}/svg/")
    except Exception as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
