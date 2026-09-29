"""显式运行的真实服务回归；不会被 unittest discover 自动执行。

使用演示测试身份，只执行沙箱计算、补充信息及合成数据图表，不写 ERP 订单。
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx


BASE_URL = "http://127.0.0.1:18000"
USER_ID = "project-review-20260924"


async def stream_events(client: httpx.AsyncClient, path: str, payload: dict) -> list[dict]:
    """
    读取服务端的真实 SSE 事件，错误事件使验收立即失败。
    """
    events = []
    async with client.stream("POST", path, json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:].strip())
                if event["type"] == "error":
                    raise AssertionError(event.get("message", "SSE error"))
                events.append(event)
    assert any(event["type"] in {"done", "interrupt"} for event in events), events
    return events


async def main() -> None:
    """
    检查静态资源、归属校验、上下文、审批恢复和异步图表实际交付。
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=300) as client:
        index = await client.get("/")
        index.raise_for_status()
        asset = re.search(r'src="([^\"]+\.js)"', index.text)
        assert asset, "首页未包含构建脚本"
        (await client.get(asset.group(1))).raise_for_status()
        print("PASS built frontend asset", flush=True)

        session = await client.post("/history", params={"user_id": USER_ID})
        session.raise_for_status()
        thread_id = session.json()["thread_id"]
        print(json.dumps({"user_id": USER_ID, "thread_id": thread_id}), flush=True)
        request = {"user_id": USER_ID, "name": "回归测试", "thread_id": thread_id}
        wrong_user = {**request, "user_id": "project-review-other", "message": "请回复测试"}
        denied = await client.post("/chat/stream", json=wrong_user)
        assert denied.status_code == 404, denied.text
        print("PASS foreign thread rejected", flush=True)

        events = await stream_events(client, "/chat/stream", {
            **request, "message": "请从运行时上下文读取当前 user_id，只回复该值，不调用工具。",
        })
        answer = "".join(event.get("content", "") for event in events if event["type"] == "token")
        assert USER_ID in answer, events
        print("PASS runtime identity and SSE", flush=True)

        events = await stream_events(client, "/chat/stream", {
            **request,
            "message": "这是人工中断回归。请立即调用 request_additional_info，information_needed='请输入验收编号'，context='仅测试，不涉及订单写入'。收到补充后只复述验收编号。",
        })
        interrupt = next((event for event in events if event["type"] == "interrupt"), None)
        assert interrupt, events
        history = await client.get(f"/history/{thread_id}/messages", params={"user_id": USER_ID})
        history.raise_for_status()
        assert history.json().get("interrupt"), history.json()
        events = await stream_events(client, f"/chat/{thread_id}/resume", {
            "user_id": USER_ID, "username": "回归测试",
            "resume": {interrupt["interrupt_id"]: {"information": "REVIEW-42"}},
        })
        answer = "".join(event.get("content", "") for event in events if event["type"] == "token")
        assert "REVIEW-42" in answer, events
        print("PASS interrupt persisted and resumed", flush=True)

        events = await stream_events(client, "/chat/stream", {
            **request,
            "message": "这是采购子 Agent 中断恢复验收。请委派 procurement_order 准备采购需求；目前没有供应商、配件和数量，请它调用 request_additional_info 索取缺失信息。不查询或修改 ERP，不创建订单。",
        })
        delegation = next((event for event in events
                           if event["type"] == "tool_start" and event.get("tool_name") == "task"), None)
        interrupt = next((event for event in events if event["type"] == "interrupt"), None)
        assert delegation and interrupt, events
        history = await client.get(f"/history/{thread_id}/messages", params={"user_id": USER_ID})
        history.raise_for_status()
        assert history.json().get("interrupt", {}).get("interrupt_id") == interrupt["interrupt_id"], history.json()
        events = await stream_events(client, f"/chat/{thread_id}/resume", {
            "user_id": USER_ID, "username": "回归测试",
            "resume": {interrupt["interrupt_id"]: {
                "information": "取消本次采购需求收集。这只是中断恢复测试，验收编号 NESTED-42。请结束子任务，不再追问，不查询或修改 ERP，不创建订单。",
            }},
        })
        assert not any(event["type"] == "interrupt" for event in events), events
        assert any(event["type"] == "tool_result" and event.get("tool_call_id") == delegation["tool_call_id"]
                   for event in events), events
        history = (await client.get(f"/history/{thread_id}/messages", params={"user_id": USER_ID})).json()
        assert history.get("interrupt") is None, history
        print("PASS nested subagent interrupt durable, resumed by ID and card completed", flush=True)

        events = await stream_events(client, "/chat/stream", {
            **request,
            "message": "请通过 start_async_task 委派 procurement_analyst，用合成测试数据生成柱状图：A=2、B=5、C=3，标题为项目验收图。不查询或修改 ERP。",
        })
        task_ids = []
        for event in events:
            if event["type"] == "tool_result" and event.get("tool_name") == "start_async_task":
                task_ids += re.findall(
                    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", event.get("text", "")
                )
        assert task_ids, events
        task_id = task_ids[0]
        print(json.dumps({"task_id": task_id}), flush=True)
        events = await stream_events(client, "/chat/stream", {
            **request,
            "message": "请立即调用 list_async_tasks 查询当前异步任务状态，只简短说明查询到的状态。",
        })
        tracked_results = [
            event.get("text", "")
            for event in events
            if event["type"] == "tool_result" and event.get("tool_name") == "list_async_tasks"
        ]
        assert any(task_id in result and "status:" in result for result in tracked_results), events
        print("PASS running async task is visible to main agent", flush=True)
        denied = await client.get(f"/async-tasks/{task_id}", params={"user_id": "project-review-other"})
        assert denied.status_code == 404, denied.text
        for _ in range(90):
            response = await client.get(f"/async-tasks/{task_id}", params={"user_id": USER_ID})
            response.raise_for_status()
            status = response.json()
            if status["done"]:
                assert status["status"] == "success", status
                if status["delivered"]:
                    break
            await asyncio.sleep(2)
        else:
            raise AssertionError("图表任务未在验收时间内交付")
        visualization = status.get("visualization")
        assert visualization and visualization.get("artifact_id"), status
        artifact = await client.get(visualization["src"])
        artifact.raise_for_status()
        assert "text/html" in artifact.headers.get("content-type", ""), artifact.headers
        assert len(artifact.content) > 200, "图表 HTML 缺失"
        assert "sandbox" in artifact.headers.get("content-security-policy", "")
        history = (await client.get(f"/history/{thread_id}/messages", params={"user_id": USER_ID})).json()
        delivered = [message for message in history["messages"] if message.get("async_task_id") == task_id]
        assert any(message.get("visualization") for message in delivered), history
        print(json.dumps({"artifact_id": visualization["artifact_id"], "html_bytes": len(artifact.content)}), flush=True)
        print("PASS async task ownership, delivery, history and real HTML artifact", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
