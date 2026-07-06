import os

from dotenv import load_dotenv
from openai import OpenAI


def test_openai_compatible():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("未填写 OPENAI_API_KEY，跳过真实API调用。")
        return

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
    )
    response = client.chat.completions.create(
        model=os.getenv("MODEL_FAST", "deepseek-v4-flash"),
        messages=[{"role": "user", "content": "简单介绍竞品情报分析的作用"}],
        temperature=float(os.getenv("MODEL_TEMPERATURE", "0.0")),
        max_tokens=512,
    )
    print("API调用成功：", response.choices[0].message.content)


if __name__ == "__main__":
    load_dotenv()
    test_openai_compatible()
