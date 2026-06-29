"""
CSA Aerotherm custom MCP tools.
All tools specific to CS Aerotherm's automation pipeline live here.
This file is separate from tools.py to keep CSA code isolated from
the original mcp-server-odoo repo code.
"""

import xmlrpc.client
import socket
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, field_validator

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from .logging_config import get_logger, perf_logger
# Default timeout in seconds for all Odoo XML-RPC calls
# If Odoo does not respond within this time, raise a clean error
ODOO_XMLRPC_TIMEOUT = 30
from .odoo_connection import OdooConnection

# Creates a logger named 'mcp_server_odoo.csa_tools'
# Every log line from this file will be tagged with this name
logger = get_logger(__name__)

# The internal warehouse stock location name in CSA's Odoo
# Confirmed from stock.quant query: location_id = [8, 'WH/CSAPL Stock']
CSA_STOCK_LOCATION = "WH/CSAPL Stock"

class BomInput(BaseModel):
    product_name: str
    qty: float = 1.0

    @field_validator("product_name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("product_name cannot be empty")
        return v.strip()

    @field_validator("qty")
    @classmethod
    def qty_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("qty must be greater than 0")
        return v  #v — the actual value passed in by Claude


class ShortageInput(BaseModel):
    product_name: str
    qty: float = 1.0

    @field_validator("product_name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v.strip():  #v.strip() — removes spaces from both ends of the string
            raise ValueError("product_name cannot be empty")
        return v.strip()

    @field_validator("qty")
    @classmethod
    def qty_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("qty must be greater than 0")
        return v


class VendorInput(BaseModel):
    product_name: str
    qty: float = 1.0

    @field_validator("product_name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("product_name cannot be empty")
        return v.strip()

    @field_validator("qty")
    @classmethod
    def qty_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("qty must be greater than 0")
        return v

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
        socket.setdefaulttimeout(ODOO_XMLRPC_TIMEOUT)

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
        try:
            params = BomInput(product_name=product_name, qty=1.0)
            product_name = params.product_name
        except ValueError as e:
            return {"error": str(e)}

        logger.info(f"get_bom_with_stock called for product: '{product_name}'")
        try:

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

        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo fault in get_bom_with_stock: {e}")
            return {"error": f"Odoo rejected the request: {str(e)}"}
        except socket.timeout:
            logger.error("Timeout in get_bom_with_stock")
            return {"error": "Odoo took too long to respond. Please try again."}
        except Exception as e:
            logger.error(f"Unexpected error in get_bom_with_stock: {e}")
            return {"error": f"Unexpected error: {str(e)}"}

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
    def _check_stock_for_product(self, product_id: int) -> float:
        """
        Returns the available stock qty for a product in WH/CSAPL Stock.

        product_id -- numeric Odoo ID of the product
        """
        quant_records = self.connection.execute_kw(
            "stock.quant",
            "search_read",
            [[
                ["product_id", "=", product_id],
                ["location_id.complete_name", "ilike", CSA_STOCK_LOCATION],
                ["location_id.usage", "=", "internal"],
            ]],
            {"fields": ["quantity"]},
        )
        return sum(q["quantity"] for q in quant_records if q["quantity"] > 0)

    def get_shortage_report(
        self,
        product_name: str,
        qty: float = 1.0,
    ):
        """
        Full multi-level shortage report for a product.
        Explodes the BOM completely, checks stock for every raw material,
        returns only the items that are short.

        product_name -- full or partial name or internal reference
        qty          -- how many finished units you want to build (default 1)
        """
        try:
            params = ShortageInput(product_name=product_name, qty=qty)
            product_name = params.product_name
            qty = params.qty
        except ValueError as e:
            return {"error": str(e)}

        logger.info(
            f"get_shortage_report called: product='{product_name}' qty={qty}"
        )
        try:
    
            # Step 1: Explode the BOM fully
            explosion = self.explode_bom_multilevel(product_name, qty)

            if not explosion["found"]:
                return {
                    "found": False,
                    "product_name": product_name,
                    "message": explosion["message"],
                    "shortages": [],
                }

            # Step 2: Check stock for each raw material
            shortages = []
            for item in explosion["raw_materials"]:
                qty_available = self._check_stock_for_product(item["product_id"])
                qty_needed = item["qty_needed"]

                if qty_available < qty_needed:
                    shortages.append({
                        "product_id": item["product_id"],
                        "product_name": item["product_name"],
                        "qty_needed": round(qty_needed, 2),
                        "qty_available": round(qty_available, 2),
                        "shortage_qty": round(qty_needed - qty_available, 2),
                        "uom": item["uom"],
                    })

            logger.info(
                f"get_shortage_report complete: '{explosion['finished_product']}' "
                f"qty={qty} -> {len(shortages)} shortages out of "
                f"{explosion['total_unique_raw_materials']} raw materials"
            )

            return {
                "found": True,
                "finished_product": explosion["finished_product"],
                "qty_requested": qty,
                "total_raw_materials": explosion["total_unique_raw_materials"],
                "shortage_count": len(shortages),
                "has_shortages": len(shortages) > 0,
                "shortages": shortages,
            }

        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo fault in get_shortage_report: {e}")
            return {"error": f"Odoo rejected the request: {str(e)}"}
        except socket.timeout:
            logger.error("Timeout in get_shortage_report")
            return {"error": "Odoo took too long to respond. Please try again."}
        except Exception as e:
            logger.error(f"Unexpected error in get_shortage_report: {e}")
            return {"error": f"Unexpected error: {str(e)}"}

    def _get_vendor_info_for_product(self, product_id: int, qty_needed: float):
        """
        Fetches all vendors for a component from product.supplierinfo.
        Returns list of vendors with price, min_qty, lead_time,
        and a recommended_vendor picked by lowest price where min_qty is meetable.

        product_id  -- numeric Odoo product.product ID
        qty_needed  -- how many units we need (used to filter meetable min_qty)
        """
        # product.supplierinfo links to product.template, not product.product
        # so first get the template ID
        product_records = self.connection.execute_kw(
            "product.product",
            "read",
            [[product_id]],
            {"fields": ["product_tmpl_id", "display_name"]},
        )
        if not product_records:
            return [], None

        tmpl_id = product_records[0]["product_tmpl_id"][0]
        product_display_name = product_records[0]["display_name"]

        # Now fetch all vendor pricelists for this product template
        supplier_records = self.connection.execute_kw(
            "product.supplierinfo",
            "search_read",
            [[["product_tmpl_id", "=", tmpl_id]]],
            {
                "fields": [
                    "partner_id",    # vendor name + id
                    "price",         # unit price
                    "min_qty",       # minimum order quantity
                    "delay",         # lead time in days
                    "currency_id",   # currency (INR etc)
                ],
            },
        )

        if not supplier_records:
            return [], None

        # Build clean vendor list
        vendors = []
        for s in supplier_records:
            vendors.append({
                "vendor_name": s["partner_id"][1],
                "vendor_id": s["partner_id"][0],
                "price": s["price"],
                "min_qty": s["min_qty"],
                "lead_time_days": s["delay"],
                "currency": s["currency_id"][1] if s["currency_id"] else "INR",
            })

        # Pick recommended vendor:
        # 1. Filter to vendors whose min_qty we can meet
        # 2. Among those, pick lowest price
        # 3. If tie on price, pick shortest lead time
        meetable = [v for v in vendors if v["min_qty"] <= qty_needed]

        if meetable:
            recommended = min(
                meetable,
                key=lambda v: (v["price"], v["lead_time_days"])
            )
        else:
            # No vendor meets our min_qty requirement
            # Still recommend the cheapest overall so team knows who to negotiate with
            recommended = min(
                vendors,
                key=lambda v: (v["price"], v["lead_time_days"])
            )

        return vendors, recommended["vendor_name"]

    def get_vendor_lead_times(
        self,
        product_name: str,
        qty: float = 1.0,
    ):
        """
        For a finished product, explodes the full BOM and returns
        all vendors + lead times for every raw material component.
        Flags components that have no vendor configured in Odoo.

        product_name -- full or partial name or internal reference
        qty          -- how many finished units you want to build (default 1)
        """
        try:
            params = VendorInput(product_name=product_name, qty=qty)
            product_name = params.product_name
            qty = params.qty
        except ValueError as e:
            return {"error": str(e)}

        logger.info(
            f"get_vendor_lead_times called: product='{product_name}' qty={qty}"
        )
        try:

            # Step 1: Explode the BOM to get all raw materials
            explosion = self.explode_bom_multilevel(product_name, qty)

            if not explosion["found"]:
                return {
                    "found": False,
                    "product_name": product_name,
                    "message": explosion["message"],
                    "components": [],
                }

            # Step 2: For each raw material, fetch vendor info
            components = []
            no_vendor_count = 0

            for item in explosion["raw_materials"]:
                vendors, recommended = self._get_vendor_info_for_product(
                    item["product_id"],
                    item["qty_needed"],
                )

                has_vendor = len(vendors) > 0
                if not has_vendor:
                    no_vendor_count += 1

                components.append({
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "qty_needed": item["qty_needed"],
                    "uom": item["uom"],
                    "has_vendor": has_vendor,
                    "recommended_vendor": recommended,
                    "vendors": vendors,
                })

            logger.info(
                f"get_vendor_lead_times complete: '{explosion['finished_product']}' "
                f"qty={qty} -> {len(components)} components, "
                f"{no_vendor_count} missing vendors"
            )

            return {
                "found": True,
                "finished_product": explosion["finished_product"],
                "qty_requested": qty,
                "total_components": len(components),
                "no_vendor_count": no_vendor_count,
                "components": components,
            }

        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo fault in get_vendor_lead_times: {e}")
            return {"error": f"Odoo rejected the request: {str(e)}"}
        except socket.timeout:
            logger.error("Timeout in get_vendor_lead_times")
            return {"error": "Odoo took too long to respond. Please try again."}
        except Exception as e:
            logger.error(f"Unexpected error in get_vendor_lead_times: {e}")
            return {"error": f"Unexpected error: {str(e)}"}
            
    def explain_bom(
        self,
        product_name: str,
        qty: float = 1.0,
    ):
        """
        Returns a plain-English explanation of the top-level BOM for a product.
        Shows which components are sub-assemblies (have their own BOM)
        and which are raw materials (no BOM, bought directly).

        product_name -- full or partial name or internal reference
        qty          -- how many finished units (default 1)
        """
        try:
            params = BomInput(product_name=product_name, qty=qty)
            product_name = params.product_name
            qty = params.qty
        except ValueError as e:
            return {"error": str(e)}

        logger.info(f"explain_bom called: product='{product_name}' qty={qty}")

        try:
            # Step 1: Find the top-level BOM
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
                    "components": [],
                }

            bom = bom_records[0]
            bom_id = bom["id"]
            finished_product = bom["product_tmpl_id"][1]
            produces_qty = bom["product_qty"]
            uom = bom["product_uom_id"][1]

            # Step 2: Fetch direct component lines (one level only)
            bom_lines = self.connection.execute_kw(
                "mrp.bom.line",
                "search_read",
                [[["bom_id", "=", bom_id]]],
                {
                    "fields": [
                        "product_id",
                        "product_qty",
                        "product_uom_id",
                    ]
                },
            )

            if not bom_lines:
                return {
                    "found": True,
                    "finished_product": finished_product,
                    "produces_qty": produces_qty,
                    "uom": uom,
                    "message": "BOM exists but has no components.",
                    "total_components": 0,
                    "sub_assembly_count": 0,
                    "raw_material_count": 0,
                    "components": [],
                }

            # Step 3: For each component, check if it has its own BOM
            # If it does -> sub-assembly. If not -> raw material.
            components = []
            sub_assembly_count = 0
            raw_material_count = 0

            for line in bom_lines:
                comp_product_id = line["product_id"][0]   # numeric ID
                comp_name = line["product_id"][1]          # display name
                comp_qty = line["product_qty"] * qty       # scaled by requested qty
                comp_uom = line["product_uom_id"][1]

                # Check if this component has its own BOM
                sub_bom = self._get_bom_for_product_id(comp_product_id)
                is_sub_assembly = sub_bom is not None

                if is_sub_assembly:
                    sub_assembly_count += 1
                    component_type = "sub_assembly"
                else:
                    raw_material_count += 1
                    component_type = "raw_material"

                components.append({
                    "product_id": comp_product_id,
                    "product_name": comp_name,
                    "qty_needed": round(comp_qty, 4),
                    "uom": comp_uom,
                    "type": component_type,
                })

            logger.info(
                f"explain_bom complete: '{finished_product}' has "
                f"{len(components)} components "
                f"({sub_assembly_count} sub-assemblies, {raw_material_count} raw materials)"
            )

            return {
                "found": True,
                "finished_product": finished_product,
                "produces_qty": produces_qty,
                "uom": uom,
                "qty_requested": qty,
                "total_components": len(components),
                "sub_assembly_count": sub_assembly_count,
                "raw_material_count": raw_material_count,
                "summary": (
                    f"'{finished_product}' has {len(components)} direct components: "
                    f"{sub_assembly_count} sub-assemblies (each has its own BOM) "
                    f"and {raw_material_count} raw materials (bought directly)."
                ),
                "components": components,
            }

        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo fault in explain_bom: {e}")
            return {"error": f"Odoo rejected the request: {str(e)}"}
        except socket.timeout:
            logger.error("Timeout in explain_bom")
            return {"error": "Odoo took too long to respond. Please try again."}
        except Exception as e:
            logger.error(f"Unexpected error in explain_bom: {e}")
            return {"error": f"Unexpected error: {str(e)}"}
    
    def what_can_i_build_today(self):
        """
        Scans all products that have a BOM in Odoo.
        For each product, runs a full shortage check.
        Returns two lists:
          - can_build: products with zero shortages (all parts in stock)
          - cannot_build: products with at least one shortage

        No arguments needed -- scans everything automatically.
        """
        logger.info("what_can_i_build_today called")

        try:
            # Step 1: Fetch all BOMs (just the product name, no lines needed)
            bom_records = self.connection.execute_kw(
                "mrp.bom",
                "search_read",
                [[]],   # empty domain = fetch ALL BOMs
                {
                    "fields": [
                        "id",
                        "product_tmpl_id",
                        "product_qty",
                        "product_uom_id",
                    ],
                },
            )

            if not bom_records:
                return {
                    "total_products_checked": 0,
                    "can_build": [],
                    "cannot_build": [],
                    "message": "No BOMs found in Odoo.",
                }

            can_build = []
            cannot_build = []

            # Step 2: For each BOM, run a shortage check
            for bom in bom_records:
                finished_product = bom["product_tmpl_id"][1]  # product display name
                produces_qty = bom["product_qty"]
                uom = bom["product_uom_id"][1]

                shortage_result = self.get_shortage_report(
                    product_name=finished_product,
                    qty=produces_qty,
                )

                # If error (e.g. Odoo timeout on one product), skip it
                if "error" in shortage_result:
                    logger.warning(
                        f"Skipping '{finished_product}' due to error: "
                        f"{shortage_result['error']}"
                    )
                    continue

                entry = {
                    "product_name": finished_product,
                    "produces_qty": produces_qty,
                    "uom": uom,
                    "total_raw_materials": shortage_result.get("total_raw_materials", 0),
                    "shortage_count": shortage_result.get("shortage_count", 0),
                }

                if shortage_result["shortage_count"] == 0:
                    can_build.append(entry)
                else:
                    cannot_build.append(entry)

            logger.info(
                f"what_can_i_build_today complete: "
                f"{len(can_build)} can build, {len(cannot_build)} cannot build"
            )

            return {
                "total_products_checked": len(can_build) + len(cannot_build),
                "can_build_count": len(can_build),
                "cannot_build_count": len(cannot_build),
                "can_build": can_build,
                "cannot_build": cannot_build,
            }

        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo fault in what_can_i_build_today: {e}")
            return {"error": f"Odoo rejected the request: {str(e)}"}
        except socket.timeout:
            logger.error("Timeout in what_can_i_build_today")
            return {"error": "Odoo took too long to respond. Please try again."}
        except Exception as e:
            logger.error(f"Unexpected error in what_can_i_build_today: {e}")
            return {"error": f"Unexpected error: {str(e)}"}