"""
Broker interface for trade execution.
Currently configured for paper trading / manual mode only.
Auto-execution is DISABLED — all trades require manual confirmation.
"""

from typing import Dict, Optional
from datetime import datetime, timezone
import json


def paper_order_stub(
    symbol: str,
    side: str,
    qty: float,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    order_type: str = "market",
    price: Optional[float] = None,
) -> Dict:
    """
    Paper trading order stub for manual mode.

    Prints order details for manual execution. Does NOT connect
    to any exchange or execute real trades.

    In manual mode, the trader must:
    1. Review the signal
    2. Confirm the setup on their exchange
    3. Enter the order manually

    Args:
        symbol: Trading pair symbol (e.g., 'BTC/USDT')
        side: Order side ('buy' or 'sell')
        qty: Quantity to trade
        sl: Stop loss price (optional)
        tp: Take profit price (optional)
        order_type: Order type ('market' or 'limit')
        price: Limit order price (optional, ignored for market orders)

    Returns:
        Dict with order details and confirmation status
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    order = {
        "order_id": f"PAPER-{int(datetime.now().timestamp())}",
        "symbol": symbol,
        "side": side.upper(),
        "qty": qty,
        "order_type": order_type,
        "price": price if order_type == "limit" else None,
        "sl": sl,
        "tp": tp,
        "timestamp": timestamp,
        "status": "PENDING_MANUAL_EXECUTION",
        "mode": "PAPER",
    }

    # Print order for manual review
    print("\n" + "=" * 60)
    print("PAPER ORDER STUB - MANUAL EXECUTION REQUIRED")
    print("=" * 60)
    print(f"  Order ID:  {order['order_id']}")
    print(f"  Symbol:    {order['symbol']}")
    print(f"  Side:      {order['side']}")
    print(f"  Qty:       {order['qty']:.6f}")
    print(f"  Type:      {order['order_type'].upper()}")
    if price and order_type == "limit":
        print(f"  Price:     {order['price']:.4f}")
    if sl:
        print(f"  Stop Loss: {order['sl']:.4f}")
    if tp:
        print(f"  Take Profit: {order['tp']:.4f}")
    print(f"  Timestamp: {order['timestamp']}")
    print("=" * 60)
    print("WARNING: DO NOT EXECUTE WITHOUT MANUAL VERIFICATION")
    print("=" * 60 + "\n")

    return order


# ─── CCXT Live Trading Placeholder ──────────────────────────────────────────
# The following is a placeholder for future live trading implementation.
# DO NOT ENABLE without proper risk management and testing.

# def ccxt_place_order(
#     exchange: ccxt.Exchange,
#     symbol: str,
#     side: str,
#     qty: float,
#     sl: Optional[float] = None,
#     tp: Optional[float] = None,
#     order_type: str = "market",
#     price: Optional[float] = None,
# ) -> Dict:
#     """
#     Place a live order via CCXT.
#
#     WARNING: This is a placeholder. Use only after thorough testing.
#     """
#     try:
#         params = {}
#
#         if sl or tp:
#             # Some exchanges support OCO (One-Cancels-Other) orders
#             if sl and tp:
#                 params["stopLoss"] = {"type": "stop", "price": sl}
#                 params["takeProfit"] = {"type": "take_profit", "price": tp}
#
#         if order_type == "limit":
#             order = exchange.create_order(
#                 symbol, "limit", side, qty, price, params
#             )
#         else:
#             order = exchange.create_order(
#                 symbol, "market", side, qty, None, params
#             )
#
#         return {
#             "order_id": order["id"],
#             "symbol": symbol,
#             "side": side,
#             "qty": qty,
#             "status": order["status"],
#             "price": order.get("price"),
#         }
#
#     except ccxt.InsufficientFunds as e:
#         print(f"Insufficient funds: {e}")
#         raise
#     except ccxt.InvalidOrder as e:
#         print(f"Invalid order: {e}")
#         raise
#     except Exception as e:
#         print(f"Order failed: {e}")
#         raise