# PPT-AGENT

一个基于 LLM 的 PPT 自动生成工具，支持两种输出链路：

- **SVG Pipeline**：AI 生成 SVG 页面，再转为 PPT
- **HTML Pipeline**：AI 生成单页 HTML 页面，再截图导出 PPT（当前推荐）

## 特性

- 自动生成 PPT 大纲
- 自动扩写每页内容
- 自动生成单页视觉稿
- 输出 `.pptx` 文件
- 支持 OpenAI 兼容接口
- 支持 HTML 卡片化排版，显著减少文本溢出问题

---

## 项目结构

```bash
PPT-AGENT/
├── main.py                    # SVG pipeline 入口
├── pipeline.py                # SVG pipeline 核心
├── svg_checker.py             # SVG 文本问题检测器
├── pptx_builder.py            # SVG → PNG → PPTX
├── html_pipeline/
│   ├── main.py                # HTML pipeline 入口
│   ├── pipeline.py            # HTML pipeline 核心
│   └── html_builder.py        # HTML → PNG → PPTX
├── ai_client.py               # LLM 客户端封装
├── config.py                  # 配置读取
├── check_api.py               # API 连通性测试
├── 顶级架构师.md              # 大纲生成 prompt
├── 顶级设计师.md              # SVG 设计 prompt
├── html-ppt优化提示词.md      # HTML 设计 prompt 参考
├── .env.example               # 环境变量示例
└── requirements.txt
```

---

## 安装

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd PPT-AGENT
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

---

## 配置

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

最少需要配置：

```env
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5.4
OPENAI_REASONING_EFFORT=high
DEFAULT_PROVIDER=openai
DEFAULT_TOPIC=红茶与绿茶的区别
DEFAULT_AUDIENCE=销售团队
DEFAULT_PAGES=3-5页
OUTPUT_DIR=./output
```

### `OPENAI_REASONING_EFFORT` 可选值

```env
minimal
low
medium
high
```

### `DEFAULT_TOPIC` 用法

如果你在 `.env` 中配置了：

```env
DEFAULT_TOPIC=红茶与绿茶的区别
```

那么运行时可以不传 `-t`：

```bash
python main.py
python -m html_pipeline.main
```

命令行如果显式传了 `-t`，会优先使用命令行主题。

---

## 使用说明

## 1) 测试接口

```bash
python check_api.py
```

或者只测 responses：

```bash
python check_api.py --mode responses
```

如果成功会看到：

```bash
[PASS] chat
[PASS] responses
```

---

## 2) 使用 SVG pipeline

适合：保留 SVG 设计稿链路。

```bash
python main.py -t "主题"
```

示例：

```bash
python main.py -t "红茶与绿茶的区别"
```

输出：

```bash
output/红茶与绿茶的区别/
├── outline.json
├── contents.json
├── svg/
└── 红茶与绿茶的区别.pptx
```

---

## 3) 使用 HTML pipeline（推荐）

适合：更稳定的页面排版，减少文字溢出。

```bash
python -m html_pipeline.main -t "主题"
```

示例：

```bash
python -m html_pipeline.main -t "红茶与绿茶的区别"
```

输出：

```bash
output/红茶与绿茶的区别/
├── outline.json
├── contents.json
├── html/
└── 红茶与绿茶的区别.pptx
```

---

## 可选参数

SVG 和 HTML 两条命令都支持：

```bash
--topic / -t       主题
--audience / -a    目标受众
--pages / -p       页数要求
--provider / -m    openai / claude / domestic
--research / -r    补充调研信息
```

示例：

```bash
python -m html_pipeline.main \
  -t "红茶与绿茶的区别" \
  -a "销售团队" \
  -p "3-5页" \
  -m openai \
  -r "重点突出工艺、口感、适饮场景和推荐逻辑"
```

---

## Audience 与风格

HTML pipeline 会根据 `audience` 调整视觉风格：

- `企业管理层 / 政务 / ToB` → 浅色、稳重
- `学生/教育 / 年轻群体` → 更轻快或暗黑
- `销售团队 / 通用受众` → 默认浅色商务风格

如果命令行不传 `--audience`，会读取 `.env` 里的：

```env
DEFAULT_AUDIENCE=销售团队
```

---

## 已知限制

### SVG pipeline
- 文本布局依赖 SVG 坐标，复杂页面容易出现溢出或重叠
- 已内置 `svg_checker.py` 做检测，但不能完全根治

### HTML pipeline
- 最终导出的 PPT 页面本质是截图图片，不是原生可编辑形状
- 但排版稳定性更好，当前更推荐使用

---

## 典型工作流

### 推荐顺序

1. 配好 `.env`
2. 运行接口测试：
   ```bash
   python check_api.py
   ```
3. 先用 HTML pipeline 生成：
   ```bash
   python -m html_pipeline.main -t "你的主题"
   ```
4. 打开 `output/.../*.pptx` 查看效果

---

## 依赖

```txt
openai>=1.0.0
python-dotenv>=1.0.0
rich>=13.0.0
python-pptx>=1.0.0
playwright>=1.40.0
```

---

## License

---