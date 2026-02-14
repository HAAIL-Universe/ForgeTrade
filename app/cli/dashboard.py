"""CLI dashboard — prints bot status to the console."""


def print_status(status: dict) -> str:
    """Format and print the current bot status.

    Args:
        status: Dict matching the physics.yaml ``BotStatus`` schema.

    Returns:
        The formatted string (also printed to stdout).
    """
    mode = status.get("mode", "unknown")
    running = status.get("running", False)
    pair = status.get("pair", "N/A")
    equity = status.get("equity")
    balance = status.get("balance")
    drawdown = status.get("drawdown_pct")
    cb_active = status.get("circuit_breaker_active", False)
    positions = status.get("open_positions", 0)
    uptime = status.get("uptime_seconds", 0)

    equity_str = f"${equity:,.2f}" if equity is not None else "N/A"
    balance_str = f"${balance:,.2f}" if balance is not None else "N/A"
    dd_str = f"{drawdown:.2f}%" if drawdown is not None else "N/A"
    cb_str = "ACTIVE" if cb_active else "off"

    lines = [
        "──────────────── ForgeTrade Status ────────────────",
        f"  Mode:            {mode}",
        f"  Running:         {running}",
        f"  Pair:            {pair}",
        f"  Equity:          {equity_str}",
        f"  Balance:         {balance_str}",
        f"  Drawdown:        {dd_str}",
        f"  Circuit Breaker: {cb_str}",
        f"  Open Positions:  {positions}",
        f"  Uptime:          {uptime:.0f}s",
        "──────────────────────────────────────────────────",
    ]
    output = "\n".join(lines)
    print(output)
    return output
