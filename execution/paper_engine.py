"""Local paper broker with deterministic fills, positions, and exits."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from storage import get_store

class PaperBroker:
    def __init__(self, fee_pct=0.0, slippage_pct=0.0):
        self.fee_pct=float(fee_pct); self.slippage_pct=float(slippage_pct); self.store=get_store()
    def _fill_price(self, side, price):
        direction=1 if str(side).lower() in ('buy','long') else -1
        return float(price)*(1+direction*self.slippage_pct)
    def open_position(self, signal: Dict[str, Any], quantity: float, reason='SIGNAL') -> Dict[str, Any]:
        if self.store.open_positions_count() >= 5: raise RiskError('MAX_OPEN_POSITIONS')
        side='BUY' if signal['signal'].upper()=='BUY' else 'SELL'
        fill=self._fill_price(side, signal['entry']); sl=signal.get('sl'); tp=signal.get('tp')
        notional=abs(fill*quantity); fee=notional*self.fee_pct/100
        pos=self.store.open_position(signal, side, fill, quantity, sl, tp, fee, reason)
        return pos
    def mark_and_close(self, position_id: int, current_price: float, reason='MANUAL') -> Optional[Dict[str, Any]]:
        p=self.store.get_position(position_id)
        if not p or p['status']!='OPEN': return None
        direction=1 if p['side']=='BUY' else -1
        gross=(current_price-p['entry_price'])*p['quantity']*direction
        exit_price=self._fill_price(p['side'],current_price); net=gross-(float(p['entry_fee'] or 0)+abs(exit_price*p['quantity'])*self.fee_pct/100)
        return self.store.close_position(position_id, exit_price, net, reason)
    def check_exit(self, current_prices: Dict[str,float]) -> list:
        closed=[]
        for p in self.store.open_positions():
            price=current_prices.get(p['symbol'])
            if price is None: continue
            sl,tp=p['sl'],p['tp']
            hit_sl=sl is not None and ((p['side']=='BUY' and price<=sl) or (p['side']=='SELL' and price>=sl))
            hit_tp=tp is not None and ((p['side']=='BUY' and price>=tp) or (p['side']=='SELL' and price<=tp))
            if hit_sl or hit_tp: closed.append(self.mark_and_close(p['id'], sl if hit_sl else tp, 'STOP_LOSS' if hit_sl else 'TAKE_PROFIT'))
        return [x for x in closed if x]

class RiskError(Exception): pass
