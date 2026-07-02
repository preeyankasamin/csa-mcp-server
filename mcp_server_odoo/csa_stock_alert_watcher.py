"""
CSA Aerotherm - Stock Alert Watcher
Finds products below minimum stock that have NO reordering rule in Odoo.
Does NOT duplicate Odoo's native reordering rule (ROR) alerts to Karthik.
"""
from .csa_notification_preferences import get_karthik_contact
from .csa_notification_dedup import should_send, mark_sent
from .logging_config import get_logger

logger = get_logger(__name__)

CSA_STOCK_LOCATION = "WH/CSAPL Stock"


def get_all_stock_quantities(conn) -> dict:
    """
    Fetches stock for ALL products in ONE Odoo call.
    Returns: { product_id: total_quantity }
    """
    quants = conn.search_read(
        "stock.quant",
        [
            ["location_id.complete_name", "ilike", CSA_STOCK_LOCATION],
            ["location_id.usage", "=", "internal"],
        ],
        fields=["product_id", "quantity"],
    )
    stock_map = {}
    for q in quants:
        if not q["product_id"] or q["quantity"] <= 0:
            continue
        pid = q["product_id"][0]
        stock_map[pid] = stock_map.get(pid, 0) + q["quantity"]
    return stock_map


def get_category_benchmarks(conn) -> dict:
    """
    Groups all existing reordering rules by product category,
    returns the average min_qty per category.
    conn -- authenticated OdooConnection
    Returns: { category_id: average_min_qty }
    """
    rules = conn.search_read(
        "stock.warehouse.orderpoint",
        [],
        fields=["product_category_id", "product_min_qty"],
    )
    totals = {}
    counts = {}
    for rule in rules:
        if not rule["product_category_id"]:
            continue
        cat_id = rule["product_category_id"][0]
        totals[cat_id] = totals.get(cat_id, 0) + rule["product_min_qty"]
        counts[cat_id] = counts.get(cat_id, 0) + 1

    benchmarks = {}
    for cat_id, total in totals.items():
        benchmarks[cat_id] = round(total / counts[cat_id], 2)
    return benchmarks


def find_watched_products(conn) -> dict:
    """
    Splits all products into three groups:
      critical     -- no rule, below category benchmark
      no_benchmark -- no rule, category has no benchmark to compare against
      has_rule     -- has a reordering rule (informational only)
    conn -- authenticated OdooConnection
    """
    benchmarks = get_category_benchmarks(conn)
    stock_map = get_all_stock_quantities(conn)

    rules = conn.search_read(
        "stock.warehouse.orderpoint",
        [],
        fields=["product_id"],
    )
    ruled_product_ids = {r["product_id"][0] for r in rules if r["product_id"]}

    logger.info("Fetching all products from Odoo...")
    all_products = conn.search_read(
        "product.product",
        [],
        fields=["name", "categ_id"],
    )
    logger.info(f"Fetched {len(all_products)} products.")

    critical = []
    no_benchmark = []
    has_rule = []
    raw_critical_count = [0]

    total = len(all_products)
    for idx, prod in enumerate(all_products):
        if idx % 500 == 0:
            logger.debug(f"Progress: {idx}/{total}")
        product_id = prod["id"]

        if product_id in ruled_product_ids:
            has_rule.append({
                "product_id": product_id,
                "product_name": prod["name"],
            })
            continue

        stock_qty = stock_map.get(product_id, 0)
        cat_id = prod["categ_id"][0] if prod["categ_id"] else None
        cat_name = prod["categ_id"][1] if prod["categ_id"] else "Uncategorized"

        if cat_id == 1:
            cat_id = None

        if cat_id in benchmarks:
            benchmark_min = benchmarks[cat_id]
            raw_critical_count[0] += 1
            if stock_qty < benchmark_min:
                critical.append({
                    "product_id": product_id,
                    "product_name": prod["name"],
                    "category": cat_name,
                    "stock_qty": stock_qty,
                    "benchmark_min": benchmark_min,
                })
        else:
            no_benchmark.append({
                "product_id": product_id,
                "product_name": prod["name"],
                "category": cat_name,
                "stock_qty": stock_qty,
            })

    logger.info(f"Products with a real benchmark to compare: {raw_critical_count[0]}")
    logger.info(f"Of those, below benchmark (critical): {len(critical)}")
    return {"critical": critical, "no_benchmark": no_benchmark, "has_rule": has_rule}


def run_stock_alert_watcher(conn):
    """
    Entry point. Builds the report, applies dedup, returns what would be sent.
    Does NOT send WhatsApp/email yet (Day 5 wiring).
    """
    results = find_watched_products(conn)
    contact = get_karthik_contact(conn)

    to_alert = []
    skip_count = 0
    for item in results["critical"]:
        fingerprint = f"stock_alert|{item['product_id']}"
        decision = should_send(fingerprint)
        if decision:
            to_alert.append(item)
            mark_sent(fingerprint)
        else:
            skip_count += 1
    logger.info(f"Stock alert watcher: total_critical={len(results['critical'])}, alerted={len(to_alert)}, skipped_dedup={skip_count}")

    logger.info(
        f"Stock Alert Watcher: {len(to_alert)} new critical, "
        f"{len(results['no_benchmark'])} no-benchmark, "
        f"{len(results['has_rule'])} has-rule"
    )

    return {
        "recipient": contact,
        "critical_new": to_alert,
        "no_benchmark": results["no_benchmark"],
        "has_rule_informational": results["has_rule"],
    }