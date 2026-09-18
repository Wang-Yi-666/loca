"""Price calculations."""


def total_with_tax(prices, rate):
    """Sum of `prices` plus `rate` tax (0.2 means 20%)."""
    subtotal = 0.0
    for price in prices:
        subtotal += price
    taxed = subtotal * (1 + rate)
    return taxed
