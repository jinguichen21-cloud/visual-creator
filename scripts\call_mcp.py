#!/usr/bin/env python3
"""
MCP 工具调用脚本 — 通过 StreamableHTTP 协议调用 MCP Server
支持 $ENV_VAR 和直接 URL 两种方式

用法:
  python3 call_mcp.py list "$MCP_BOCHA_URL"
  python3 call_mcp.py call "$MCP_BOCHA_URL" web_search --params '{"query": "AI"}'
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error


def load_mcp_config():
    """从 mcp-config.json 加载配置，返回 {ENV_VAR: url} 映射"""
    config_path = os.path.join(os.path.dirname(__file__), "..", "mcp-config.json")
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v.get("url", "") for k, v in data.items() if isinstance(v, dict)}


def resolve_url(raw: str) -> str:
    """解析 URL：支持 $ENV_VAR 格式或直接 URL"""
    if raw.startswith("$"):
        var_name = raw[1:]
        # 优先从环境变量读取
        url = os.environ.get(var_name, "")
        if not url:
            # 回退到 mcp-config.json
            config = load_mcp_config()
            url = config.get(var_name, "")
        if not url:
            print(f"错误: 环境变量 {var_name} 未设置，且 mcp-config.json 中无对应 URL", file=sys.stderr)
            sys.exit(1)
        return url
    return raw


def send_request(url: str, method: str, params: dict, timeout: int = 30) -> dict:
    """发送 JSON-RPC 请求到 MCP Server"""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        body = resp.read().decode("utf-8")

        # SSE 响应处理
        if "text/event-stream" in content_type:
            return parse_sse(body)

        return json.loads(body)


def parse_sse(body: str) -> dict:
    """解析 SSE 格式响应，提取最后一个 data 事件"""
    last_data = None
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            raw = line[5:].strip()
            if raw:
                try:
                    last_data = json.loads(raw)
                except json.JSONDecodeError:
                    last_data = {"raw": raw}
    return last_data or {"error": "No data in SSE response"}


def cmd_list(url: str):
    """列出 MCP Server 的所有可用工具"""
    result = send_request(url, "tools/list", {})
    tools = result.get("result", {}).get("tools", [])
    if not tools:
        print("该 MCP Server 没有发现可用工具")
        return

    print(f"发现 {len(tools)} 个工具:\n")
    for t in tools:
        name = t.get("name", "unknown")
        desc = t.get("description", "无描述")
        print(f"  - {name}: {desc}")

        # 显示参数 schema
        schema = t.get("inputSchema", {}).get("properties", {})
        if schema:
            required = t.get("inputSchema", {}).get("required", [])
            for param, info in schema.items():
                req_mark = " *" if param in required else ""
                ptype = info.get("type", "any")
                pdesc = info.get("description", "")
                print(f"      {param}{req_mark} ({ptype}): {pdesc}")
        print()


def cmd_call(url: str, tool_name: str, params: dict):
    """调用 MCP Server 的指定工具"""
    result = send_request(url, "tools/call", {
        "name": tool_name,
        "arguments": params
    })

    # 提取内容
    content = result.get("result", {}).get("content", [])
    if content:
        for item in content:
            text = item.get("text", "")
            # 尝试美化 JSON 输出
            try:
                parsed = json.loads(text)
                print(json.dumps(parsed, ensure_ascii=False, indent=2))
            except (json.JSONDecodeError, TypeError):
                print(text)
    else:
        # 直接输出完整响应
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="MCP 工具调用脚本")
    sub = parser.add_subparsers(dest="command")

    # list 子命令
    list_p = sub.add_parser("list", help="列出 MCP Server 的所有工具")
    list_p.add_argument("url", help="MCP Server URL 或 $ENV_VAR")

    # call 子命令
    call_p = sub.add_parser("call", help="调用 MCP Server 的指定工具")
    call_p.add_argument("url", help="MCP Server URL 或 $ENV_VAR")
    call_p.add_argument("tool", help="工具名称")
    call_p.add_argument("--params", default="{}", help="JSON 格式的参数")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    url = resolve_url(args.url)

    if args.command == "list":
        cmd_list(url)
    elif args.command == "call":
        params = json.loads(args.params)
        cmd_call(url, args.tool, params)


if __name__ == "__main__":
    main()
