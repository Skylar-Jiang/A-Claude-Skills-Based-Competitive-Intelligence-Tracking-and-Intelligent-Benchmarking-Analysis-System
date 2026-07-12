"""Conversation memory and webpage crawler workflow.

Run Memory + crawler demo:
    python -m modules.conversation_crawler --mock
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


SAMPLE_FRESH_PRICE_HTML = """
<html>
  <head><title>生鲜批发价格公开样例</title></head>
  <body>
    <h1>生鲜批发价格公开样例</h1>
    <p>本样例用于课堂演示公开网页抓取与文本抽取流程。</p>
    <p>山东寿光黄瓜批发价小幅上行，河北黄瓜受降雨影响到货减少，辽宁批发市场黄瓜低价到货。</p>
    <a href="/price/shouguang-cucumber">山东寿光黄瓜价格日报</a>
    <a href="/price/hebei-cucumber">河北黄瓜价格日报</a>
  </body>
</html>
"""


class CompatConversationBufferMemory:
    """Fallback for LangChain 1.x environments without langchain.memory."""

    def __init__(self, memory_key: str = "history", input_key: str = "question", output_key: str = "output"):
        self.memory_key = memory_key
        self.input_key = input_key
        self.output_key = output_key
        self.buffer: list[tuple[str, str]] = []

    def load_memory_variables(self, _: dict[str, Any]) -> dict[str, str]:
        history = "\n".join(f"Human: {question}\nAI: {answer}" for question, answer in self.buffer)
        return {self.memory_key: history}

    def save_context(self, inputs: dict[str, str], outputs: dict[str, str]) -> None:
        self.buffer.append((inputs.get(self.input_key, ""), outputs.get(self.output_key, "")))


def create_conversation_buffer_memory():
    try:
        from langchain.memory import ConversationBufferMemory

        print("Memory 来源：langchain.memory.ConversationBufferMemory")
        return ConversationBufferMemory(memory_key="history", input_key="question", output_key="output")
    except ModuleNotFoundError:
        print("Memory 来源：兼容实现（当前 LangChain 1.x 已移除 langchain.memory）")
        return CompatConversationBufferMemory(memory_key="history", input_key="question", output_key="output")


def extract_webpage_text(html: str, source_url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else source_url
    link_titles = []
    for link in soup.find_all("a", href=True)[:10]:
        text = link.get_text(" ", strip=True)
        if text:
            link_titles.append(f"{text} ({urljoin(source_url, link['href'])})")

    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    if link_titles:
        text = f"{text}\n新闻/链接标题：\n" + "\n".join(link_titles)
    return {"title": title, "text": text[:5000], "source_url": source_url}


def fetch_webpage_text(url: str) -> dict[str, str]:
    response = requests.get(
        url,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()
    return extract_webpage_text(response.text, source_url=url)


def fetch_webpage_html(url: str) -> str:
    response = requests.get(
        url,
        timeout=12,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return response.text


def crawl_public_webpage(url: str, fetcher=None, allow_fallback: bool = False) -> dict[str, Any]:
    fetch_html = fetcher or fetch_webpage_html
    try:
        html = fetch_html(url)
        page = extract_webpage_text(html, source_url=url)
        page["used_fallback"] = False
        page["error"] = ""
        return page
    except Exception as exc:
        if not allow_fallback:
            raise
        page = extract_webpage_text(SAMPLE_FRESH_PRICE_HTML, source_url=url)
        page["used_fallback"] = True
        page["error"] = str(exc)
        page["crawl_status"] = "success_with_local_sample"
        return page


def write_crawl_result(page: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    markdown_path = output_path / "public_web_crawl_result.md"
    csv_path = output_path / "public_web_crawl_result.csv"

    text = str(page.get("text", ""))
    markdown_path.write_text(
        "\n".join(
            [
                "# 第三天公开网页爬虫结果",
                "",
                f"- 标题：{page.get('title', '')}",
                f"- 来源：{page.get('source_url', '')}",
                f"- 抽取状态：成功",
                f"- 课堂演示数据来源：{'本地公开样例' if page.get('used_fallback', False) else '目标网页'}",
                f"- 备注：{('目标网页暂不可访问，已使用本地公开样例完成解析' if page.get('used_fallback', False) else '目标网页抓取成功')}",
                "",
                "## 抽取文本",
                "",
                text[:2000],
                "",
            ]
        ),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["title", "source_url", "status", "demo_source", "text"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "title": page.get("title", ""),
                "source_url": page.get("source_url", ""),
                "status": "success",
                "demo_source": "local_sample" if page.get("used_fallback", False) else "target_webpage",
                "text": text[:2000],
            }
        )
    return {"markdown": markdown_path, "csv": csv_path}


def build_memory_llm(mock: bool):
    if mock:
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        return FakeListChatModel(
            responses=[
                "我已抓取并总结网页内容：山东寿光黄瓜批发价小幅上行，建议继续跟踪河北黄瓜和辽宁批发市场黄瓜的区域价差。",
                "根据上一轮记忆，你刚才关注的是寿光黄瓜行情；本轮重点应补充河北降雨影响、辽宁低价到货和质量监管风险做对比。",
            ]
        )

    from langchain_openai import ChatOpenAI

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("请先在 .env 中配置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY，或使用 --mock。")

    return ChatOpenAI(
        model=os.getenv("MODEL_ANALYSIS", "deepseek-chat"),
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        temperature=float(os.getenv("MODEL_TEMPERATURE", "0.0")),
    )


def answer_with_memory(question: str, web_context: str, memory, chain) -> str:
    memory_vars = memory.load_memory_variables({})
    answer = chain.invoke(
        {
            "history": memory_vars.get("history", ""),
            "web_context": web_context,
            "question": question,
        }
    )
    memory.save_context({"question": question}, {"output": answer})
    return answer


def run_memory_crawler(url: str, mock: bool = False, page: dict[str, Any] | None = None) -> list[str]:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import PromptTemplate

    memory = create_conversation_buffer_memory()
    llm = build_memory_llm(mock)
    prompt = PromptTemplate(
        input_variables=["history", "web_context", "question"],
        template=(
            "你是生鲜批发采购区域供应源竞品情报助手。\n"
            "历史对话：\n{history}\n\n"
            "网页抓取内容：\n{web_context}\n\n"
            "用户问题：{question}\n"
            "请结合网页内容和历史对话回答，无法判断时说明需要补充证据。"
        ),
    )
    chain = prompt | llm | StrOutputParser()

    if page is None and mock:
        page = {
            "title": "Mock 生鲜批发价格新闻",
            "text": "山东寿光黄瓜批发价小幅上行，河北黄瓜受降雨影响到货减少，辽宁批发市场黄瓜低价到货。",
            "source_url": url,
        }
    elif page is None:
        page = crawl_public_webpage(url)

    web_context = f"标题：{page['title']}\n来源：{page['source_url']}\n正文：{page['text']}"
    return [
        answer_with_memory("帮我抓取并总结这个竞品网页的新闻标题和核心内容。", web_context, memory, chain),
        answer_with_memory("总结上次讨论的要点，并说明下一步要对比什么。", "", memory, chain),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="多轮对话与网页抓取：ConversationBufferMemory + BeautifulSoup")
    parser.add_argument("--mock", action="store_true", help="不请求真实网页和真实 API")
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--save-result", action="store_true", help="保存公开网页爬虫抽取结果")
    parser.add_argument(
        "--output-dir",
        default="daily-tasks/每日任务/day3/crawler-results",
        help="爬虫结果输出目录",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    page = crawl_public_webpage(args.url) if args.save_result else None
    if args.save_result and page is not None:
        paths = write_crawl_result(page, args.output_dir)
        print(f"爬虫结果 Markdown：{paths['markdown']}")
        print(f"爬虫结果 CSV：{paths['csv']}")
        if page.get("used_fallback"):
            print("目标网页暂不可访问，已使用本地公开样例完成课堂爬虫解析。")
    outputs = run_memory_crawler(args.url, mock=args.mock, page=page)
    for index, output in enumerate(outputs, start=1):
        print(f"\n=== 第 {index} 轮对话 ===")
        print(output)


if __name__ == "__main__":
    main()
