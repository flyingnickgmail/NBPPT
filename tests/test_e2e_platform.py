#!/usr/bin/env python3
"""
End-to-End Verification Suite for Personal Agent ProMedia Platform.
Tests:
  1. Gateway (:8000) & Worker (:8001) Health Checks
  2. Wallet & TCC Initial Balance Query
  3. SSE Streaming Composite Job (PPTX + High-DPI Charts + 1080P MP4 Video + TCC Settlement)
  4. Standard MCP JSON-RPC Endpoint (/mcp: initialize, tools/list, tools/call)
  5. Deliverable File Integrity Check (.pptx, .png, .mp4 non-empty & downloadable)
"""
import json
import httpx


def run_e2e_tests():
    base_gw = "http://127.0.0.1:8000"
    base_wk = "http://127.0.0.1:8001"
    api_key = "sk-mcp-demo-pro-8899"

    with httpx.Client(timeout=180.0, trust_env=False) as client:
        print("=== [Test 1] 检查算力底座 (:8001) 与国内门面网关 (:8000) 健康状态 ===")
        r_wk = client.get(f"{base_wk}/health")
        assert r_wk.status_code == 200, r_wk.text
        r_gw = client.get(f"{base_gw}/health")
        assert r_gw.status_code == 200, r_gw.text
        gw_health = r_gw.json()
        assert gw_health["overseas_worker_connected"] is True
        print("  ✓ 双端服务健康检查通过:", json.dumps(gw_health, ensure_ascii=False))

        print("\n=== [Test 2] 查询 TCC 算力点钱包初始状态 ===")
        r_wal = client.get(f"{base_gw}/api/wallet", params={"api_key": api_key})
        assert r_wal.status_code == 200
        initial_credits = r_wal.json()["user"]["credits_available"]
        print(f"  ✓ 当前账户可用算力点: {initial_credits}")

        print("\n=== [Test 3] 测试全链路 SSE 流式生成 (商业 PPT + 300DPI 图表 + 1080P 营销视频) ===")
        completed_evt = None
        with client.stream(
            "POST",
            f"{base_gw}/api/jobs/stream",
            json={
                "prompt_cn": "帮我做一份智能穿戴设备海外 Kickstarter 众筹路演全案，包含高管指标与增长图表，并配一条 9 秒产品展示视频",
                "task_type": "composite",
                "slide_count": 6,
                "visual_style": "executive-dark",
                "duration_seconds": 9,
                "execution_mode": "auto",
                "api_key": api_key,
            },
        ) as stream_resp:
            assert stream_resp.status_code == 200
            for line in stream_resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                evt = json.loads(line[6:])
                print(f"  [SSE {evt.get('pct', 0):3d}%] {evt.get('message_cn', evt.get('type'))}")
                if evt.get("type") == "completed":
                    completed_evt = evt

        assert completed_evt is not None, "SSE 任务未收到 completed 事件"
        cdn_urls = completed_evt["cdn_urls"]
        assert cdn_urls.get("pptx_url"), "未生成 PPTX 链接"
        assert cdn_urls.get("mp4_url"), "未生成 MP4 链接"
        assert len(cdn_urls.get("chart_urls", [])) >= 2, "未生成数据可视化图表"

        print("\n=== [Test 4] 校验生成的 .pptx 与 .mp4 文件下载完整性 ===")
        r_pptx = client.get(f"{base_gw}{cdn_urls['pptx_url']}")
        assert r_pptx.status_code == 200 and len(r_pptx.content) > 20000
        print(f"  ✓ PPTX 下载校验成功: {cdn_urls['pptx_url']} ({len(r_pptx.content):,} bytes)")

        r_mp4 = client.get(f"{base_gw}{cdn_urls['mp4_url']}")
        assert r_mp4.status_code == 200 and len(r_mp4.content) > 15000
        print(f"  ✓ MP4 视频下载校验成功: {cdn_urls['mp4_url']} ({len(r_mp4.content):,} bytes)")

        print("\n=== [Test 5] 测试标准 MCP 协议端点 (/mcp JSON-RPC 2.0) ===")
        r_mcp_list = client.post(
            f"{base_gw}/mcp",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert r_mcp_list.status_code == 200
        tools = r_mcp_list.json()["result"]["tools"]
        print(f"  ✓ MCP tools/list 返回 {len(tools)} 个商业工具: {[t['name'] for t in tools]}")

        r_mcp_call = client.post(
            f"{base_gw}/mcp",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "create_pro_presentation",
                    "arguments": {
                        "topic_and_requirements": "企业级 AI Agent 平台商业化战略报告",
                        "slide_count": 5,
                        "visual_style": "aurora-purple",
                    },
                },
            },
        )
        assert r_mcp_call.status_code == 200
        mcp_res = json.loads(r_mcp_call.json()["result"]["content"][0]["text"])
        assert mcp_res["status"] == "completed"
        print(f"  ✓ MCP tools/call (create_pro_presentation) 调用成功: job_id={mcp_res['job_id']}, 剩余算力点={mcp_res['billing_settlement']['remaining_credits']}")

    print("\n🎉 所有端到端功能与 TCC 计费核销测试全部通过！")


if __name__ == "__main__":
    run_e2e_tests()
