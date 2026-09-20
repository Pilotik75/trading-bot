"""Risk-Management: Positionsgröße und Hebel automatisch aus Kapitalrisiko + Stop-Distanz ableiten."""

from dataclasses import dataclass


@dataclass
class PositionSizeResult:
    size: float           # Menge des Basiswerts (z.B. BTC)
    position_value: float  # Positionswert in Quote-Währung (z.B. USDT)
    leverage: float        # tatsächlich benötigter Hebel
    stop_price: float
    risk_amount: float     # tatsächlich riskierter Betrag


def calculate_position_size(capital, entry_price, stop_distance, side, risk_pct=0.02, max_leverage=5.0):
    """Berechnet Positionsgröße und Hebel so, dass bei Erreichen des Stops genau
    `risk_pct` des Kapitals verloren wird (sofern das nicht mehr als max_leverage erfordert).

    Wird der für risk_pct nötige Hebel durch max_leverage gedeckelt, sinkt das
    tatsächliche Risiko entsprechend unter risk_pct (Sicherheitsgrenze geht vor).
    """
    if stop_distance <= 0:
        raise ValueError("stop_distance muss positiv sein")
    if entry_price <= 0:
        raise ValueError("entry_price muss positiv sein")
    if not (0 < risk_pct < 1):
        raise ValueError("risk_pct muss zwischen 0 und 1 liegen")

    risk_amount = capital * risk_pct
    stop_distance_pct = stop_distance / entry_price

    position_value = risk_amount / stop_distance_pct

    max_position_value = capital * max_leverage
    if position_value > max_position_value:
        position_value = max_position_value
        risk_amount = position_value * stop_distance_pct

    size = position_value / entry_price
    leverage = position_value / capital
    stop_price = entry_price - stop_distance if side == "long" else entry_price + stop_distance

    return PositionSizeResult(
        size=size,
        position_value=position_value,
        leverage=leverage,
        stop_price=stop_price,
        risk_amount=risk_amount,
    )
