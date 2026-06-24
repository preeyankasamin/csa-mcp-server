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