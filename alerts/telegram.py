"""
Telegram bot integration for sending trading signals.
Uses the Telegram Bot API directly via requests.
"""

import requests
from pathlib import Path
from typing import Optional


def send_telegram_signal(
    bot_token: str,
    chat_id: str,
    image_path: str,
    caption_str: str,
    parse_mode: str = "HTML",
) -> bool:
    """
    Send a trading signal image with caption to Telegram chat.

    Uses the Telegram Bot API sendPhoto endpoint to deliver
    annotated charts with formatted signal information.

    Args:
        bot_token: Telegram Bot API token
        chat_id: Target Telegram chat ID
        image_path: Path to the chart image file
        caption_str: Formatted caption text (supports HTML/Markdown)
        parse_mode: Telegram parse mode ('HTML' or 'MarkdownV2')

    Returns:
        True if message sent successfully, False otherwise

    Note:
        Caption should include:
        - Signal type (BUY/SELL)
        - Symbol and timeframe
        - Entry, SL, TP levels
        - Support/Resistance zones
        - Risk/Reward ratio
    """
    if not bot_token or not chat_id:
        print("[Telegram] Bot token or chat ID not configured")
        return False

    image_path_obj = Path(image_path)
    if not image_path_obj.exists():
        print(f"[Telegram] Image file not found: {image_path}")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    try:
        with open(image_path_obj, "rb") as photo:
            payload = {
                "chat_id": chat_id,
                "caption": caption_str,
                "parse_mode": parse_mode,
            }
            files = {
                "photo": photo,
            }

            response = requests.post(url, data=payload, files=files, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    print(f"[Telegram] Signal sent to chat {chat_id}")
                    return True
                else:
                    print(f"[Telegram] API error: {result.get('description', 'Unknown error')}")
                    return False
            else:
                print(f"[Telegram] HTTP error {response.status_code}: {response.text[:200]}")
                return False

    except requests.exceptions.Timeout:
        print("[Telegram] Request timed out")
        return False
    except requests.exceptions.RequestException as e:
        print(f"[Telegram] Request failed: {e}")
        return False
    except Exception as e:
        print(f"[Telegram] Unexpected error: {e}")
        return False


def format_signal_caption(
    symbol: str,
    signal: str,
    entry: float,
    sl: float,
    tp: float,
    support: Optional[float] = None,
    resistance: Optional[float] = None,
    rrr: Optional[float] = None,
    timeframe: str = "15m",
) -> str:
    """
    Format a trading signal caption with emoji and structured data.

    Args:
        symbol: Trading pair symbol
        signal: Signal direction ('BUY' or 'SELL')
        entry: Entry price
        sl: Stop loss price
        tp: Take profit price
        support: Support zone level
        resistance: Resistance zone level
        rrr: Risk-to-reward ratio
        timeframe: Entry timeframe

    Returns:
        Formatted caption string with emoji indicators
    """
    signal_emoji = "🟢" if signal.upper() == "BUY" else "🔴"
    trend_emoji = "📈" if signal.upper() == "BUY" else "📉"

    caption_parts = [
        f"{signal_emoji} <b>{signal.upper()} SIGNAL</b> — {symbol}",
        f"",
        f"📊 Timeframe: {timeframe}",
        f"{trend_emoji} Entry: <code>{entry:.4f}</code>",
        f"🛑 Stop Loss: <code>{sl:.4f}</code>",
        f"🎯 Take Profit: <code>{tp:.4f}</code>",
    ]

    if support is not None:
        caption_parts.append(f"🟢 Support: <code>{support:.4f}</code>")
    if resistance is not None:
        caption_parts.append(f"🔴 Resistance: <code>{resistance:.4f}</code>")
    if rrr is not None:
        caption_parts.append(f"⚖️ RRR: <b>{rrr:.1f}:1</b>")

    caption_parts.extend([
        f"",
        f"⚠️ <i>Manual execution required — verify before trading</i>",
    ])

    return "\n".join(caption_parts)