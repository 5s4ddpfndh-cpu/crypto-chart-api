"""Support / resistance zones built by clustering swing points."""


def build_zones(swings, atr_value, total_bars, tolerance=0.6, max_width=1.0, pad=0.15):
    """Group swing prices that sit within `tolerance * ATR` of each other into
    zones no wider than `max_width * ATR`. Strength rewards repeated touches
    and recent touches."""
    if not swings or not atr_value:
        return []
    points = sorted(swings, key=lambda s: s["price"])
    clusters = [[points[0]]]
    for point in points[1:]:
        cluster = clusters[-1]
        if (point["price"] - cluster[-1]["price"] <= tolerance * atr_value
                and point["price"] - cluster[0]["price"] <= max_width * atr_value):
            cluster.append(point)
        else:
            clusters.append([point])

    zones = []
    for cluster in clusters:
        prices = [p["price"] for p in cluster]
        last_index = max(p["index"] for p in cluster)
        recency = last_index / max(total_bars - 1, 1)
        low = min(prices) - pad * atr_value
        high = max(prices) + pad * atr_value
        zones.append({
            "low": low,
            "high": high,
            "mid": (low + high) / 2,
            "touches": len(cluster),
            "strength": round(len(cluster) + 2 * recency, 2),
            "lastTouchIndex": last_index,
        })
    return zones


def split_zones(zones, price):
    """Supports are zones whose middle is below price (nearest first);
    resistances are above price (nearest first)."""
    supports = sorted((z for z in zones if z["mid"] < price), key=lambda z: -z["mid"])
    resistances = sorted((z for z in zones if z["mid"] >= price), key=lambda z: z["mid"])
    return supports, resistances
