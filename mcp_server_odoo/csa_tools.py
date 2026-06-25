"""
CSA Aerotherm custom MCP tools.
All tools specific to CS Aerotherm's automation pipeline live here.
This file is separate from tools.py to keep CSA code isolated from
the original mcp-server-odoo repo code.
"""

import xmlrpc.client
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from .logging_config import get_logger, perf_logger
from .odoo_connection import OdooConnection

# Creates a logger named 'mcp_server_odoo.csa_tools'
# Every log line from this file will be tagged with this name
logger = get_logger(__name__)

# The internal warehouse stock location name in CSA's Odoo
# Confirmed from stock.quant query: location_id = [8, 'WH/CSAPL Stock']
CSA_STOCK_LOCATION = "WH/CSAPL Stock"


class CSAToolHandler:
    """
    Handles all CSA Aerotherm specific MCP tools.
    Registered into the same FastMCP app as OdooToolHandler.
    """

    def __init__(self, app: FastMCP, connection: OdooConnection):
        """
        app        — the FastMCP server instance (same one used by OdooToolHandler)
        connection — the OdooConnection instance (handles all XML-RPC calls)
        """
        self.app = app
        self.connection = connection
        self._register_csa_tools()

    def _register_csa_tools(self):
        """Registers all CSA tools into the FastMCP app."""

        @self.app.tool(
            title="Get BOM with Stock",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def get_bom_with_stock(
            product_name: str,
            ctx: Optional[Context] = None,
        ) -> Dict[str, Any]:
            """
            Get the Bill of Materials for a product and check current stock
            for each component against CSA's warehouse (WH/CSAPL Stock).

            Use this tool when asked:
            - "What parts do I need to build [product]?"
            - "Do we have enough stock to manufacture [product]?"
            - "Show me the BOM and stock status for [product]"
            - "Are there any shortages for [product]?"

            Args:
                product_name: Full or partial product name or internal reference
                              e.g. "B-1300", "CSA-CRM11", "Deck Oven"

            Returns:
                BOM header info, list of components with required qty,
                available stock, and shortage flag for each component.
            """
            return await self._handle_get_bom_with_stock(product_name, ctx)

    # ── Core logic ────────────────────────────────────────────────────────────

    async def _handle_get_bom_with_stock(
        self,
        product_name: str,
        ctx: Optional[Context] = None,
    ) -> Dict[str, Any]:
        """
        Core logic for get_bom_with_stock.
        Separated from the tool decorator to make it independently testable.
        """

        logger.info(f"get_bom_with_stock called for product: '{product_name}'")

        # ── Step 1: Find the BOM for this product ─────────────────────────────
        # Search mrp.bom where the product template name matches input
        # ilike = case-insensitive contains search
        with perf_logger.track_operation("bom_search", model="mrp.bom"):
           bom_records = self.connection.execute_kw(
                "mrp.bom",
                "search_read",
                [["|",
                  ["product_tmpl_id.name", "ilike", product_name],
                  ["product_tmpl_id.default_code", "ilike", product_name]]],
                {
                    "fields": [
                        "product_tmpl_id",   # finished product name + id
                        "product_qty",        # how many units this BOM produces
                        "product_uom_id",     # unit of measure (Nos, Kg, etc)
                        "bom_line_ids",       # list of component line IDs
                    ],
                    "limit": 5,
                },
            )

        # If no BOM found, return a clear message
        if not bom_records:
            logger.warning(f"No BOM found for product: '{product_name}'")
            return {
                "found": False,
                "product_name": product_name,
                "message": f"No Bill of Materials found for '{product_name}'. "
                           f"Check the product name or internal reference.",
                "components": [],
            }

        # Take the first matching BOM
        bom = bom_records[0]
        bom_id = bom["id"]
        finished_product = bom["product_tmpl_id"][1]  # [0]=id, [1]=name
        produces_qty = bom["product_qty"]
        uom = bom["product_uom_id"][1]

        logger.info(f"Found BOM id={bom_id} for '{finished_product}'")

        # ── Step 2: Get all component lines ───────────────────────────────────
        with perf_logger.track_operation("bom_lines_fetch", model="mrp.bom.line"):
            bom_lines = self.connection.execute_kw(
                "mrp.bom.line",
                "search_read",
                [[["bom_id", "=", bom_id]]],
                {
                    "fields": [
                        "product_id",       # component product id + name
                        "product_qty",      # quantity needed
                        "product_uom_id",   # unit of measure
                    ]
                },
            )

        if not bom_lines:
            return {
                "found": True,
                "bom_id": bom_id,
                "finished_product": finished_product,
                "produces_qty": produces_qty,
                "uom": uom,
                "message": "BOM exists but has no component lines.",
                "components": [],
                "has_shortages": False,
            }

        # ── Step 3: Check stock for each component ────────────────────────────
        components = []
        has_shortages = False

        for line in bom_lines:
            product_id = line["product_id"][0]    # numeric ID
            product_name_full = line["product_id"][1]  # display name
            qty_needed = line["product_qty"]
            comp_uom = line["product_uom_id"][1]

            # Query stock.quant for this product in CSA warehouse only
            with perf_logger.track_operation("stock_check", model="stock.quant"):
                quant_records = self.connection.execute_kw(
                    "stock.quant",
                    "search_read",
                    [[
                        ["product_id", "=", product_id],
                        ["location_id.complete_name", "ilike", CSA_STOCK_LOCATION],
                        ["location_id.usage", "=", "internal"],
                    ]],
                    {"fields": ["quantity", "location_id"]},
                )

            # Sum all quantities across matching locations
            # (product may be in multiple bins within the warehouse)
            qty_available = sum(
                q["quantity"] for q in quant_records if q["quantity"] > 0
            )

            shortage = qty_available < qty_needed

            if shortage:
                has_shortages = True

            components.append({
                "product_id": product_id,
                "product_name": product_name_full,
                "qty_needed": qty_needed,
                "qty_available": round(qty_available, 2),
                "uom": comp_uom,
                "shortage": shortage,
                "shortage_qty": round(max(0, qty_needed - qty_available), 2),
            })

            logger.debug(
                f"Component '{product_name_full}': "
                f"need={qty_needed}, have={qty_available}, shortage={shortage}"
            )

        # ── Step 4: Return complete result ────────────────────────────────────
        result = {
            "found": True,
            "bom_id": bom_id,
            "finished_product": finished_product,
            "produces_qty": produces_qty,
            "uom": uom,
            "total_components": len(components),
            "has_shortages": has_shortages,
            "shortage_count": sum(1 for c in components if c["shortage"]),
            "components": components,
        }

        logger.info(
            f"get_bom_with_stock complete: {len(components)} components, "
            f"shortages={has_shortages}"
        )

        return result

# ── Multi-level BOM explosion ──────────────────────────────────────────

    def _get_bom_for_product_id(self, product_id: int):
        """
        Given a product.product ID, find its BOM if one exists.
        Returns the BOM record or None.

        product_id  — the numeric Odoo ID of the product
        """
        # First get the product_tmpl_id from product.product
        # because mrp.bom links to product.template, not product.product
        product_records = self.connection.execute_kw(
            "product.product",
            "read",
            [[product_id]],
            {"fields": ["product_tmpl_id"]},
        )
        if not product_records:
            return None

        tmpl_id = product_records[0]["product_tmpl_id"][0]

        # Now search mrp.bom for this template
        bom_records = self.connection.execute_kw(
            "mrp.bom",
            "search_read",
            [[["product_tmpl_id", "=", tmpl_id]]],
            {
                "fields": [
                    "id",
                    "product_qty",
                    "bom_line_ids",
                ],
                "limit": 1,
            },
        )
        if not bom_records:
            return None

        return bom_records[0]

    def _explode(
        self,
        product_id: int,
        product_name: str,
        qty_needed: float,
        uom: str,
        visited: set,
        depth: int = 0,
    ):
        """
        Recursively breaks down a product into its raw materials.
        Returns a list of raw material dicts.

        product_id   — numeric Odoo ID of the product to break down
        product_name — display name (used for logging only)
        qty_needed   — how many units of this product we need
        uom          — unit of measure string
        visited      — set of product_ids already processed (circular BOM guard)
        depth        — how deep we are (0=top level, 1=sub-assembly, etc)
        """

        # ── Circular BOM guard ──────────────────────────────────────────
        # If we have already visited this product, stop immediately
        # This prevents infinite loops if Odoo has A→B→A by mistake
        if product_id in visited:
            logger.warning(
                f"Circular BOM detected for product_id={product_id} "
                f"'{product_name}' at depth={depth}. Stopping recursion."
            )
            return [{
                "product_id": product_id,
                "product_name": product_name,
                "qty_needed": qty_needed,
                "uom": uom,
                "depth": depth,
                "note": "circular_bom_detected",
            }]

        # Mark this product as visited
        visited.add(product_id)

        # ── Check if this product has a BOM ────────────────────────────
        bom = self._get_bom_for_product_id(product_id)

        if bom is None:
            # No BOM = this is a raw material = add to final list
            logger.debug(
                f"{'  ' * depth}RAW: '{product_name}' qty={qty_needed} {uom}"
            )
            return [{
                "product_id": product_id,
                "product_name": product_name,
                "qty_needed": round(qty_needed, 4),
                "uom": uom,
                "depth": depth,
            }]

        # ── Has a BOM = fetch its component lines ──────────────────────
        bom_produces_qty = bom["product_qty"]
        # Scale factor: if BOM produces 2 units but we need 6,
        # we need 3x all quantities
        scale = qty_needed / bom_produces_qty

        bom_lines = self.connection.execute_kw(
            "mrp.bom.line",
            "search_read",
            [[["bom_id", "=", bom["id"]]]],
            {
                "fields": [
                    "product_id",
                    "product_qty",
                    "product_uom_id",
                ]
            },
        )

        logger.debug(
            f"{'  ' * depth}ASSEMBLY: '{product_name}' "
            f"qty={qty_needed} → {len(bom_lines)} components"
        )

        # ── Recurse into each component ────────────────────────────────
        raw_materials = []
        for line in bom_lines:
            comp_id = line["product_id"][0]
            comp_name = line["product_id"][1]
            comp_qty = line["product_qty"] * scale
            comp_uom = line["product_uom_id"][1]

            # Recurse — go one level deeper
            result = self._explode(
                product_id=comp_id,
                product_name=comp_name,
                qty_needed=comp_qty,
                uom=comp_uom,
                visited=visited,
                depth=depth + 1,
            )
            raw_materials.extend(result)

        return raw_materials

    def explode_bom_multilevel(
        self,
        product_name: str,
        qty: float = 1.0,
    ):
        """
        Entry point for multi-level BOM explosion.
        Takes a product name and quantity, returns full raw material list.

        product_name — full or partial name or internal reference
        qty          — how many finished units you want to build (default 1)
        """

        logger.info(
            f"explode_bom_multilevel called: product='{product_name}' qty={qty}"
        )

        # Step 1: Find the top-level BOM by name (same search as get_bom_with_stock)
        bom_records = self.connection.execute_kw(
            "mrp.bom",
            "search_read",
            [["|",
              ["product_tmpl_id.name", "ilike", product_name],
              ["product_tmpl_id.default_code", "ilike", product_name]]],
            {
                "fields": [
                    "id",
                    "product_tmpl_id",
                    "product_qty",
                    "product_uom_id",
                    "bom_line_ids",
                ],
                "limit": 1,
            },
        )

        if not bom_records:
            return {
                "found": False,
                "product_name": product_name,
                "message": f"No BOM found for '{product_name}'.",
                "raw_materials": [],
            }

        bom = bom_records[0]
        finished_product = bom["product_tmpl_id"][1]
        bom_produces_qty = bom["product_qty"]
        uom = bom["product_uom_id"][1]

        # Get the product.product ID for the finished product
        tmpl_id = bom["product_tmpl_id"][0]
        product_variants = self.connection.execute_kw(
            "product.product",
            "search_read",
            [[["product_tmpl_id", "=", tmpl_id]]],
            {"fields": ["id"], "limit": 1},
        )
        if not product_variants:
            return {
                "found": False,
                "product_name": product_name,
                "message": f"Product template found but no variant exists.",
                "raw_materials": [],
            }

        top_product_id = product_variants[0]["id"]

        # Step 2: Explode — pass empty visited set (fresh start)
        scale = qty / bom_produces_qty
        raw_materials_nested = []

        bom_lines = self.connection.execute_kw(
            "mrp.bom.line",
            "search_read",
            [[["bom_id", "=", bom["id"]]]],
            {"fields": ["product_id", "product_qty", "product_uom_id"]},
        )

        visited = {top_product_id}  # mark top product as visited immediately

        for line in bom_lines:
            comp_id = line["product_id"][0]
            comp_name = line["product_id"][1]
            comp_qty = line["product_qty"] * scale
            comp_uom = line["product_uom_id"][1]

            result = self._explode(
                product_id=comp_id,
                product_name=comp_name,
                qty_needed=comp_qty,
                uom=comp_uom,
                visited=visited,
                depth=1,
            )
            raw_materials_nested.extend(result)

        # Step 3: Merge duplicates
        # Same product may appear via multiple paths — combine their quantities
        merged = {}
        for item in raw_materials_nested:
            pid = item["product_id"]
            if pid in merged:
                merged[pid]["qty_needed"] = round(
                    merged[pid]["qty_needed"] + item["qty_needed"], 4
                )
            else:
                merged[pid] = item.copy()

        raw_materials = list(merged.values())

        logger.info(
            f"explode_bom_multilevel complete: '{finished_product}' "
            f"qty={qty} → {len(raw_materials)} unique raw materials"
        )

        return {
            "found": True,
            "finished_product": finished_product,
            "qty_requested": qty,
            "uom": uom,
            "total_unique_raw_materials": len(raw_materials),
            "raw_materials": raw_materials,
        }