#!/bin/bash

# 设置环境变量
export NEWAPI_ACCOUNTS='[
  {
    "url": "https://api.example.com",
    "session": "MTc2NzQxMzYzM3xEWDhFQVFMX2dBQUJFQUVRQUFE...",
    "user_id": "123",
    "name": "主力站"
  },
  {
    "url": "https://api2.example.com",
    "session": "QVFMXzJhYWJFRUFRQUFEX3dfLUFBQVlHYzNS...",
    "user_id": "456",
    "name": "备用站"
  },
  {
    "url": "https://api3.example.com",
    "session": "RFhFN0FBQkVBRVFBQUQzd19fQUFBWUdjM1J5...",
    "user_id": "789",
    "name": "测试站"
  }
]'
export TELEGRAM_BOT_TOKEN="TELEGRAM_BOT_TOKEN"
export TELEGRAM_CHAT_ID="123456"

# 运行脚本
cd "$(dirname "$0")"
uv run python checkin.py "$@"
