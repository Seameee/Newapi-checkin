#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NewAPI 自动签到脚本
支持多账号签到，通过 GitHub Actions 定时执行
支持 Telegram 和钉钉通知
"""

import os
import sys
import json
import base64
import requests
from datetime import datetime
from typing import Optional

# ============ 通知模块 ============

def send_telegram_notification(bot_token: str, chat_id: str, message: str) -> bool:
    """
    发送 Telegram 通知
    
    Args:
        bot_token: Telegram Bot Token
        chat_id: 聊天ID（用户ID或频道ID）
        message: 消息内容（支持 MarkdownV2）
    """
    if not bot_token or not chat_id:
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # 转义 MarkdownV2 特殊字符
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    escaped_message = ''
    for char in message:
        if char in escape_chars:
            escaped_message += '\\' + char
        else:
            escaped_message += char
    
    payload = {
        'chat_id': chat_id,
        'text': escaped_message,
        'parse_mode': 'MarkdownV2',
        'disable_web_page_preview': True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        result = response.json()
        
        if result.get('ok'):
            print('  ✅ Telegram 通知发送成功')
            return True
        else:
            print(f'  ❌ Telegram 发送失败: {result.get("description")}')
            return False
            
    except Exception as e:
        print(f'  ❌ Telegram 请求异常: {e}')
        return False


def format_telegram_message(results: list, execution_time: str, total_accounts: int) -> str:
    """
    格式化 Telegram 通知消息
    """
    success_count = sum(1 for r in results if r.get('success'))
    fail_count = len(results) - success_count
    
    # 判断整体状态
    if fail_count == 0:
        status_emoji = "✅"
        status_text = "全部成功"
    elif success_count == 0:
        status_emoji = "❌"
        status_text = "全部失败"
    else:
        status_emoji = "⚠️"
        status_text = "部分成功"
    
    lines = [
        f"{status_emoji} *NewAPI 签到报告*",
        "",
        f"⏰ 执行时间: `{execution_time}`",
        f"📊 总计: {total_accounts} 个账号 | 成功 {success_count} | 失败 {fail_count}",
        ""
    ]
    
    # 每个账号的详情
    for i, result in enumerate(results, 1):
        name = result.get('name', f'账号{i}')
        success = result.get('success', False)
        
        if success:
            emoji = "✅"
            msg = result.get('message', '签到成功')
            quota = result.get('quota_awarded')
            
            line = f"{emoji} *{name}*: {msg}"
            
            if quota:
                # 格式化额度
                if quota >= 1000000:
                    quota_str = f"{quota / 1000000:.2f}M"
                elif quota >= 1000:
                    quota_str = f"{quota / 1000:.2f}K"
                else:
                    quota_str = str(quota)
                line += f" \\(+{quota_str}\\)"
                
            checkin_count = result.get('checkin_count')
            if checkin_count is not None:
                line += f" 本月已签{checkin_count}天"
                
        else:
            emoji = "❌"
            msg = result.get('message', '签到失败')
            # 截断过长的错误信息
            if len(msg) > 50:
                msg = msg[:47] + "..."
            line = f"{emoji} *{name}*: `{msg}`"
            
        lines.append(line)
    
    lines.append("")
    lines.append(f"#{status_text.replace(' ', '_')}")
    
    return '\n'.join(lines)


# 尝试导入钉钉通知（保持兼容）
try:
    from dingtalk_notifier import send_checkin_notification as send_dingtalk_notification
except ImportError:
    send_dingtalk_notification = None


class NewAPICheckin:
    """NewAPI 签到类"""

    @staticmethod
    def _mask_url(url: str) -> str:
        """
        脱敏 URL，隐藏域名细节
        例如: https://api.example.com -> https://api.***.**
        """
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain_parts = parsed.netloc.split('.')
            if len(domain_parts) >= 2:
                # 保留第一部分和最后一部分，中间用 *** 代替
                masked_domain = f"{domain_parts[0]}.***." + '.'.join(domain_parts[-1:])
            else:
                masked_domain = '***'
            return f"{parsed.scheme}://{masked_domain}"
        except Exception:
            return 'https://***'

    @staticmethod
    def _mask_user_id(user_id: str) -> str:
        """
        脱敏用户ID
        例如: 1429 -> ****
        """
        return '****'

    def __init__(self, base_url: str, session_cookie: str, user_id: str = None, cf_clearance: str = None):
        """
        初始化签到实例

        Args:
            base_url: API 基础地址，如 https://example.com
            session_cookie: session cookie 值
            user_id: 用户ID（可选，如果不提供会尝试自动提取）
            cf_clearance: Cloudflare clearance cookie（可选，用于绕过 CF 防护）
        """
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.cookies.set('session', session_cookie)

        # 如果提供了 cf_clearance，添加到 cookies
        if cf_clearance:
            self.session.cookies.set('cf_clearance', cf_clearance)

        self.session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'no-store',
            'Pragma': 'no-cache',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })

        # 设置用户ID
        if user_id:
            self.user_id = user_id
            self.session.headers.update({'new-api-user': str(user_id)})
        else:
            # 尝试从 Session Cookie 中提取用户ID
            self.user_id = self._extract_user_id_from_session(session_cookie)
            if self.user_id:
                self.session.headers.update({'new-api-user': str(self.user_id)})

    def _extract_user_id_from_session(self, session_cookie: str) -> Optional[str]:
        """
        从 Session Cookie 中提取用户ID

        Session Cookie 格式通常是 Base64 编码的数据
        """
        try:
            # 尝试解码 Session Cookie
            # Session 格式类似：MTc2NzQxMzYzM3xE...
            # 解码后可能包含用户信息
            decoded = base64.b64decode(session_cookie + '==')  # 添加 padding
            decoded_str = decoded.decode('utf-8', errors='ignore')

            # 查找可能的用户ID模式
            # 例如：linuxdo_988 中的 988
            import re
            # 查找 "linuxdo_数字" 或 "id"=数字 等模式
            patterns = [
                r'linuxdo[_-](\d+)',  # linuxdo_988
                r'"id"[:\s]+(\d+)',    # "id": 988
                r'user[_-](\d+)',      # user_988
                r'userid[:\s]+(\d+)',  # userid: 988
            ]

            for pattern in patterns:
                match = re.search(pattern, decoded_str, re.IGNORECASE)
                if match:
                    return match.group(1)

        except Exception:
            pass

        return None

    def get_user_info(self, verbose: bool = False) -> Optional[dict]:
        """
        获取用户信息

        自动设置 new-api-user 请求头

        Args:
            verbose: 是否显示详细调试信息
        """
        try:
            resp = self.session.get(f'{self.base_url}/api/user/self', timeout=30)

            if verbose:
                print(f'  [调试] HTTP 状态码: {resp.status_code}')
                print(f'  [调试] 响应内容预览: {resp.text[:200]}...')

            # 检查认证失败
            if resp.status_code == 401:
                print(f'[错误] 认证失败 (401): Session 可能已过期')
                if verbose:
                    print(f'  [调试] 完整响应: {resp.text[:500]}')
                return None

            # 尝试解析 JSON
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                print(f'[错误] 响应格式错误 (HTTP {resp.status_code}): 无法解析 JSON')
                if verbose:
                    print(f'  [调试] 原始响应: {resp.text[:500]}')
                return None

            if verbose:
                print(f'  [调试] success 字段: {data.get("success")}')
                print(f'  [调试] message 字段: {data.get("message")}')

            if resp.status_code == 200:
                if data.get('success'):
                    user_data = data.get('data')
                    # 保存用户ID并设置到请求头
                    if user_data and 'id' in user_data:
                        self.user_id = user_data['id']
                        self.session.headers.update({
                            'new-api-user': str(self.user_id)
                        })
                    return user_data
                else:
                    if verbose:
                        print(f'  [调试] API 返回失败: {data.get("message", "未知错误")}')
            else:
                print(f'[错误] HTTP {resp.status_code}: {data.get("message", "未知错误")}')

            return None

        except requests.exceptions.Timeout:
            print(f'[错误] 请求超时')
            return None
        except requests.exceptions.RequestException as e:
            print(f'[错误] 网络请求失败: {e}')
            return None
        except Exception as e:
            print(f'[错误] 未知错误: {e}')
            if verbose:
                import traceback
                traceback.print_exc()
            return None

    def checkin(self) -> dict:
        """
        执行签到

        Returns:
            签到结果字典，包含：
            - success: 是否成功
            - message: 返回消息
            - checkin_date: 签到日期
            - quota_awarded: 获得的额度
        """
        result = {
            'success': False,
            'message': '',
            'checkin_date': None,
            'quota_awarded': None
        }

        try:
            resp = self.session.post(f'{self.base_url}/api/user/checkin', timeout=30)

            # 先检查状态码
            if resp.status_code == 401:
                result['message'] = '认证失败: Session 可能已过期，请重新获取'
                return result

            # 尝试解析 JSON
            try:
                data = resp.json()
            except json.JSONDecodeError:
                # JSON 解析失败，显示原始响应内容
                content_preview = resp.text[:200] if resp.text else '(空响应)'
                result['message'] = f'响应格式错误 (HTTP {resp.status_code}): {content_preview}'
                return result

            if resp.status_code == 200:
                # 根据 API 响应的 success 字段判断
                if data.get('success'):
                    result['success'] = True
                    result['message'] = data.get('message', '签到成功')

                    # 解析签到数据
                    checkin_data = data.get('data', {})
                    result['checkin_date'] = checkin_data.get('checkin_date')
                    result['quota_awarded'] = checkin_data.get('quota_awarded')
                else:
                    result['message'] = data.get('message', '签到失败')
            else:
                result['message'] = f'HTTP {resp.status_code}: {data.get("message", "未知错误")}'

        except requests.exceptions.Timeout:
            result['message'] = '请求超时'
        except requests.exceptions.RequestException as e:
            result['message'] = f'网络请求失败: {e}'
        except Exception as e:
            result['message'] = f'未知错误: {e}'

        return result

    def get_checkin_history(self, month: str = None) -> Optional[dict]:
        """
        获取签到历史

        Args:
            month: 月份，格式 YYYY-MM，默认当前月
        """
        if month is None:
            month = datetime.now().strftime('%Y-%m')

        try:
            resp = self.session.get(
                f'{self.base_url}/api/user/checkin',
                params={'month': month},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    return data.get('data')
            return None
        except Exception as e:
            print(f'[错误] 获取签到历史失败: {e}')
            return None


def parse_accounts(accounts_str: str) -> list:
    """
    解析账号配置

    支持格式:
    1. 单账号: BASE_URL#SESSION_COOKIE
    2. 多账号: BASE_URL1#SESSION1,BASE_URL2#SESSION2
    3. JSON格式: [{"url": "...", "session": "..."}]
    """
    accounts = []

    if not accounts_str:
        return accounts

    # 尝试 JSON 格式
    try:
        data = json.loads(accounts_str)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and 'url' in item and 'session' in item:
                    account = {
                        'url': item['url'],
                        'session': item['session'],
                        'name': item.get('name', '')
                    }
                    # 如果提供了 user_id，添加到账号信息中
                    if 'user_id' in item:
                        account['user_id'] = item['user_id']
                    # 如果提供了 cf_clearance，添加到账号信息中
                    if 'cf_clearance' in item:
                        account['cf_clearance'] = item['cf_clearance']
                    accounts.append(account)
            return accounts
    except json.JSONDecodeError:
        pass

    # 简单格式: URL#SESSION,URL#SESSION
    for part in accounts_str.split(','):
        part = part.strip()
        if '#' in part:
            url, session = part.split('#', 1)
            accounts.append({
                'url': url.strip(),
                'session': session.strip(),
                'name': ''
            })

    return accounts


def main():
    """主函数"""
    # 设置北京时区
    import pytz
    beijing_tz = pytz.timezone('Asia/Shanghai')
    execution_time = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
    print('=' * 50)
    print('NewAPI 自动签到')
    print(f'执行时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 50)

    # 从环境变量获取账号配置
    accounts_str = os.environ.get('NEWAPI_ACCOUNTS', '')

    if not accounts_str:
        print('[错误] 未配置 NEWAPI_ACCOUNTS 环境变量')
        print('配置格式: BASE_URL#SESSION_COOKIE')
        print('多账号用逗号分隔: URL1#SESSION1,URL2#SESSION2')
        sys.exit(1)

    accounts = parse_accounts(accounts_str)

    if not accounts:
        print('[错误] 账号配置解析失败')
        sys.exit(1)

    print(f'共 {len(accounts)} 个账号待签到\n')

    success_count = 0
    fail_count = 0
    checkin_results = []

    for i, account in enumerate(accounts, 1):
        url = account['url']
        session_cookie = account['session']
        user_id = account.get('user_id')  # 获取用户ID（如果提供）
        cf_clearance = account.get('cf_clearance')  # 获取 CF clearance（如果提供）
        name = account.get('name') or f'账号{i}'

        print(f'[{i}/{len(accounts)}] {name}')
        print(f'  站点: {NewAPICheckin._mask_url(url)}')
        if user_id:
            print(f'  用户ID: {NewAPICheckin._mask_user_id(user_id)}')

        client = NewAPICheckin(url, session_cookie, user_id, cf_clearance)

        # 获取用户信息
        user_info = client.get_user_info()
        if user_info:
            username = user_info.get('username', '未知')
            # 用户名也脱敏，只显示前3个字符
            masked_username = username[:3] + '***' if len(username) > 3 else '***'
            print(f'  用户: {masked_username}')
        else:
            print('  用户: 获取失败（可能 session 已过期）')

        # 执行签到
        result = client.checkin()

        # 收集结果用于通知
        account_result = {
            'name': name,
            'success': False,
            'message': result['message'],
            'quota_awarded': None,
            'checkin_count': None
        }

        if result['success']:
            success_count += 1
            print(f'  结果: ✅ {result["message"]}')

            # 显示签到日期
            if result['checkin_date']:
                print(f'  日期: {result["checkin_date"]}')

            # 显示获得的额度（格式化显示）
            if result['quota_awarded']:
                quota = result['quota_awarded']
                # 格式化额度显示
                if quota >= 1000000:
                    quota_str = f'{quota / 1000000:.2f}M'
                elif quota >= 1000:
                    quota_str = f'{quota / 1000:.2f}K'
                else:
                    quota_str = str(quota)
                print(f'  奖励: +{quota_str} 额度 ({quota:,} tokens)')

            # 获取本月签到统计
            history = client.get_checkin_history()
            checkin_count = 0
            if history and history.get('stats'):
                stats = history['stats']
                checkin_count = stats.get('checkin_count', 0)
                total_quota = stats.get('total_quota', 0)
                if total_quota >= 1000000:
                    total_str = f'{total_quota / 1000000:.2f}M'
                elif total_quota >= 1000:
                    total_str = f'{total_quota / 1000:.2f}K'
                else:
                    total_str = str(total_quota)
                print(f'  统计: 本月已签 {checkin_count} 天，累计 {total_str} 额度')

            # 更新结果
            account_result['success'] = True
            account_result['message'] = result['message']
            account_result['quota_awarded'] = result.get('quota_awarded')
            account_result['checkin_count'] = checkin_count

        else:
            fail_count += 1
            print(f'  结果: ❌ {result["message"]}')
            account_result['message'] = result['message']

        checkin_results.append(account_result)
        print()

    # 汇总
    print('=' * 50)
    print(f'签到完成: 成功 {success_count}, 失败 {fail_count}')
    print('=' * 50)
    
    # ============ 发送通知 ============
    
    # 1. Telegram 通知
    tg_bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    tg_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if tg_bot_token and tg_chat_id:
        print('\n[通知] 发送 Telegram 通知...')
        tg_message = format_telegram_message(checkin_results, execution_time, len(accounts))
        send_telegram_notification(tg_bot_token, tg_chat_id, tg_message)
    elif os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_CHAT_ID'):
        print('\n[警告] Telegram 配置不完整，需要同时设置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID')
    
    # 2. 钉钉通知（保持兼容）
    if send_dingtalk_notification:
        print('\n[通知] 发送钉钉通知...')
        send_dingtalk_notification(checkin_results, execution_time)
    elif os.environ.get('DINGTALK_WEBHOOK'):
        print('\n[警告] 已配置 DINGTALK_WEBHOOK 但无法导入通知模块')

    # 如果全部失败则返回错误码
    if fail_count == len(accounts):
        sys.exit(1)


if __name__ == '__main__':
    main()
