from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from .data_governance import resolve_promotion_exception
from .operational import make_operational_engine
from .parsers import read_records


BATCH_KEY = "HISTORY-D7AB786EB3D6-A42462C335C2"
ACTOR = "exception-resolver:verified-evidence-2026-09-14"
SALES = {
    180: ("AK2026-03607", 7),
    181: ("AK2026-03608", 1),
    182: ("AK2026-03609", 3),
}
SALE_LINE_EXCEPTIONS = {
    1: ("AK2026-03609", "92056"), 2: ("AK2026-03609", "92057"),
    3: ("AK2026-03609", "92326"), 4: ("AK2026-03608", "92965"),
    5: ("AK2026-03607", "92212"), 6: ("AK2026-03607", "92222"),
    7: ("AK2026-03607", "76116"), 8: ("AK2026-03607", "76118"),
    9: ("AK2026-03607", "93439"), 10: ("AK2026-03607", "92336"),
    11: ("AK2026-03607", "93293"),
}
TAX_EXCEPTIONS = {
    103: ("purchase", "PO2026/0456"),
    104: ("sale", "AK2026-03609"),
    105: ("sale", "AK2026-03608"),
    106: ("sale", "AK2026-03607"),
}
FINANCIAL_SETTLEMENT_EXCEPTIONS = {
    "AK2026-03599": (66, 107),
    "AK2026-03468": (67, 108),
    "AK2026-03465": (68, 109),
}
RETURN_LINE_RELATIONSHIP_EXCEPTIONS = {
    12: {"source_line_id": 10, "direction": "purchase", "return_document": "2026/0004",
         "parent_document": "PO2026/0078", "product_name": "MW Container Black W/Lid - RO16 (50pcs x 3pkt)",
         "sku": "92142", "return_quantity": "0.00", "return_subtotal": "0.00"},
    13: {"source_line_id": 23, "direction": "purchase", "return_document": "2026/0004",
         "parent_document": "PO2026/0078", "product_name": "PP Cup 75cc White W/Lid - 1500pcs (100pcs x 15pkt)",
         "sku": "78769", "return_quantity": "0.00", "return_subtotal": "0.00"},
    14: {"source_line_id": 30, "direction": "purchase", "return_document": "2026/0003",
         "parent_document": "PO2026/0155", "product_name": "Aluminium Foil Wrapall - 30cm 1kg (1x6)",
         "sku": "92882", "return_quantity": "3.00", "return_subtotal": "246.00"},
    15: {"source_line_id": 34, "direction": "purchase", "return_document": "2026/0003",
         "parent_document": "PO2026/0155", "product_name": "Maxi Roll, EMB, PP(1x6 Pcs)",
         "sku": "92058", "return_quantity": "0.00", "return_subtotal": "0.00"},
    16: {"source_line_id": 35, "direction": "purchase", "return_document": "2026/0003",
         "parent_document": "PO2026/0155", "product_name": "Sandwich Paper Printed 5kg (1x5 Packs)",
         "sku": "92899", "return_quantity": "0.00", "return_subtotal": "0.00"},
    17: {"source_line_id": 39, "direction": "purchase", "return_document": "2026/0001",
         "parent_document": "PO2026/0154", "product_name": "Maxi Roll, EMB, PP(1x6 Pcs)",
         "sku": "92058", "return_quantity": "0.00", "return_subtotal": "0.00"},
    18: {"source_line_id": 41, "direction": "purchase", "return_document": "2026/0001",
         "parent_document": "PO2026/0154", "product_name": "Aluminium Foil Wrapall - 30cm 1kg (1x6)",
         "sku": "92882", "return_quantity": "5.00", "return_subtotal": "425.00"},
    19: {"source_line_id": 60, "direction": "sale", "return_document": "CN2026/0025",
         "parent_document": "AK2026-02777", "product_name": "Paper Cup 6.5Oz 250gsm - IHC-(50x20 Pkt)",
         "sku": "93405", "return_quantity": "1.00", "return_subtotal": "48.00"},
    20: {"source_line_id": 79, "direction": "sale", "return_document": "AK2026-01159",
         "parent_document": "AK2026-01159", "product_name": "Sandwich Paper Printed 7kg",
         "sku": "78532", "return_quantity": "1.00", "return_subtotal": "38.00"},
    21: {"source_line_id": 82, "direction": "sale", "return_document": "CN2026/0006",
         "parent_document": "AK2026-00287", "product_name": "Lids - Paper Cup 6Oz-(1x20 Pack)",
         "sku": "6297000993072", "return_quantity": "1.00", "return_subtotal": "41.00"},
}
PAYMENT_PARENT_RELATIONSHIP_EXCEPTIONS = {
    23: {"source_payment_id": 92, "direction": "purchase", "payment_reference": "PP2026/0346",
         "parent_document": "PO2026/0339", "party_name": "Al Hilal Trading LLC",
         "paid_on": "08/18/2026 08:13", "method": "Bank Transfer", "amount": "231.00",
         "settlement_exception_id": 128},
    24: {"source_payment_id": 94, "direction": "purchase", "payment_reference": "PP2026/0340",
         "parent_document": "PO2026/0339", "party_name": "Luzan Packing & Packaging Materials Trading Co. LLC",
         "paid_on": "08/17/2026 10:37", "method": "Cash", "amount": "195.00",
         "settlement_exception_id": 129},
    25: {"source_payment_id": 932, "direction": "sale", "payment_reference": "SP2026/3240",
         "parent_document": "AK2026-03080", "party_name": "Al jerf cafeteriaNaushad",
         "paid_on": "08/25/2026 11:53", "method": "Cash", "amount": "83.00",
         "settlement_exception_id": 114},
}
RETURN_DUE_SETTLEMENT_EXCEPTIONS = {
    113: {"invoice": "AK2026-03132", "return_document": "CN2026/0030",
          "payment_references": ("SP2026/3293",), "net_total": "0.05",
          "payment_total": "35.50", "return_due": "35.45", "return_total": "35.70",
          "original_gross": "35.75"},
    118: {"invoice": "AK2026-02182", "return_document": "AK2026-02182",
          "payment_references": ("SP2026/2497", "SP2026/2550"), "net_total": "31.50",
          "payment_total": "31.75", "return_due": "0.25", "return_total": "336.00",
          "original_gross": "367.50"},
    119: {"invoice": "AK2026-02044", "return_document": "CN2026/0014",
          "payment_references": ("SP2026/2224",), "net_total": "58.85",
          "payment_total": "60.00", "return_due": "1.15", "return_total": "55.65",
          "original_gross": "114.50"},
    120: {"invoice": "AK2026-01619", "return_document": "CN2026/0009",
          "payment_references": ("SP2026/1755",), "net_total": "159.16",
          "payment_total": "162.00", "return_due": "2.84", "return_total": "62.8425",
          "original_gross": "222.00"},
    124: {"invoice": "AK2026-00287", "return_document": "CN2026/0006",
          "payment_references": ("SP2026/0510",), "net_total": "47.45",
          "payment_total": "90.00", "return_due": "42.55", "return_total": "43.05",
          "original_gross": "90.50"},
}
LATER_PAYMENT_SETTLEMENT_EXCEPTIONS = {
    116: {"invoice": "AK2026-02571", "payment_references": (
        "SP2026/3612", "SP2026/3656", "SP2026/3762"),
        "total": "287.75", "paid": "250.00", "due": "37.75"},
}
FULL_RETURN_ALLOCATION_EXCEPTIONS = {
    110: {"invoice": "AK2026-03285", "return_document": "CN2026/0035",
          "original_gross": "70.25", "return_total": "70.35", "net_total": "-0.10"},
    111: {"invoice": "AK2026-03146", "return_document": "CN2026/0031",
          "original_gross": "25.25", "return_total": "25.20", "net_total": "0.05"},
    112: {"invoice": "AK2026-03132", "return_document": "CN2026/0030",
          "original_gross": "35.75", "return_total": "35.70", "net_total": "0.05"},
    115: {"invoice": "AK2026-02927", "return_document": "CN2026/0026",
          "original_gross": "48.25", "return_total": "48.30", "net_total": "-0.05"},
    117: {"invoice": "AK2026-02445", "return_document": "CN2026/0019",
          "original_gross": "30.50", "return_total": "30.45", "net_total": "0.05"},
    121: {"invoice": "AK2026-01159", "return_document": "AK2026-01159",
          "original_gross": "40.00", "return_total": "39.90", "net_total": "0.10"},
    122: {"invoice": "AK2026-00985", "return_document": "CN2026/0001",
          "original_gross": "66.25", "return_total": "66.15", "net_total": "0.10"},
}
PURCHASE_RETURN_ALLOCATION_EXCEPTIONS = {
    130: {"purchase": "PO2026/0243", "return_document": "2026/0012",
          "line_total": "250.00", "tax_base": "620.00", "vat": "31.00",
          "return_total": "388.50", "line_gap": "370.00"},
    131: {"purchase": "PO2026/0224", "return_document": "2026/0009",
          "line_total": "2620.50", "tax_base": "2747.50", "vat": "137.38",
          "return_total": "133.35", "line_gap": "127.00"},
    132: {"purchase": "PO2026/0155", "return_document": "2026/0003",
          "line_total": "1595.50", "tax_base": "1841.50", "vat": "92.08",
          "return_total": "258.30", "line_gap": "246.00"},
    133: {"purchase": "PO2026/0154", "return_document": "2026/0001",
          "line_total": "1247.50", "tax_base": "1672.50", "vat": "83.63",
          "return_total": "446.25", "line_gap": "425.00"},
    135: {"purchase": "PO2026/0078", "return_document": "2026/0004",
          "line_total": "7381.01", "tax_base": "7443.01", "vat": "371.40",
          "return_total": "65.10", "line_gap": "62.00"},
}
GROSS_COST_JOURNAL_EXCEPTIONS = {
    160: {"purchase": "PO2026/0233", "total": "100.00"},
    161: {"purchase": "PO2026/0227", "total": "109.60"},
    163: {"purchase": "PO2026/0133", "total": "80.00"},
    164: {"purchase": "PO2026/0037", "total": "170.00"},
}
# These source purchases have complete lines and a header exactly 5% above the
# item subtotal, but no captured input-tax row.  Preserve them at gross cost;
# do not manufacture a recoverable VAT claim.
INFERRED_GROSS_COST_ALLOCATION_EXCEPTIONS = {
    125: ("PO2026/0454", "1590.00", "79.50", "1669.50"),
    126: ("PO2026/0433", "1700.00", "85.00", "1785.00"),
    127: ("PO2026/0432", "450.00", "22.50", "472.50"),
}
RETURN_SETTLEMENT_CASH_FLOW_EXCEPTIONS = {
    136: {"direction": "sale", "payment_reference": "SP2026/0128",
          "return_document": "AK2026-00093", "parent_document": "AK2026-00093",
          "party_name": "Tasty corner, X", "return_date": "04/30/2026 16:19",
          "cash_date": "04/30/2026 05:59", "method": "Cash", "amount": "31.50",
          "status": "Paid", "cash_direction": "Debit"},
    137: {"direction": "purchase", "payment_reference": "PP2026/0229",
          "return_document": "2026/0001", "parent_document": "PO2026/0154",
          "party_name": "Zain Pack Plastic Trading LLC", "return_date": "06/27/2026 15:15",
          "cash_date": "07/27/2026 17:44", "method": "Cash", "amount": "446.25",
          "status": "Received", "cash_direction": "Credit"},
    138: {"direction": "purchase", "payment_reference": "PP2026/0361",
          "return_document": "2026/0010", "parent_document": "",
          "party_name": "Eazy Pack Plastic Products L.L.C", "return_date": "08/20/2026 18:09",
          "cash_date": "08/20/2026 18:28", "method": "Cash", "amount": "813.75",
          "status": "Received", "cash_direction": "Credit"},
    139: {"direction": "purchase", "payment_reference": "PP2026/0370",
          "return_document": "2026/0012", "parent_document": "PO2026/0243",
          "party_name": "Al Hessa Star Plastics Trading L.L.C", "return_date": "08/26/2026 15:39",
          "cash_date": "08/26/2026 15:39", "method": "Cash", "amount": "388.50",
          "status": "Received", "cash_direction": "Credit"},
}
PAYMENT_REGISTER_WITHOUT_CASH_FLOW_EXCEPTIONS = {
    140: {"direction": "purchase", "payment_reference": "PP2026/0001",
          "parent_document": "PO2026/0010", "party_name": "Real Detergent & Disinfectants Industry LLC",
          "paid_on": "04/08/2026 01:19", "method": "Cash", "amount": "1476.80"},
    142: {"direction": "purchase", "payment_reference": "PP2026/0007",
          "parent_document": "PO2026/0007", "party_name": "Oman Plastic LLC",
          "paid_on": "04/06/2026 01:22", "method": "Cash", "amount": "472.50"},
    143: {"direction": "purchase", "payment_reference": "PP2026/0004",
          "parent_document": "PO2026/0011", "party_name": "Uni Chem Detergent Industry LLC",
          "paid_on": "04/06/2026 01:21", "method": "Cash", "amount": "132.30"},
    144: {"direction": "purchase", "payment_reference": "PP2026/0005",
          "parent_document": "PO2026/0009", "party_name": "Shalimar Chemicals Trading LLC",
          "paid_on": "04/06/2026 01:21", "method": "Cash", "amount": "18.90"},
    145: {"direction": "purchase", "payment_reference": "PP2026/0006",
          "parent_document": "PO2026/0008", "party_name": "Euroclean General Trading LLC",
          "paid_on": "04/06/2026 01:21", "method": "Cash", "amount": "566.00"},
    146: {"direction": "sale", "payment_reference": "SP2026/1087",
          "parent_document": "AK2026-01088", "party_name": "AL RAWDHA AL KHADHRA CAFETERIA X",
          "paid_on": "06/19/2026 15:59", "method": "Cash", "amount": "235.25"},
    147: {"direction": "sale", "payment_reference": "SP2026/1022",
          "parent_document": "AK2026-01028", "party_name": "Layali Al Salihiah Cafeteria X",
          "paid_on": "06/17/2026 17:09", "method": "Cash", "amount": "38.75"},
    148: {"direction": "sale", "payment_reference": "SP2026/0902",
          "parent_document": "AK2026-00895", "party_name": "Alam Al Noor Cafeteria - Al Taza",
          "paid_on": "06/12/2026 16:10", "method": "Cash", "amount": "177.00"},
    149: {"direction": "sale", "payment_reference": "SP2026/0021",
          "parent_document": "AK2026-00016", "party_name": "Al Nahda Restaurent",
          "paid_on": "04/14/2026 06:57", "method": "Cash", "amount": "28.35"},
}

INVENTORY_MOVEMENT_UOM_EXCEPTIONS = {
    37: (9530, "purchase", "2026/0012", "Sandwich Wedge Clear Single (125 x 8 Pkt)", "93366", "1.00", "Carton", "Carton", "1", "identity"),
    38: (9531, "purchase", "2026/0012", "Kraft Burger Box HB-2 (1x250pcs)", "93447", "2.00", "Carton", "Carton", "1", "identity"),
    39: (9532, "purchase", "2026/0009", "MW Container Corepack Black W/Lid - RE24 (50pcs x 3pkt)", "93394", "1.00", "Carton(1x150)-RE/RO", "Pack", "3", "unit_registry"),
    40: (9533, "purchase", "2026/0009", "Paper Cup 6.5Oz 250gsm-(50x20 Pkt)", "77229", "2.00", "Carton", "Pack", "20", "x20pkt"),
    41: (9534, "purchase", "2026/0004", "Kraft Bag Brown Medium with Twist Handle 250 Pcs", "92148", "1.00", "Carton", "Carton", "1", "identity"),
    42: (9535, "purchase", "2026/0003", "Aluminium Foil Wrapall - 30cm 1kg (1x6)", "92882", "3.00", "CTN(1x6)", "Pieces", "6", "unit_registry"),
    43: (9536, "purchase", "2026/0001", "Aluminium Foil Wrapall - 30cm 1kg (1x6)", "92882", "5.00", "CTN(1x6)", "Pieces", "6", "unit_registry"),
    44: (9543, "sale", "CN2026/0037", "PP Bowls 350cc Star White W/Lid (50pcs x 20pkt)", "93439", "1.00", "Carton", "Pack", "20", "x20pkt"),
    45: (9555, "sale", "CN2026/0025", "Paper Cup 6.5Oz 250gsm - IHC-(50x20 Pkt)", "93405", "1.00", "Carton", "Pack", "20", "x20pkt"),
    46: (9561, "sale", "CN2026/0019", "Dish Wash Neo 5Ltr - Lemon-(1x4pcs)", "93293", "1.00", "ctn", "Pieces", "4", "1x4pcs"),
    47: (9564, "sale", "CN2026/0017", "Aluminium Container 8389(125x8pkt)", "P120101083890", "0.75", "Carton", "Pack", "8", "x8pkt"),
    48: (9566, "sale", "CN2026/0016", "Floor Cleaner 5Ltr - Lavender-(1x4pcs)", "6299532702818", "1.00", "Carton", "Pieces", "4", "1x4pcs"),
    49: (9567, "sale", "CN2026/0015", "Plastic Spoon - Black HD-(1x40 Pack)", "92077", "0.53", "Carton", "Pack", "40", "1x40pack"),
    51: (9574, "sale", "AK2026-01159", "Sandwich Paper Printed 7kg", "78532", "1.00", "Carton", "Carton", "1", "identity"),
    52: (9575, "sale", "CN2026/0008", "Plastic Spoon - Black HD-(1x40 Pack)", "92077", "1.00", "Carton", "Pack", "40", "1x40pack"),
    53: (9577, "sale", "CN2026/0006", "Lids - Paper Cup 6Oz-(1x20 Pack)", "6297000993072", "1.00", "Carton", "Pack", "20", "1x20pack"),
    54: (9583, "sale", "AK2026-00799", "Floor Cleaner 5Ltr - Lavender-(1x4pcs)", "6299532702818", "1.00", "Carton", "Pieces", "4", "1x4pcs"),
    55: (9584, "sale", "AK2026-00093", "Interfold - 150 Sheets-(1x20pcs)", "75530", "1.00", "ctn", "Pieces", "20", "1x20pcs"),
    58: (9683, "transfer_out", "ST2026/0913", "Foam Cup Upack 6oz -(50pcsx20pkt)", "93404", "100.00", "Carton (20 Pack)", "Carton", "1", "identity_family"),
    59: (9684, "transfer_in", "ST2026/0913", "Foam Cup Upack 6oz -(50pcsx20pkt)", "93404", "100.00", "Carton (20 Pack)", "Carton", "1", "identity_family"),
    60: (13895, "transfer_out", "ST2026/0498", "Foam Cup Upack 6oz -(50pcsx20pkt)", "93404", "100.00", "Carton (20 Pack)", "Carton", "1", "identity_family"),
    61: (13896, "transfer_in", "ST2026/0498", "Foam Cup Upack 6oz -(50pcsx20pkt)", "93404", "100.00", "Carton (20 Pack)", "Carton", "1", "identity_family"),
    62: (15423, "transfer_out", "ST2026/0327", "Sponge (1x12 Pcs)-10 Pack", "92875", "12.00", "Carton (12 Pc(s))", "Pack", "10", "10pack"),
    63: (15424, "transfer_in", "ST2026/0327", "Sponge (1x12 Pcs)-10 Pack", "92875", "12.00", "Carton (12 Pc(s))", "Pack", "10", "10pack"),
}

# The operational review queue retains its own exception identifiers.  These
# mappings bind each queue item to one or more independently checksum-verified
# financial reconciliations built below; they do not post or alter source data.
FINANCIAL_DOCUMENT_REVIEW_EVIDENCE = {
    69: (110,), 70: (111,), 71: (112, 113), 72: (114,), 73: (115,),
    74: (116,), 75: (117,), 76: (118,), 77: (119,), 78: (120,),
    79: (121,), 80: (122,), 82: (124,), 86: (128,), 87: (129,),
    88: (130,), 89: (131,), 90: (132,), 91: (133,), 93: (135,),
}

# These legacy blueprint controls are superseded by the separately approved
# checksum-bound opening-stock import.  The import keeps negative stock in a
# quarantine table and does not authorize posting.
OPENING_STOCK_BLOCKED_EVIDENCE = (165, 166, 167, 168, 169)

# Source labels such as Carton and Pack have multiple valid package sizes.  The
# ERP therefore forbids a global conversion for them and requires a captured
# product-specific factor on every stock-affecting line.
UOM_REGISTRY_CONFLICT_ALIASES = {
    94: ("bundle", 6),
    95: ("carton", 25),
    96: ("kg", 2),
    97: ("pack", 4),
    98: ("piece", 6),
}

# Ambiguous staging links can be resolved only where separately captured
# payment or return-line evidence establishes one unique parent/product.
AMBIGUOUS_RELATIONSHIP_EVIDENCE = {
    183: (23, 128),
    184: (24, 129),
    185: (25, 114),
    186: (12,),
    187: (16,),
}
JOURNAL_BLUEPRINT_GROSS_COST_EVIDENCE = {
    157: (125,),
    158: (126,),
    159: (127,),
}
NEGATIVE_STOCK_QUARANTINE_EVIDENCE = {
    172: ("75613", "SHJ", "-2.00", "Pack", "6.93"),
    173: ("93058", "Asas General Trading LLC", "-5.00", "Bundle", "56.70"),
    174: ("93456", "Asas General Trading LLC", "-5.00", "Pack", "4.81"),
    175: ("94821", "Asas General Trading LLC", "-1.00", "Carton", "39.90"),
}
UOM_CONVERSION_GROUP_EVIDENCE = {
    99: (40, 44, 45, 47, 49),
    100: (46, 48, 54, 55),
    101: (62, 63),
    102: (58, 59, 60, 61),
}
ZERO_QUANTITY_LOCATIONLESS_STOCK_EVIDENCE = {176: "92659", 177: "98024"}


def resolution_code(exception_id: int) -> str:
    if exception_id in ZERO_QUANTITY_LOCATIONLESS_STOCK_EVIDENCE:
        return "ZERO_QUANTITY_LOCATIONLESS_STOCK_EXCLUDED"
    if exception_id in UOM_CONVERSION_GROUP_EVIDENCE:
        return "PRODUCT_SPECIFIC_UOM_CONVERSION_GROUP_RECONCILED"
    if exception_id in NEGATIVE_STOCK_QUARANTINE_EVIDENCE:
        return "NEGATIVE_STOCK_QUARANTINED_NOT_AVAILABLE"
    if exception_id in JOURNAL_BLUEPRINT_GROSS_COST_EVIDENCE:
        return "GROSS_COST_JOURNAL_BLUEPRINT_CLASSIFIED"
    if exception_id in INFERRED_GROSS_COST_ALLOCATION_EXCEPTIONS:
        return "GROSS_COST_ALLOCATION_WITH_UNCLAIMED_VAT_CLASSIFIED"
    if exception_id in AMBIGUOUS_RELATIONSHIP_EVIDENCE:
        return "MULTI_FIELD_AMBIGUOUS_RELATIONSHIP_RESOLVED"
    if exception_id in UOM_REGISTRY_CONFLICT_ALIASES:
        return "GLOBAL_UOM_ALIAS_BLOCKED_PRODUCT_SPECIFIC_FACTORS_REQUIRED"
    if exception_id in OPENING_STOCK_BLOCKED_EVIDENCE:
        return "OPENING_STOCK_APPROVED_RECONCILED_IMPORT"
    if exception_id in FINANCIAL_DOCUMENT_REVIEW_EVIDENCE:
        return "FINANCIAL_DOCUMENT_REVIEW_RECONCILED"
    if exception_id in PAYMENT_REGISTER_WITHOUT_CASH_FLOW_EXCEPTIONS:
        return "NONPOSTING_PAYMENT_REGISTER_SETTLEMENT_PRESERVED"
    if exception_id in RETURN_SETTLEMENT_CASH_FLOW_EXCEPTIONS:
        return "RETURN_REGISTER_EMBEDDED_SETTLEMENT_PROVEN"
    if exception_id in GROSS_COST_JOURNAL_EXCEPTIONS:
        return "GROSS_COST_JOURNAL_WITHOUT_INPUT_VAT_APPROVED"
    if exception_id == 151:
        return "HIERARCHICAL_TRIAL_BALANCE_AGGREGATION_CLASSIFIED"
    if exception_id == 152:
        return "NON_ATOMIC_ACCOUNT_CAPTURE_DRIFT_RECONCILED"
    if exception_id in FULL_RETURN_ALLOCATION_EXCEPTIONS:
        return "SALES_RETURN_NET_ALLOCATION_RECONCILED"
    if exception_id in PURCHASE_RETURN_ALLOCATION_EXCEPTIONS:
        return "PURCHASE_RETURN_LINE_GAP_RECONCILED"
    if exception_id in RETURN_DUE_SETTLEMENT_EXCEPTIONS:
        return "SALES_RETURN_DUE_SETTLEMENT_RECONCILED"
    if exception_id in LATER_PAYMENT_SETTLEMENT_EXCEPTIONS:
        return "LATER_PAYMENT_SETTLEMENT_RECONCILED"
    if exception_id in {expected["settlement_exception_id"]
                        for expected in PAYMENT_PARENT_RELATIONSHIP_EXCEPTIONS.values()}:
        return "PAYMENT_PARENT_SETTLEMENT_RECONCILED"
    if exception_id in PAYMENT_PARENT_RELATIONSHIP_EXCEPTIONS:
        return "PAYMENT_PARENT_MULTI_FIELD_MATCH_PROVEN"
    if exception_id == 22:
        return "TRANSFER_LINE_RELATIONSHIP_PROVEN"
    if exception_id in RETURN_LINE_RELATIONSHIP_EXCEPTIONS:
        if Decimal(RETURN_LINE_RELATIONSHIP_EXCEPTIONS[exception_id]["return_quantity"]) == 0:
            return "ZERO_QUANTITY_RETURN_PLACEHOLDER_CLASSIFIED"
        return "RETURN_LINE_PRODUCT_RELATIONSHIP_PROVEN"
    if exception_id in {value for pair in FINANCIAL_SETTLEMENT_EXCEPTIONS.values() for value in pair}:
        return "LATER_CAPTURE_SETTLEMENT_RECONCILED"
    if 26 <= exception_id <= 36 or exception_id in {56, 57}:
        return "DETERMINISTIC_MOVEMENT_MAPPING_PROVEN"
    if exception_id in INVENTORY_MOVEMENT_UOM_EXCEPTIONS:
        return "PRODUCT_SPECIFIC_UOM_MOVEMENT_PROVEN"
    if exception_id in TAX_EXCEPTIONS:
        return "TAX_DOCUMENT_RELATIONSHIP_PROVEN"
    if exception_id in SALE_LINE_EXCEPTIONS:
        return "TRANSACTION_LINE_PARENT_PROVEN"
    return "LATER_CAPTURE_RELATIONSHIP_PROVEN"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def money(value: str) -> Decimal:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    return Decimal(cleaned or "0")


def first_money(value: str) -> Decimal:
    match = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?", value or "")
    return Decimal(match.group(0).replace(",", "")) if match else Decimal("0")


def normalized_document(value: str) -> str:
    return (value or "").replace("\xa0", "").strip()


def quantity(value: str) -> Decimal:
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", value or "")
    return Decimal(match.group(0)) if match else Decimal("0")


def normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def build_resolution_evidence(source_root: Path) -> dict[int, dict]:
    frozen = source_root / "2026-09-10-frozen-browser-cutover"
    sales_path = frozen / "sales_last_30_days.csv"
    lines_path = frozen / "details" / "sales_product_lines_current_business_day.csv"
    transfers_path = frozen / "stock_transfers_2026.csv"
    transfer_details_path = source_root / "2026-09-08" / "stock_transfer_details_0001_0050.json"
    products_path = frozen / "products.csv"
    stock_path = frozen / "details" / "stock_by_location.csv"
    status_path = frozen / "CAPTURE_STATUS.json"
    purchases_path = frozen / "purchases_2026.csv"
    tax_input_path = source_root / "2026-09-08" / "tax_input_2026.csv"
    tax_output_path = source_root / "2026-09-08" / "tax_output_2026.csv"
    purchase_returns_path = source_root / "2026-09-08" / "purchase_return_details.json"
    sales_returns_path = source_root / "2026-09-08" / "sales_return_details.json"
    purchase_lines_path = source_root / "2026-09-08" / "product_purchase_detail_2026.csv"
    source_products_path = source_root / "2026-09-08" / "products_all.csv"
    units_path = source_root / "2026-09-08" / "units.csv"
    detail_hashes_path = source_root / "2026-09-08" / "DETAIL_HASHES.sha256"
    purchase_payments_path = source_root / "2026-09-08" / "purchase_payments_2026.csv"
    sales_payments_path = source_root / "2026-09-08" / "sales_payments_2026.csv"
    cash_flow_path = source_root / "2026-09-08" / "cash_flow_2026-08-16_2026-08-31.csv"
    source_purchases_path = source_root / "2026-09-08" / "purchases_2026.csv"
    source_sales_path = source_root / "2026-09-08" / "sales_2026.csv"
    source_sales_returns_path = source_root / "2026-09-08" / "sales_returns_2026.csv"
    source_purchase_returns_path = source_root / "2026-09-08" / "purchase_returns_2026.csv"
    current_root = source_root / "2026-09-09-current-non-atomic"
    current_status_path = current_root / "CAPTURE_STATUS.json"
    current_sales_path = current_root / "sales_2026_current.csv"
    current_purchases_path = current_root / "purchases_2026_current.csv"
    current_sales_payments_path = current_root / "sales_payments_current.csv"
    current_purchase_payments_path = current_root / "purchase_payments_current.csv"
    frozen_sales_payments_path = frozen / "sales_payments_2026.csv"
    frozen_purchase_payments_path = frozen / "purchase_payments_2026.csv"
    trial_balance_path = source_root / "2026-09-08" / "trial_balance_2026.xlsx"
    payment_accounts_path = source_root / "2026-09-08" / "payment_accounts.csv"
    account_cash_flow_paths = sorted((source_root / "2026-09-08").glob("cash_flow_2026-*.csv"))

    status = json.loads(status_path.read_text(encoding="utf-8"))
    require(status.get("source_mutation") is False, "capture status does not prove read-only access")
    require(status.get("zero_drift_observed") is True, "capture status does not prove zero observed drift")
    declared_hashes = {item["file"]: item["sha256"].upper() for item in status["exports"]}
    for path in (sales_path, purchases_path, transfers_path, products_path):
        require(declared_hashes.get(path.name) == sha256(path), f"capture checksum mismatch: {path.name}")

    detail_hashes = {}
    for line in detail_hashes_path.read_text(encoding="utf-8").splitlines():
        checksum, filename = line.split(maxsplit=1)
        detail_hashes[filename.strip()] = checksum.upper()
    for path in (purchase_returns_path, sales_returns_path, transfer_details_path):
        require(detail_hashes.get(path.name) == sha256(path), f"detail checksum mismatch: {path.name}")

    sales_rows = rows(sales_path)
    line_rows = rows(lines_path)
    result: dict[int, dict] = {}

    trial_records = list(read_records(trial_balance_path))
    trial_data = [row for row in trial_records
                  if normalized_name(str(row.get("Trial Balance - Asas General Trading LLC") or "")) != "account"]
    trial_debit = sum((money(str(row.get("column_2") or "")) for row in trial_data), Decimal("0"))
    trial_credit = sum((money(str(row.get("column_3") or "")) for row in trial_data), Decimal("0"))
    trial_labels = [str(row.get("Trial Balance - Asas General Trading LLC") or "").strip()
                    for row in trial_data]
    ar_index = trial_labels.index("Accounts Receivable (A/R)")
    supplier_index = trial_labels.index("Suppliers")
    cash_index = trial_labels.index("Cash - ASAS Office")
    ar_parent = money(str(trial_data[ar_index].get("column_2") or ""))
    ar_child = money(str(trial_data[ar_index + 1].get("column_2") or ""))
    supplier_parent = money(str(trial_data[supplier_index].get("column_3") or ""))
    supplier_children_debit = sum(
        (money(str(row.get("column_2") or "")) for row in trial_data[supplier_index + 1:cash_index]),
        Decimal("0"),
    )
    supplier_children_credit = sum(
        (money(str(row.get("column_3") or "")) for row in trial_data[supplier_index + 1:cash_index]),
        Decimal("0"),
    )
    supplier_children_net = supplier_children_credit - supplier_children_debit
    require(trial_debit == Decimal("930029.02") and trial_credit == Decimal("862301.36"),
            "trial balance exported row totals differ")
    require(ar_parent == ar_child == Decimal("2551.60"),
            "trial balance does not prove the receivable parent/child duplication")
    require(supplier_parent == supplier_children_net == Decimal("38953.43"),
            "trial balance does not prove the supplier parent/detail duplication")
    result[151] = {
        "source_key": "TRIAL_BALANCE_EXPORTED_ROW_SUM",
        "relationship": "the export contains parent control rows and their detail rows, so summing every row double-counts account balances",
        "raw_row_debit_aed": f"{trial_debit:.2f}",
        "raw_row_credit_aed": f"{trial_credit:.2f}",
        "receivable_parent_aed": f"{ar_parent:.2f}",
        "receivable_child_aed": f"{ar_child:.2f}",
        "supplier_parent_aed": f"{supplier_parent:.2f}",
        "supplier_children_net_aed": f"{supplier_children_net:.2f}",
        "control_disposition": "invalid_hierarchical_row_sum_not_a_ledger_balance",
        "remaining_control": "TRIAL_BALANCE_UI_TOP_LEVEL remains quarantined",
        "files": {
            str(trial_balance_path.relative_to(source_root)): sha256(trial_balance_path),
        },
    }

    payment_account_rows = [row for row in rows(payment_accounts_path)
                            if normalized_name(row.get("Name", "")) != "total"]
    payment_balances = {row["Name"]: money(row["Balance"]) for row in payment_account_rows}
    cash_rows_current = [row for path in account_cash_flow_paths for row in rows(path)]
    cash_by_account: dict[str, list[dict[str, str]]] = {}
    for row in cash_rows_current:
        cash_by_account.setdefault(row["Account"], []).append(row)
    cash_closing = {
        account: money(account_rows[-1]["Account Balance"])
        for account, account_rows in cash_by_account.items()
    }
    common_accounts = set(payment_balances) & set(cash_closing)
    mismatched_accounts = {
        account for account in common_accounts
        if payment_balances[account] != cash_closing[account]
    }
    require(mismatched_accounts == {"Febin's Cash Account", "RAK 1 - Suveesh"},
            "unexpected payment-account/cash-flow mismatches")
    drift_rows: dict[str, dict] = {}
    for account in sorted(mismatched_accounts):
        account_rows = cash_by_account[account]
        matching_indexes = [index for index, row in enumerate(account_rows)
                            if money(row["Account Balance"]) == payment_balances[account]]
        require(matching_indexes, f"{account}: payment balance is absent from cash-flow history")
        matched_index = matching_indexes[-1]
        later_rows = account_rows[matched_index + 1:]
        later_net = sum(
            (money(row["Credit"]) - money(row["Debit"]) for row in later_rows),
            Decimal("0"),
        )
        closing = cash_closing[account]
        require(payment_balances[account] + later_net == closing,
                f"{account}: later cash-flow activity does not bridge the captured balance")
        drift_rows[account] = {
            "captured_payment_account_balance_aed": f"{payment_balances[account]:.2f}",
            "cash_flow_closing_balance_aed": f"{closing:.2f}",
            "later_cash_flow_net_aed": f"{later_net:.2f}",
            "later_cash_flow_rows": len(later_rows),
        }
    absent_accounts = set(payment_balances) - set(cash_closing)
    require(all(payment_balances[account] == 0 for account in absent_accounts),
            "a non-zero payment account is absent from cash flow")
    payment_total = sum(payment_balances.values(), Decimal("0"))
    cash_total = sum(cash_closing.values(), Decimal("0"))
    require(payment_total == Decimal("-131968.28")
            and cash_total == Decimal("-131594.78")
            and cash_total - payment_total == Decimal("373.50"),
            "payment-account capture drift total differs")
    result[152] = {
        "source_key": "PAYMENT_ACCOUNTS_TO_CASH_FLOW",
        "relationship": "the payment-account balances occur as intermediate cash-flow balances and later preserved receipts bridge exactly to the cash-flow closing balances",
        "payment_account_total_aed": f"{payment_total:.2f}",
        "cash_flow_closing_total_aed": f"{cash_total:.2f}",
        "later_activity_aed": f"{cash_total - payment_total:.2f}",
        "mismatched_accounts": drift_rows,
        "zero_balance_accounts_without_cash_rows": sorted(absent_accounts),
        "control_disposition": "non_atomic_capture_timing_reconciled",
        "files": {
            str(payment_accounts_path.relative_to(source_root)): sha256(payment_accounts_path),
            **{
                str(path.relative_to(source_root)): sha256(path)
                for path in account_cash_flow_paths
            },
        },
    }
    for exception_id, (invoice, expected_lines) in SALES.items():
        headers = [row for row in sales_rows if row["Invoice No."] == invoice]
        details = [row for row in line_rows if row["Invoice No."] == invoice]
        require(len(headers) == 1, f"{invoice}: expected one later-capture header, found {len(headers)}")
        require(len(details) == expected_lines, f"{invoice}: expected {expected_lines} lines, found {len(details)}")
        header_total = money(headers[0]["Total amount"])
        line_total = sum((money(row["Total"]) for row in details), Decimal("0"))
        require(header_total == line_total, f"{invoice}: header {header_total} != line total {line_total}")
        require(money(headers[0]["Total paid"]) + money(headers[0]["Sell Due"]) == header_total,
                f"{invoice}: payment allocation does not reconcile")
        result[exception_id] = {
            "source_key": invoice,
            "relationship": "later capture contains one matching header and all preserved sale lines",
            "header_rows": 1,
            "line_rows": len(details),
            "header_total_aed": str(header_total),
            "line_total_aed": str(line_total),
            "payment_status": headers[0]["Payment Status"],
            "paid_aed": str(money(headers[0]["Total paid"])),
            "due_aed": str(money(headers[0]["Sell Due"])),
            "files": {
                str(sales_path.relative_to(source_root)): sha256(sales_path),
                str(lines_path.relative_to(source_root)): sha256(lines_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }

    for invoice, exception_ids in FINANCIAL_SETTLEMENT_EXCEPTIONS.items():
        headers = [row for row in sales_rows if row["Invoice No."] == invoice]
        details = [row for row in line_rows if row["Invoice No."] == invoice]
        require(len(headers) == 1 and details, f"{invoice}: settlement evidence is incomplete")
        header = headers[0]
        header_total = money(header["Total amount"])
        paid_total = money(header["Total paid"])
        due_total = money(header["Sell Due"])
        return_due = money(header["Sell Return Due"])
        line_total = sum((money(row["Total"]) for row in details), Decimal("0"))
        require(header["Payment Status"] == "Paid", f"{invoice}: later status is not Paid")
        require(header_total == paid_total and due_total == 0 and return_due == 0,
                f"{invoice}: later settlement does not reconcile")
        require(line_total == header_total, f"{invoice}: line and header totals differ")
        evidence = {
            "source_key": invoice,
            "relationship": "later frozen register and preserved item lines prove a fully settled invoice",
            "payment_status": header["Payment Status"],
            "header_total_aed": str(header_total),
            "line_total_aed": str(line_total),
            "paid_aed": str(paid_total),
            "due_aed": str(due_total),
            "return_due_aed": str(return_due),
            "line_rows": len(details),
            "files": {
                str(sales_path.relative_to(source_root)): sha256(sales_path),
                str(lines_path.relative_to(source_root)): sha256(lines_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }
        for exception_id in exception_ids:
            result[exception_id] = evidence

    source_sales_rows = rows(source_sales_path)
    source_sales_returns = rows(source_sales_returns_path)
    source_sales_payments = rows(sales_payments_path)
    source_tax_outputs = rows(tax_output_path)
    allocation_sales_line_paths = sorted((source_root / "2026-09-08").glob("product_sales_detail*.csv"))
    allocation_sales_lines = [row for path in allocation_sales_line_paths for row in rows(path)]
    for exception_id, expected in FULL_RETURN_ALLOCATION_EXCEPTIONS.items():
        headers = [row for row in source_sales_rows
                   if normalized_document(row["Invoice No."]) == expected["invoice"]]
        returns = [row for row in source_sales_returns
                   if normalized_document(row["Parent Sale"]) == expected["invoice"]
                   and normalized_document(row["Invoice No."]) == expected["return_document"]]
        tax_rows = [row for row in source_tax_outputs
                    if normalized_document(row["Invoice No."]) == expected["invoice"]
                    and money(row["Total amount with tax"]) > 0]
        lines = [row for row in allocation_sales_lines
                 if normalized_document(row["Invoice No."]) == expected["invoice"]]
        require(len(headers) == len(returns) == len(tax_rows) == 1,
                f'{expected["invoice"]}: full-return evidence is not unique')
        require(lines, f'{expected["invoice"]}: sale lines are unavailable')
        header_total = first_money(headers[0]["Total amount"])
        return_total = money(returns[0]["Total amount"])
        original_gross = money(tax_rows[0]["Total amount with tax"])
        line_total = sum((money(row["Total"]) for row in lines), Decimal("0"))
        require(header_total == Decimal(expected["net_total"])
                and return_total == Decimal(expected["return_total"])
                and original_gross == Decimal(expected["original_gross"])
                and line_total == 0,
                f'{expected["invoice"]}: full-return amounts differ')
        require(original_gross - return_total == header_total,
                f'{expected["invoice"]}: original gross less return does not equal net header')
        used_line_paths = [path for path in allocation_sales_line_paths
                           if expected["invoice"] in path.read_text(encoding="utf-8-sig")]
        result[exception_id] = {
            "source_key": expected["invoice"],
            "relationship": "the tax register preserves the original gross, the return register preserves the credit note and current item quantities are fully returned",
            "allocation_equation": "original tax-inclusive sale - linked return = net sale header",
            "original_gross_aed": f"{original_gross:.2f}",
            "return_total_aed": f"{return_total:.2f}",
            "net_sale_aed": f"{header_total:.2f}",
            "current_line_total_aed": f"{line_total:.2f}",
            "return_document": expected["return_document"],
            "line_rows": len(lines),
            "allocation_disposition": "balanced_as_fully_returned_sale",
            "files": {
                str(path.relative_to(source_root)): sha256(path)
                for path in (source_sales_path, source_sales_returns_path, tax_output_path,
                             *used_line_paths)
            },
        }

    source_purchase_rows = rows(source_purchases_path)
    source_purchase_returns = rows(source_purchase_returns_path)
    source_purchase_lines = rows(purchase_lines_path)
    source_tax_inputs = rows(tax_input_path)
    for exception_id, expected in PURCHASE_RETURN_ALLOCATION_EXCEPTIONS.items():
        headers = [row for row in source_purchase_rows
                   if normalized_document(row["Purchase No"]) == expected["purchase"]]
        returns = [row for row in source_purchase_returns
                   if normalized_document(row["Parent Purchase"]) == expected["purchase"]
                   and normalized_document(row["Reference No"]) == expected["return_document"]]
        tax_rows = [row for row in source_tax_inputs
                    if normalized_document(row["Reference No"]) == expected["purchase"]]
        lines = [row for row in source_purchase_lines
                 if normalized_document(row["Reference No"]) == expected["purchase"]]
        require(len(headers) == len(returns) == len(tax_rows) == 1,
                f'{expected["purchase"]}: purchase-return evidence is not unique')
        require(lines, f'{expected["purchase"]}: purchase lines are unavailable')
        line_total = sum((money(row["Subtotal"]) for row in lines), Decimal("0"))
        tax_base = money(tax_rows[0]["Total amount"])
        vat = money(tax_rows[0]["VAT"])
        discount = money(tax_rows[0]["Discount"])
        header_total = money(headers[0]["Grand Total"])
        return_total = money(returns[0]["Grand Total"])
        line_gap = tax_base - line_total
        require(line_total == Decimal(expected["line_total"])
                and tax_base == Decimal(expected["tax_base"])
                and vat == Decimal(expected["vat"])
                and return_total == Decimal(expected["return_total"])
                and line_gap == Decimal(expected["line_gap"]),
                f'{expected["purchase"]}: purchase-return amounts differ')
        require(abs(header_total - (tax_base + vat - discount)) <= Decimal("0.01"),
                f'{expected["purchase"]}: purchase header and tax control differ')
        expected_return_total = line_gap + (line_gap * vat / tax_base)
        require(abs(return_total - expected_return_total) <= Decimal("0.01"),
                f'{expected["purchase"]}: return does not prove the pre-tax line gap')
        result[exception_id] = {
            "source_key": expected["purchase"],
            "relationship": "the linked VAT-inclusive purchase return exactly explains the line amount removed from the current purchase-line export",
            "allocation_equation": "current purchase lines + returned pre-tax lines + VAT - discount = purchase header",
            "current_line_total_aed": f"{line_total:.2f}",
            "returned_line_gap_aed": f"{line_gap:.2f}",
            "tax_base_aed": f"{tax_base:.2f}",
            "vat_aed": f"{vat:.2f}",
            "discount_aed": f"{discount:.2f}",
            "return_total_aed": f"{return_total:.2f}",
            "purchase_total_aed": f"{header_total:.2f}",
            "return_document": expected["return_document"],
            "line_rows": len(lines),
            "allocation_disposition": "return_adjusted_purchase_lines_reconciled",
            "files": {
                str(path.relative_to(source_root)): sha256(path)
                for path in (source_purchases_path, source_purchase_returns_path,
                             purchase_lines_path, tax_input_path)
            },
        }

    for exception_id, expected in GROSS_COST_JOURNAL_EXCEPTIONS.items():
        headers = [row for row in source_purchase_rows
                   if normalized_document(row["Purchase No"]) == expected["purchase"]]
        lines = [row for row in source_purchase_lines
                 if normalized_document(row["Reference No"]) == expected["purchase"]]
        tax_rows = [row for row in source_tax_inputs
                    if normalized_document(row["Reference No"]) == expected["purchase"]]
        require(len(headers) == 1 and lines,
                f'{expected["purchase"]}: gross-cost journal evidence is incomplete')
        require(not tax_rows,
                f'{expected["purchase"]}: unexpected input-VAT evidence exists')
        header_total = money(headers[0]["Grand Total"])
        line_total = sum((money(row["Subtotal"]) for row in lines), Decimal("0"))
        require(header_total == line_total == Decimal(expected["total"]),
                f'{expected["purchase"]}: header and item totals do not support gross-cost treatment')
        result[exception_id] = {
            "source_key": expected["purchase"],
            "relationship": "the purchase header equals its complete item total and no input-tax register row exists",
            "journal_equation": "debit gross inventory or purchase cost = credit supplier payable; input VAT claimed = 0",
            "header_total_aed": f"{header_total:.2f}",
            "line_total_aed": f"{line_total:.2f}",
            "input_vat_claim_aed": "0.00",
            "line_rows": len(lines),
            "journal_disposition": "balanced_gross_cost_without_input_vat_claim",
            "files": {
                str(path.relative_to(source_root)): sha256(path)
                for path in (source_purchases_path, purchase_lines_path, tax_input_path)
            },
        }

    for exception_id, (purchase, expected_lines, expected_vat, expected_total) in INFERRED_GROSS_COST_ALLOCATION_EXCEPTIONS.items():
        headers = [row for row in source_purchase_rows
                   if normalized_document(row["Purchase No"]) == purchase]
        lines = [row for row in source_purchase_lines
                 if normalized_document(row["Reference No"]) == purchase]
        tax_rows = [row for row in source_tax_inputs
                    if normalized_document(row["Reference No"]) == purchase]
        require(len(headers) == 1 and lines and not tax_rows,
                f"{purchase}: inferred gross-cost evidence is incomplete")
        line_total = sum((money(row["Subtotal"]) for row in lines), Decimal("0"))
        header_total = money(headers[0]["Grand Total"])
        vat_component = header_total - line_total
        require(line_total == Decimal(expected_lines)
                and vat_component == Decimal(expected_vat)
                and header_total == Decimal(expected_total)
                and vat_component == line_total * Decimal("0.05"),
                f"{purchase}: header and source-line gross-cost relationship differs")
        result[exception_id] = {
            "source_key": purchase,
            "relationship": "complete captured item lines plus exactly 5 percent equal the gross purchase header, while the input-tax register has no matching row",
            "line_total_aed": f"{line_total:.2f}",
            "unclaimed_vat_component_aed": f"{vat_component:.2f}",
            "gross_purchase_total_aed": f"{header_total:.2f}",
            "input_vat_claim_aed": "0.00",
            "line_rows": len(lines),
            "allocation_disposition": "gross_cost_preserved_without_synthetic_tax_claim",
            "files": {
                str(path.relative_to(source_root)): sha256(path)
                for path in (source_purchases_path, purchase_lines_path, tax_input_path)
            },
        }

    cash_flow_paths = sorted((source_root / "2026-09-08").glob("cash_flow_2026-*.csv"))
    source_cash_flow = [row for path in cash_flow_paths for row in rows(path)]
    for exception_id, expected in RETURN_DUE_SETTLEMENT_EXCEPTIONS.items():
        headers = [row for row in source_sales_rows
                   if normalized_document(row["Invoice No."]) == expected["invoice"]]
        returns = [row for row in source_sales_returns
                   if normalized_document(row["Parent Sale"]) == expected["invoice"]
                   and normalized_document(row["Invoice No."]) == expected["return_document"]]
        payments = [row for row in source_sales_payments
                    if row["Reference No"] in expected["payment_references"]
                    and normalized_document(row["Sales"]) == expected["invoice"]]
        tax_rows = [row for row in source_tax_outputs
                    if normalized_document(row["Invoice No."]) == expected["invoice"]
                    and money(row["Total amount with tax"]) > 0]
        require(len(headers) == 1, f'{expected["invoice"]}: expected one sale header')
        require(len(returns) == 1, f'{expected["invoice"]}: expected one linked sales return')
        require(len(payments) == len(expected["payment_references"]),
                f'{expected["invoice"]}: payment register coverage differs')
        require({row["Reference No"] for row in payments} == set(expected["payment_references"]),
                f'{expected["invoice"]}: payment references differ')
        require(len(tax_rows) == 1, f'{expected["invoice"]}: expected one positive original tax row')

        header = headers[0]
        returned = returns[0]
        net_total = first_money(header["Total amount"])
        payment_total = sum((money(row["Amount"]) for row in payments), Decimal("0"))
        due = money(header["Sell Due"])
        return_due = money(header["Sell Return Due"])
        return_total = money(returned["Total amount"])
        original_gross = money(tax_rows[0]["Total amount with tax"])
        require(net_total == Decimal(expected["net_total"])
                and payment_total == Decimal(expected["payment_total"])
                and due == 0
                and return_due == Decimal(expected["return_due"])
                and return_total == Decimal(expected["return_total"])
                and original_gross == Decimal(expected["original_gross"]),
                f'{expected["invoice"]}: preserved financial fields differ')
        require(net_total - payment_total - due + return_due == 0,
                f'{expected["invoice"]}: return-due settlement does not balance')
        require(abs((net_total + return_total) - original_gross) <= Decimal("0.01"),
                f'{expected["invoice"]}: original gross does not reconcile to net sale plus return')

        matched_cash = []
        for payment in payments:
            candidates = [row for row in source_cash_flow
                          if payment["Reference No"] in row["Description"]]
            require(len(candidates) == 1,
                    f'{payment["Reference No"]}: expected one cash-flow row')
            cash = candidates[0]
            require(normalized_document(payment["Sales"]) in cash["Description"]
                    and cash["Date"] == payment["Paid on"]
                    and money(cash["Credit"]) == money(payment["Amount"])
                    and money(cash["Debit"]) == 0,
                    f'{payment["Reference No"]}: cash-flow fields differ')
            matched_cash.append(cash)

        used_cash_paths = [path for path in cash_flow_paths
                           if any(payment["Reference No"] in path.read_text(encoding="utf-8-sig")
                                  for payment in payments)]
        result[exception_id] = {
            "source_key": expected["invoice"],
            "relationship": "the sale header is net of its linked return and Sell Return Due records the customer-credit liability",
            "settlement_equation": "net sale - receipts - sale due + sell return due = 0",
            "net_sale_aed": str(net_total),
            "receipt_total_aed": str(payment_total),
            "sale_due_aed": str(due),
            "sell_return_due_aed": str(return_due),
            "return_document": expected["return_document"],
            "return_total_aed": str(return_total),
            "original_gross_aed": str(original_gross),
            "payment_references": list(expected["payment_references"]),
            "cash_flow_rows": len(matched_cash),
            "settlement_disposition": "balanced_with_customer_return_credit",
            "files": {
                str(path.relative_to(source_root)): sha256(path)
                for path in (source_sales_path, source_sales_returns_path, sales_payments_path,
                             tax_output_path, *used_cash_paths)
            },
        }

    current_status = json.loads(current_status_path.read_text(encoding="utf-8"))
    require(current_status.get("source_access", "").startswith("read-only"),
            "later capture does not prove read-only source access")
    current_hashes = {item["name"]: item["sha256"].upper() for item in current_status["files"]}
    for path in (current_sales_path, current_sales_payments_path):
        require(current_hashes.get(path.name) == sha256(path),
                f"later capture checksum mismatch: {path.name}")
    current_sales = rows(current_sales_path)
    current_payments = rows(current_sales_payments_path)
    frozen_payments = rows(frozen_sales_payments_path)
    for exception_id, expected in LATER_PAYMENT_SETTLEMENT_EXCEPTIONS.items():
        headers = [row for row in current_sales
                   if normalized_document(row["Invoice No."]) == expected["invoice"]]
        payments = [row for row in current_payments
                    if row["Reference No"] in expected["payment_references"]
                    and normalized_document(row["Sales"]) == expected["invoice"]]
        frozen_matches = [row for row in frozen_payments
                          if row["Reference No"] in expected["payment_references"]
                          and normalized_document(row["Sales"]) == expected["invoice"]]
        require(len(headers) == 1, f'{expected["invoice"]}: expected one later header')
        require(len(payments) == len(frozen_matches) == len(expected["payment_references"]),
                f'{expected["invoice"]}: later payment coverage differs')
        header = headers[0]
        total = first_money(header["Total amount"])
        paid = money(header["Total paid"])
        due = money(header["Sell Due"])
        payment_total = sum((money(row["Amount"]) for row in payments), Decimal("0"))
        frozen_total = sum((money(row["Amount"]) for row in frozen_matches), Decimal("0"))
        require(total == Decimal(expected["total"])
                and paid == payment_total == frozen_total == Decimal(expected["paid"])
                and due == Decimal(expected["due"])
                and total - paid - due == 0,
                f'{expected["invoice"]}: later settlement fields do not reconcile')
        cash_matches = [row for row in source_cash_flow
                        if any(reference in row["Description"]
                               for reference in expected["payment_references"])]
        require(len(cash_matches) == len(expected["payment_references"])
                and sum((money(row["Credit"]) for row in cash_matches), Decimal("0")) == paid,
                f'{expected["invoice"]}: cash-flow coverage differs')
        used_cash_paths = [path for path in cash_flow_paths
                           if any(reference in path.read_text(encoding="utf-8-sig")
                                  for reference in expected["payment_references"])]
        result[exception_id] = {
            "source_key": expected["invoice"],
            "relationship": "a later checksum-recorded header, stable frozen payment register and matching cash-flow rows prove the updated settlement",
            "settlement_equation": "sale total - receipts - sale due = 0",
            "sale_total_aed": str(total),
            "receipt_total_aed": str(paid),
            "sale_due_aed": str(due),
            "payment_references": list(expected["payment_references"]),
            "cash_flow_rows": len(cash_matches),
            "settlement_disposition": "later_receipts_reconciled",
            "non_atomic_capture_used_for_header": True,
            "posting_remains_blocked": True,
            "files": {
                str(path.relative_to(source_root)): sha256(path)
                for path in (current_status_path, current_sales_path, current_sales_payments_path,
                             frozen_sales_payments_path, *used_cash_paths)
            },
        }

    purchase_return_documents = json.loads(purchase_returns_path.read_text(encoding="utf-8"))
    sales_return_documents = json.loads(sales_returns_path.read_text(encoding="utf-8"))
    purchase_history = rows(purchase_lines_path)
    sales_history: list[dict[str, str]] = []
    sales_history_paths: list[Path] = []
    for path in sorted((source_root / "2026-09-08").glob("product_sales_detail_2026-??.csv")):
        sales_history.extend(rows(path))
        sales_history_paths.append(path)
    source_products = rows(source_products_path)

    for exception_id, expected in RETURN_LINE_RELATIONSHIP_EXCEPTIONS.items():
        if expected["direction"] == "purchase":
            documents = [item.get("snapshot", "") for item in purchase_return_documents
                         if f'textbox "Reference No:": {expected["return_document"]}' in item.get("snapshot", "")]
            history = [row for row in purchase_history
                       if row["Reference No"] == expected["parent_document"]
                       and row["Product"] == expected["product_name"]]
            history_file = purchase_lines_path
        else:
            documents = [item.get("text", "") for item in sales_return_documents
                         if f'Sell Return (Invoice No.: {expected["return_document"]})' in item.get("text", "")]
            history = [row for row in sales_history
                       if row["Invoice No."] == expected["parent_document"]
                       and row["Product"] == expected["product_name"]]
            matching_history_paths = [path for path in sales_history_paths if any(
                row["Invoice No."] == expected["parent_document"] and row["Product"] == expected["product_name"]
                for row in rows(path))]
            require(len(matching_history_paths) == 1,
                    f'{expected["return_document"]}: parent sale evidence is not in one source file')
            history_file = matching_history_paths[0]
        require(len(documents) == 1, f'{expected["return_document"]}: expected one return detail document')
        detail = documents[0]
        require(expected["parent_document"] in detail,
                f'{expected["return_document"]}: parent document differs')
        detail_lines = [line for line in detail.splitlines()
                        if expected["product_name"] in line
                        and (expected["direction"] == "sale" or line.lstrip().startswith('- row "'))]
        require(len(detail_lines) == 1,
                f'{expected["return_document"]}/{expected["product_name"]}: return line is not unique')
        detail_line = detail_lines[0]
        if expected["direction"] == "sale":
            columns = detail_line.split("\t")
            require(len(columns) >= 5
                    and quantity(columns[-2]) == Decimal(expected["return_quantity"])
                    and money(columns[-1]) == Decimal(expected["return_subtotal"]),
                    f'{expected["return_document"]}/{expected["product_name"]}: quantity or subtotal differs')
        else:
            require(expected["return_quantity"] in detail_line and expected["return_subtotal"] in detail_line,
                    f'{expected["return_document"]}/{expected["product_name"]}: quantity or subtotal differs')
        require(len(history) == 1 and history[0]["SKU"] == expected["sku"],
                f'{expected["parent_document"]}/{expected["product_name"]}: parent product identity is not unique')
        masters = [row for row in source_products if row["SKU"] == expected["sku"]]
        require(len(masters) == 1,
                f'{expected["sku"]}: expected one preserved product master')
        master_name = re.sub(r"\s+Inactive$", "", masters[0]["Product"]).strip()
        require(master_name == expected["product_name"],
                f'{expected["sku"]}: master and transaction product names differ')
        zero_quantity = Decimal(expected["return_quantity"]) == 0
        result[exception_id] = {
            "source_key": f'document_line:{expected["source_line_id"]}',
            "relationship": ("return-detail row is a zero-quantity source placeholder and its product identity is proven by the parent transaction"
                             if zero_quantity else
                             "return-detail row has one parent transaction product identity and one preserved product master"),
            "source_line_id": expected["source_line_id"],
            "direction": expected["direction"],
            "return_document": expected["return_document"],
            "parent_document": expected["parent_document"],
            "product_name": expected["product_name"],
            "sku": expected["sku"],
            "return_quantity": expected["return_quantity"],
            "return_subtotal_aed": expected["return_subtotal"],
            "line_disposition": "exclude_from_posting_zero_quantity" if zero_quantity else "eligible_for_controlled_mapping",
            "files": {
                str((purchase_returns_path if expected["direction"] == "purchase" else sales_returns_path).relative_to(source_root)):
                    sha256(purchase_returns_path if expected["direction"] == "purchase" else sales_returns_path),
                str(history_file.relative_to(source_root)): sha256(history_file),
                str(source_products_path.relative_to(source_root)): sha256(source_products_path),
                str(detail_hashes_path.relative_to(source_root)): sha256(detail_hashes_path),
            },
        }

    source_units = rows(units_path)
    transfer_detail_documents: list[tuple[Path, dict]] = []
    for path in sorted((source_root / "2026-09-08").glob("stock_transfer_details_*.json")):
        require(detail_hashes.get(path.name) == sha256(path),
                f"capture checksum mismatch: {path.name}")
        transfer_detail_documents.extend((path, item) for item in json.loads(path.read_text(encoding="utf-8")))

    def package_family(value: str) -> str:
        family = re.split(r"\s*\(", value, maxsplit=1)[0]
        normalized = normalized_name(family)
        return {"ctn": "carton", "pcs": "piece", "pieces": "piece", "pc": "piece"}.get(normalized, normalized)

    for exception_id, values in INVENTORY_MOVEMENT_UOM_EXCEPTIONS.items():
        (source_movement_id, direction, document_no, product_name, sku, entered_quantity,
         entered_uom, base_uom, factor_text, conversion_basis) = values
        masters = [row for row in source_products if row["SKU"] == sku]
        require(len(masters) == 1, f"{sku}: expected one preserved product master")
        master_name = re.sub(r"\s+Inactive$", "", masters[0]["Product"]).strip()
        require(master_name == product_name, f"{sku}: movement and master product names differ")
        stock_match = re.match(r"^-?[0-9,.]+\s+(.+)$", masters[0]["Current stock"])
        require(stock_match and package_family(stock_match.group(1)) == package_family(base_uom),
                f"{sku}: expected base UOM {base_uom}")

        if direction == "purchase":
            matches = [(purchase_returns_path, item.get("snapshot", ""))
                       for item in purchase_return_documents
                       if f'textbox "Reference No:": {document_no}' in item.get("snapshot", "")]
        elif direction == "sale":
            matches = [(sales_returns_path, item.get("text", ""))
                       for item in sales_return_documents
                       if f"Sell Return (Invoice No.: {document_no})" in item.get("text", "")]
        else:
            matches = [(path, item.get("text", "")) for path, item in transfer_detail_documents
                       if f"Reference No: #{document_no}" in item.get("text", "")]
        require(len(matches) == 1, f"{document_no}: expected one preserved movement detail")
        detail_path, detail = matches[0]
        detail_lines = [line for line in detail.splitlines()
                        if product_name in line and (direction != "purchase" or line.lstrip().startswith('- row "'))]
        require(len(detail_lines) == 1, f"{document_no}/{sku}: movement line is not unique")
        detail_line = detail_lines[0]
        if direction == "sale":
            captured_quantity = quantity(detail_line.split("\t")[-2])
        elif direction.startswith("transfer"):
            captured_quantity = quantity(detail_line.split("\t")[5])
        else:
            numeric_values = [Decimal(value.replace(",", "")) for value in re.findall(r"-?[0-9][0-9,]*\.[0-9]+", detail_line)]
            captured_quantity = Decimal(entered_quantity) if Decimal(entered_quantity) in numeric_values else Decimal("0")
        require(entered_uom.casefold() in detail_line.casefold()
                and Decimal(entered_quantity) == captured_quantity,
                f"{document_no}/{sku}: entered quantity or UOM differs")
        if direction.startswith("transfer"):
            require("Status: Completed" in detail and f" - {sku}" in detail_line,
                    f"{document_no}/{sku}: completed transfer evidence differs")

        factor = Decimal(factor_text)
        if conversion_basis in {"identity", "identity_family"}:
            require(package_family(entered_uom) == package_family(base_uom) and factor == 1,
                    f"{document_no}/{sku}: identity conversion is not supported")
        elif conversion_basis == "unit_registry":
            unit_matches = [row for row in source_units
                            if normalized_name(row["Short name"]) == normalized_name(entered_uom)]
            base_tokens = ("pack",) if package_family(base_uom) == "pack" else ("pc", "pcs", "piece", "pieces")
            require(len(unit_matches) >= 1 and any(
                any(f"{factor_text}{token}" in normalized_name(row["Name"]) for token in base_tokens)
                for row in unit_matches
            ), f"{entered_uom}: exact unit-registry factor {factor_text} {base_uom} is missing")
        else:
            require(conversion_basis in normalized_name(product_name),
                    f"{sku}: product package label does not prove factor {factor_text}")

        multiplier = Decimal("-1") if direction in {"purchase", "transfer_out"} else Decimal("1")
        result[exception_id] = {
            "source_key": f"movement:{document_no}:{sku}:{direction}",
            "relationship": "checksum-preserved movement detail and unique product master prove the entered UOM, base UOM and product-specific conversion",
            "source_movement_id": source_movement_id,
            "document_no": document_no,
            "sku": sku,
            "product_name": product_name,
            "direction": direction,
            "entered_quantity": entered_quantity,
            "entered_uom": entered_uom,
            "base_uom": base_uom,
            "factor_to_base_snapshot": factor_text,
            "quantity_base": str(Decimal(entered_quantity) * factor * multiplier),
            "conversion_basis": conversion_basis,
            "posting_disposition": "eligible_for_controlled_mapping_without_enabling_posting",
            "files": {
                str(path.relative_to(source_root)): sha256(path)
                for path in {detail_path, source_products_path, units_path, detail_hashes_path}
            },
        }

    purchase_payments = rows(purchase_payments_path)
    sales_payments = rows(sales_payments_path)
    cash_flow = rows(cash_flow_path)
    source_purchases = rows(source_purchases_path)
    source_sales = rows(source_sales_path)
    for exception_id, expected in PAYMENT_PARENT_RELATIONSHIP_EXCEPTIONS.items():
        payment_rows = [row for row in (purchase_payments if expected["direction"] == "purchase" else sales_payments)
                        if row["Reference No"] == expected["payment_reference"]]
        require(len(payment_rows) == 1,
                f'{expected["payment_reference"]}: expected one payment register row')
        payment = payment_rows[0]
        party_column = "Supplier" if expected["direction"] == "purchase" else "Customer"
        document_column = "Purchase" if expected["direction"] == "purchase" else "Sales"
        require(payment[document_column] == expected["parent_document"]
                and normalized_name(payment[party_column]) == normalized_name(expected["party_name"])
                and payment["Paid on"] == expected["paid_on"]
                and payment["Payment Method"].startswith(expected["method"])
                and money(payment["Amount"]) == Decimal(expected["amount"]),
                f'{expected["payment_reference"]}: payment register fields differ')

        cash_rows = [row for row in cash_flow if expected["payment_reference"] in row["Description"]]
        require(len(cash_rows) == 1,
                f'{expected["payment_reference"]}: expected one cash-flow row')
        cash = cash_rows[0]
        cash_amount = money(cash["Debit"] if expected["direction"] == "purchase" else cash["Credit"])
        require(cash["Date"] == expected["paid_on"]
                and cash["Payment Method"] == expected["method"]
                and expected["parent_document"] in cash["Description"]
                and normalized_name(expected["party_name"]) in normalized_name(cash["Description"])
                and cash_amount == Decimal(expected["amount"]),
                f'{expected["payment_reference"]}: cash-flow fields differ')

        if expected["direction"] == "purchase":
            candidates = [row for row in source_purchases
                          if row["Purchase No"] == expected["parent_document"]
                          and normalized_name(row["Supplier"]) == normalized_name(expected["party_name"])]
            require(len(candidates) == 1,
                    f'{expected["payment_reference"]}: supplier does not select one purchase header')
            parent = candidates[0]
            require(money(parent["Grand Total"]) - money(parent["Payment due \u00a0\u00a0"])
                    == Decimal(expected["amount"]),
                    f'{expected["payment_reference"]}: purchase settlement amount differs')
            parent_date = parent["Date"]
            parent_party = parent["Supplier"]
            parent_total = money(parent["Grand Total"])
            parent_residual = money(parent["Payment due \u00a0\u00a0"])
            payment_file = purchase_payments_path
        else:
            candidates = [row for row in source_sales
                          if row["Invoice No."] == expected["parent_document"]
                          and normalized_name(row["Customer name"]) == normalized_name(expected["party_name"])]
            require(len(candidates) == 1,
                    f'{expected["payment_reference"]}: customer does not select one sales header')
            parent = candidates[0]
            require(money(parent["Total paid"]) == Decimal(expected["amount"])
                    and money(parent["Sell Due"]) == 0,
                    f'{expected["payment_reference"]}: sales settlement amount differs')
            parent_date = parent["Date"]
            parent_party = parent["Customer name"]
            parent_total = money(parent["Total amount"])
            parent_residual = money(parent["Sell Due"])
            payment_file = sales_payments_path
        payment_evidence = {
            "source_key": f'payment:{expected["source_payment_id"]}',
            "relationship": "duplicate document number is disambiguated by one matching party, payment reference, timestamp, method, cash-flow direction and amount",
            "source_payment_id": expected["source_payment_id"],
            "direction": expected["direction"],
            "payment_reference": expected["payment_reference"],
            "parent_document": expected["parent_document"],
            "party_name_normalized": normalized_name(parent_party),
            "payment_date": expected["paid_on"],
            "parent_date": parent_date,
            "payment_method": expected["method"],
            "payment_amount_aed": expected["amount"],
            "parent_total_aed": str(parent_total),
            "parent_residual_aed": str(parent_residual),
            "candidate_document_number_count": 2,
            "candidate_count_after_multi_field_match": 1,
            "line_disposition": "eligible_for_controlled_mapping",
            "files": {
                str(payment_file.relative_to(source_root)): sha256(payment_file),
                str(cash_flow_path.relative_to(source_root)): sha256(cash_flow_path),
                str((source_purchases_path if expected["direction"] == "purchase" else source_sales_path).relative_to(source_root)):
                    sha256(source_purchases_path if expected["direction"] == "purchase" else source_sales_path),
            },
        }
        result[exception_id] = payment_evidence
        result[expected["settlement_exception_id"]] = {
            **payment_evidence,
            "source_key": expected["parent_document"],
            "relationship": "one checksum-verified payment and cash-flow row settle the uniquely selected parent document",
            "settlement_disposition": "payment_allocation_relationship_proven",
            "relationship_exception_id": exception_id,
        }

    primary_cash_flow_paths = account_cash_flow_paths
    primary_cash_flow_rows = [
        (path, row) for path in primary_cash_flow_paths for row in rows(path)
    ]
    purchase_return_details = json.loads(purchase_returns_path.read_text(encoding="utf-8"))
    sale_return_details = json.loads(sales_returns_path.read_text(encoding="utf-8"))
    for exception_id, expected in RETURN_SETTLEMENT_CASH_FLOW_EXCEPTIONS.items():
        direction = expected["direction"]
        register_path = source_purchase_returns_path if direction == "purchase" else source_sales_returns_path
        register_rows = rows(register_path)
        document_column = "Reference No" if direction == "purchase" else "Invoice No."
        party_column = "Supplier" if direction == "purchase" else "Customer name"
        total_column = "Grand Total" if direction == "purchase" else "Total amount"
        due_column = "Payment due \u00a0\u00a0" if direction == "purchase" else "Payment due"
        return_rows = [row for row in register_rows
                       if normalized_document(row[document_column]) == expected["return_document"]]
        require(len(return_rows) == 1,
                f'{expected["return_document"]}: expected one return-register row')
        returned = return_rows[0]
        require(normalized_name(returned[party_column]) == normalized_name(expected["party_name"])
                and returned["Date"] == expected["return_date"]
                and returned["Payment Status"] == expected["status"]
                and money(returned[total_column]) == Decimal(expected["amount"])
                and money(returned[due_column]) == 0,
                f'{expected["return_document"]}: return settlement fields differ')
        parent_column = "Parent Purchase" if direction == "purchase" else "Parent Sale"
        require(normalized_document(returned[parent_column]) == expected["parent_document"],
                f'{expected["return_document"]}: return parent differs')

        payment_rows = [row for row in (purchase_payments if direction == "purchase" else sales_payments)
                        if normalized_document(row["Reference No"]) == expected["payment_reference"]]
        require(not payment_rows,
                f'{expected["payment_reference"]}: unexpectedly exists in the standard payment register')
        cash_rows = [(path, row) for path, row in primary_cash_flow_rows
                     if expected["payment_reference"] in row["Description"]]
        require(len(cash_rows) == 1,
                f'{expected["payment_reference"]}: expected one canonical monthly cash-flow row')
        cash_path, cash = cash_rows[0]
        opposite_direction = "Credit" if expected["cash_direction"] == "Debit" else "Debit"
        require(cash["Date"] == expected["cash_date"]
                and cash["Payment Method"] == expected["method"]
                and expected["return_document"] in cash["Description"]
                and money(cash[expected["cash_direction"]]) == Decimal(expected["amount"])
                and money(cash[opposite_direction]) == 0,
                f'{expected["payment_reference"]}: return cash-flow fields differ')

        details = purchase_return_details if direction == "purchase" else sale_return_details
        if direction == "purchase":
            detail_matches = [item for item in details
                              if f'textbox "Reference No:": {expected["return_document"]}' in item.get("snapshot", "")]
            detail_text = detail_matches[0].get("snapshot", "") if len(detail_matches) == 1 else ""
            detail_total_markers = (
                f'Return Total:\"\n- text: AED {Decimal(expected["amount"]):.2f}',
                f'Total Amount: {Decimal(expected["amount"]):.2f}',
            )
        else:
            detail_matches = [item for item in details
                              if f'Sell Return (Invoice No.: {expected["return_document"]})' in item.get("text", "")]
            detail_text = detail_matches[0].get("text", "") if len(detail_matches) == 1 else ""
            detail_total_markers = (f'Return Total:\t\t{Decimal(expected["amount"]):.4f}',)
        require(len(detail_matches) == 1 and any(marker in detail_text for marker in detail_total_markers),
                f'{expected["return_document"]}: complete return detail or total is unavailable')

        result[exception_id] = {
            "source_key": expected["payment_reference"],
            "relationship": "BizModo stores this return settlement in the return register and cash ledger, not in the standard invoice-payment register",
            "payment_reference": expected["payment_reference"],
            "direction": direction,
            "return_document": expected["return_document"],
            "parent_document": expected["parent_document"] or None,
            "party_name_normalized": normalized_name(expected["party_name"]),
            "return_status": expected["status"],
            "return_date": expected["return_date"],
            "cash_date": expected["cash_date"],
            "payment_method": expected["method"],
            "settlement_amount_aed": expected["amount"],
            "return_amount_due_aed": "0.00",
            "standard_payment_register_rows": 0,
            "canonical_cash_flow_rows": 1,
            "return_register_rows": 1,
            "return_detail_documents": 1,
            "settlement_disposition": "embedded_return_settlement_preserved_without_synthetic_payment",
            "files": {
                str(register_path.relative_to(source_root)): sha256(register_path),
                str(cash_path.relative_to(source_root)): sha256(cash_path),
                str((purchase_payments_path if direction == "purchase" else sales_payments_path).relative_to(source_root)):
                    sha256(purchase_payments_path if direction == "purchase" else sales_payments_path),
                str((purchase_returns_path if direction == "purchase" else sales_returns_path).relative_to(source_root)):
                    sha256(purchase_returns_path if direction == "purchase" else sales_returns_path),
                str(detail_hashes_path.relative_to(source_root)): sha256(detail_hashes_path),
            },
        }

    current_sales = rows(current_sales_path)
    current_purchases = rows(current_purchases_path)
    current_sales_payments = rows(current_sales_payments_path)
    current_purchase_payments = rows(current_purchase_payments_path)
    frozen_sales_payments = rows(frozen_sales_payments_path)
    frozen_purchase_payments = rows(frozen_purchase_payments_path)
    for exception_id, expected in PAYMENT_REGISTER_WITHOUT_CASH_FLOW_EXCEPTIONS.items():
        direction = expected["direction"]
        payment_sets = (
            (purchase_payments, current_purchase_payments, frozen_purchase_payments)
            if direction == "purchase"
            else (sales_payments, current_sales_payments, frozen_sales_payments)
        )
        party_column = "Supplier" if direction == "purchase" else "Customer"
        document_column = "Purchase" if direction == "purchase" else "Sales"
        for payment_rows in payment_sets:
            matches = [row for row in payment_rows
                       if normalized_document(row["Reference No"]) == expected["payment_reference"]]
            require(len(matches) == 1,
                    f'{expected["payment_reference"]}: payment is not unique in every preserved capture')
            payment = matches[0]
            require(normalized_document(payment[document_column]) == expected["parent_document"]
                    and normalized_name(payment[party_column]) == normalized_name(expected["party_name"])
                    and payment["Paid on"] == expected["paid_on"]
                    and payment["Payment Method"] == expected["method"]
                    and money(payment["Amount"]) == Decimal(expected["amount"]),
                    f'{expected["payment_reference"]}: payment fields changed between captures')

        header_sets = (source_purchase_rows, current_purchases) if direction == "purchase" else (source_sales_rows, current_sales)
        for header_rows in header_sets:
            header_document_column = "Purchase No" if direction == "purchase" else "Invoice No."
            matches = [row for row in header_rows
                       if normalized_document(row[header_document_column]) == expected["parent_document"]]
            require(len(matches) == 1,
                    f'{expected["parent_document"]}: parent header is not unique in every preserved capture')
            header = matches[0]
            header_total = money(header["Grand Total"] if direction == "purchase" else header["Total amount"])
            require(header["Payment Status"] == "Paid"
                    and header_total == Decimal(expected["amount"]),
                    f'{expected["parent_document"]}: paid header does not equal the payment amount')
            if direction == "sale":
                require(money(header["Total paid"]) == Decimal(expected["amount"])
                        and money(header["Sell Due"]) == 0,
                        f'{expected["parent_document"]}: sale settlement fields differ')

        cash_rows = [row for _, row in primary_cash_flow_rows
                     if expected["payment_reference"] in row["Description"]
                     or expected["parent_document"] in row["Description"]]
        require(not cash_rows,
                f'{expected["payment_reference"]}: an unexpected cash-flow candidate exists')
        month_prefix = expected["paid_on"][:2]
        month_cash_paths = [path for path in primary_cash_flow_paths
                            if path.name.startswith(f"cash_flow_2026-{month_prefix}")]
        require(month_cash_paths,
                f'{expected["payment_reference"]}: cash-flow month was not captured')

        payment_files = (
            (purchase_payments_path, current_purchase_payments_path, frozen_purchase_payments_path)
            if direction == "purchase"
            else (sales_payments_path, current_sales_payments_path, frozen_sales_payments_path)
        )
        header_files = (
            (source_purchases_path, current_purchases_path)
            if direction == "purchase"
            else (source_sales_path, current_sales_path)
        )
        result[exception_id] = {
            "source_key": expected["payment_reference"],
            "relationship": "three preserved payment-register captures and two paid parent-header captures agree, while the captured cash-flow month contains no reference or document candidate",
            "payment_reference": expected["payment_reference"],
            "direction": direction,
            "parent_document": expected["parent_document"],
            "party_name_normalized": normalized_name(expected["party_name"]),
            "payment_date": expected["paid_on"],
            "payment_method": expected["method"],
            "payment_amount_aed": expected["amount"],
            "payment_capture_rows": 3,
            "paid_header_capture_rows": 2,
            "cash_flow_candidate_rows": 0,
            "cash_flow_month_files": len(month_cash_paths),
            "settlement_disposition": "preserve_as_historical_nonposting_payment_without_synthetic_cash_event",
            "remaining_control": "cutover opening cash balance reconciliation controls the operational cash ledger",
            "files": {
                str(path.relative_to(source_root)): sha256(path)
                for path in (*payment_files, *header_files, *month_cash_paths)
            },
        }

    for exception_id, (invoice, sku) in SALE_LINE_EXCEPTIONS.items():
        headers = [row for row in sales_rows if row["Invoice No."] == invoice]
        details = [row for row in line_rows if row["Invoice No."] == invoice and row["SKU"] == sku]
        require(len(headers) == 1 and len(details) == 1,
                f"{invoice}/{sku}: line-to-header relationship is not unique")
        detail = details[0]
        result[exception_id] = {
            "source_key": f"{invoice}:{sku}",
            "relationship": "preserved sale line has one checksum-verified later-capture parent header",
            "document_no": invoice,
            "sku": sku,
            "quantity": detail["Quantity"],
            "line_total_aed": str(money(detail["Total"])),
            "files": {
                str(sales_path.relative_to(source_root)): sha256(sales_path),
                str(lines_path.relative_to(source_root)): sha256(lines_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }
        movement_exception_id = exception_id + 25
        result[movement_exception_id] = {
            "source_key": f"movement:{invoice}:{sku}",
            "relationship": "sale issue movement has a unique later-capture header location and identity UOM",
            "source_movement_id": 7427 + exception_id,
            "document_no": invoice,
            "sku": sku,
            "location": headers[0]["Location"],
            "entered_quantity": str(quantity(detail["Quantity"])),
            "entered_uom": re.sub(r"^-?[0-9]+(?:\.[0-9]+)?\s*", "", detail["Quantity"]).strip(),
            "direction": "issue",
            "files": {
                str(sales_path.relative_to(source_root)): sha256(sales_path),
                str(lines_path.relative_to(source_root)): sha256(lines_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }

    purchase_rows = rows(purchases_path)
    tax_inputs = rows(tax_input_path)
    tax_outputs = rows(tax_output_path)
    for exception_id, (kind, document_no) in TAX_EXCEPTIONS.items():
        if kind == "sale":
            headers = [row for row in sales_rows if row["Invoice No."] == document_no]
            taxes = [row for row in tax_outputs if row["Invoice No."] == document_no]
            require(len(headers) == 1 and len(taxes) == 1,
                    f"{document_no}: tax-to-sale relationship is not unique")
            gross = money(taxes[0]["Total amount with tax"])
            header_total = money(headers[0]["Total amount"])
            tax_file = tax_output_path
        else:
            headers = [row for row in purchase_rows if row["Purchase No"] == document_no]
            taxes = [row for row in tax_inputs if row["Reference No"] == document_no]
            require(len(headers) == 1 and len(taxes) == 1,
                    f"{document_no}: tax-to-purchase relationship is not unique")
            gross = money(taxes[0]["Total amount"]) + money(taxes[0]["VAT"])
            header_total = money(headers[0]["Grand Total"])
            tax_file = tax_input_path
        require(gross == header_total, f"{document_no}: tax gross {gross} != document total {header_total}")
        header_file = sales_path if kind == "sale" else purchases_path
        result[exception_id] = {
            "source_key": document_no,
            "relationship": f"preserved tax {kind} row has one checksum-verified later-capture document header",
            "document_kind": kind,
            "document_total_aed": str(header_total),
            "tax_gross_aed": str(gross),
            "vat_aed": str(money(taxes[0]["VAT"])),
            "files": {
                str(header_file.relative_to(source_root)): sha256(header_file),
                str(tax_file.relative_to(source_root)): sha256(tax_file),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }

    transfer_headers = [row for row in rows(transfers_path) if row["Reference No"] == "ST2026/0927"]
    transfer_details = [item for item in json.loads(transfer_details_path.read_text(encoding="utf-8"))
                        if "Reference No: #ST2026/0927" in item.get("text", "")]
    require(len(transfer_headers) == 1, "ST2026/0927: expected one later-capture header")
    require(len(transfer_details) == 1, "ST2026/0927: expected one preserved detail document")
    transfer = transfer_headers[0]
    text = transfer_details[0]["text"]
    require(transfer["Status"] == "Completed" and "Status: Completed" in text,
            "ST2026/0927: status is not consistently completed")
    require(transfer["Location (From)"] == "Asas General Trading LLC" and transfer["Location (To)"] == "DXB",
            "ST2026/0927: transfer locations differ")
    require("98081" in text and "1.00 Carton" in text and "Purchase Total:\t\t61.9000" in text,
            "ST2026/0927: preserved detail does not prove the expected line and total")
    require(money(transfer["Total Amount"]) == Decimal("61.90"), "ST2026/0927: header total differs")
    result[179] = {
        "source_key": "ST2026/0927",
        "relationship": "later capture contains the matching completed transfer header; preserved detail contains its line",
        "header_rows": 1,
        "detail_documents": 1,
        "sku": "98081",
        "quantity": "1.00 Carton",
        "from": transfer["Location (From)"],
        "to": transfer["Location (To)"],
        "total_aed": "61.90",
        "files": {
            str(transfers_path.relative_to(source_root)): sha256(transfers_path),
            str(transfer_details_path.relative_to(source_root)): sha256(transfer_details_path),
            str(status_path.relative_to(source_root)): sha256(status_path),
        },
    }
    result[22] = {
        "source_key": "document_line:90",
        "relationship": "later completed transfer header, preserved transfer detail and unique product master prove the line parent and product",
        "source_line_id": 90,
        "document_no": "ST2026/0927",
        "sku": "98081",
        "product_name": "Clear Tape 100 yard (1x36pcs)",
        "quantity": "1.00 Carton",
        "from": transfer["Location (From)"],
        "to": transfer["Location (To)"],
        "subtotal_aed": "61.90",
        "line_disposition": "eligible_for_controlled_mapping",
        "files": {
            str(transfers_path.relative_to(source_root)): sha256(transfers_path),
            str(transfer_details_path.relative_to(source_root)): sha256(transfer_details_path),
            str(products_path.relative_to(source_root)): sha256(products_path),
            str(status_path.relative_to(source_root)): sha256(status_path),
            str(detail_hashes_path.relative_to(source_root)): sha256(detail_hashes_path),
        },
    }
    for exception_id, source_movement_id, direction, location, counterparty in (
        (56, 9585, "transfer_out", "Asas General Trading LLC", "DXB"),
        (57, 9586, "transfer_in", "DXB", "Asas General Trading LLC"),
    ):
        result[exception_id] = {
            "source_key": f"movement:ST2026/0927:{direction}",
            "relationship": "transfer movement has a completed header, stable product master and preserved line detail",
            "source_movement_id": source_movement_id,
            "document_no": "ST2026/0927",
            "sku": "98081",
            "location": location,
            "counterparty_location": counterparty,
            "entered_quantity": "1.00",
            "entered_uom": "Carton",
            "direction": direction,
            "files": {
                str(transfers_path.relative_to(source_root)): sha256(transfers_path),
                str(transfer_details_path.relative_to(source_root)): sha256(transfer_details_path),
                str(products_path.relative_to(source_root)): sha256(products_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }

    products = [row for row in rows(products_path) if row["SKU"] == "98081"]
    stock_rows = [row for row in rows(stock_path) if row["SKU"] == "98081"]
    require(len(products) == 1, "98081: expected one product master")
    require(len(stock_rows) == 2, "98081: expected exactly two location stock rows")
    require({row["Location"] for row in stock_rows} == {"Asas General Trading LLC", "DXB"},
            "98081: unexpected stock locations")
    master_qty = quantity(products[0]["Current stock"])
    location_qty = sum((quantity(row["Available Stock"]) for row in stock_rows), Decimal("0"))
    require(master_qty == Decimal("1") and location_qty == master_qty,
            "98081: product and location stock do not reconcile")
    result[188] = {
        "source_key": "98081",
        "relationship": "later capture contains one stable product master and reconciled location stock",
        "product_rows": 1,
        "stock_location_rows": 2,
        "master_quantity": str(master_qty),
        "location_quantity": str(location_qty),
        "locations": {row["Location"]: str(quantity(row["Available Stock"])) for row in stock_rows},
        "files": {
            str(products_path.relative_to(source_root)): sha256(products_path),
            str(stock_path.relative_to(source_root)): sha256(stock_path),
            str(status_path.relative_to(source_root)): sha256(status_path),
        },
    }
    for queue_exception_id, evidence_ids in FINANCIAL_DOCUMENT_REVIEW_EVIDENCE.items():
        supporting = [result[evidence_id] for evidence_id in evidence_ids]
        source_keys = {item["source_key"] for item in supporting}
        require(len(source_keys) == 1,
                f"financial review {queue_exception_id}: supporting evidence does not identify one document")
        source_key = next(iter(source_keys))
        result[queue_exception_id] = {
            "source_key": f"financial_review:{source_key}",
            "relationship": "the operational financial-review exception is fully explained by the linked checksum-verified reconciliation evidence",
            "operational_exception_id": queue_exception_id,
            "supporting_evidence_ids": list(evidence_ids),
            "supporting_reconciliations": supporting,
            "posting_disposition": "reconciled_historical_evidence_only_posting_remains_disabled",
        }

    package_dir = source_root.parent / "var" / "erp_reconciliation_refreshes" / "20260909T101320Z" / "package"
    package_status_path = package_dir / "PACKAGE_STATUS.json"
    require(package_status_path.is_file(), "opening stock package status is missing")
    package_status = json.loads(package_status_path.read_text(encoding="utf-8"))
    stock = package_status.get("stock", {})
    manifest = {item["name"]: item for item in package_status.get("source_manifest", [])}
    opening_capture = source_root / "2026-09-09-reconciliation-20260909T101320Z"
    for name in ("products_current.csv", "stock_snapshot_all_locations_current.csv"):
        path = opening_capture / name
        require(path.is_file(), f"opening stock source is missing: {name}")
        require(manifest.get(name, {}).get("sha256") == sha256(path),
                f"opening stock checksum mismatch: {name}")
    require(package_status.get("source_capture_atomicity") == "NON_ATOMIC",
            "opening stock package must preserve its non-atomic capture qualification")
    require(package_status.get("source_mutation") is False and package_status.get("posting_enabled") is False,
            "opening stock package must remain source-safe and non-posting")
    require(stock.get("reconciled") is True and stock.get("sku_differences") == [],
            "opening stock package does not reconcile product and location quantities")
    require(stock.get("positive_rows") == 579 and stock.get("negative_rows") == 4,
            "opening stock package row qualification changed unexpectedly")
    for queue_exception_id in OPENING_STOCK_BLOCKED_EVIDENCE:
        result[queue_exception_id] = {
            "source_key": "opening_stock:2026-09-09-reconciliation-20260909T101320Z",
            "relationship": "legacy staging opening-stock control is superseded by the approved checksum-verified reconciled import",
            "operational_exception_id": queue_exception_id,
            "positive_positions": stock["positive_rows"],
            "positive_quantity": stock["positive_quantity"],
            "negative_positions_quarantined": stock["negative_rows"],
            "negative_quantity_quarantined": stock["negative_quantity"],
            "net_quantity": stock["net_quantity"],
            "posting_disposition": "approved_non_atomic_opening_stock_import_with_negative_stock_quarantined_posting_remains_disabled",
            "files": {
                str((opening_capture / "products_current.csv").relative_to(source_root)): sha256(opening_capture / "products_current.csv"),
                str((opening_capture / "stock_snapshot_all_locations_current.csv").relative_to(source_root)): sha256(opening_capture / "stock_snapshot_all_locations_current.csv"),
                str(package_status_path.relative_to(source_root.parent)): sha256(package_status_path),
            },
        }

    def unit_alias_signature(row: dict[str, str]) -> tuple[str | None, tuple[str, str] | None]:
        name = row.get("Name", "")
        short = row.get("Short name", "")
        alias_source = (short or name).casefold().replace(" ", "")
        aliases = {
            "pc": "piece", "pcs": "piece", "pc(s)": "piece", "piece": "piece", "pieces": "piece",
            "ctn": "carton", "carton": "carton", "cartons": "carton",
            "pack": "pack", "packs": "pack", "packet": "pack", "packets": "pack",
            "kg": "kg", "kilogram": "kg", "kilograms": "kg", "bundle": "bundle",
        }
        match = re.match(r"^(.*?)\s+\((\d+(?:\.\d+)?)\s*([^()]+(?:\([^()]*\))?)\)\s*$", name.strip())
        if not match:
            return aliases.get(alias_source, alias_source or None), None
        contained = aliases.get(match.group(3).casefold().replace(" ", ""), match.group(3).casefold().strip())
        return aliases.get(alias_source, alias_source or None), (match.group(2), contained)

    registry_signatures: dict[str, set[tuple[str, str]]] = {}
    for row in source_units:
        alias, signature = unit_alias_signature(row)
        if alias in {value[0] for value in UOM_REGISTRY_CONFLICT_ALIASES.values()} and signature:
            registry_signatures.setdefault(alias, set()).add(signature)
    for queue_exception_id, (alias, expected_count) in UOM_REGISTRY_CONFLICT_ALIASES.items():
        signatures = sorted(registry_signatures.get(alias, set()))
        require(len(signatures) == expected_count,
                f"{alias}: expected {expected_count} conflicting source unit definitions")
        result[queue_exception_id] = {
            "source_key": f"uom_registry:{alias}",
            "relationship": "source definitions prove this generic label has multiple package-specific meanings, so global conversion is prohibited",
            "operational_exception_id": queue_exception_id,
            "source_definitions": [{"contained_quantity": quantity, "contained_uom": contained}
                                   for quantity, contained in signatures],
            "conversion_policy": "require_product_specific_factor_to_base_snapshot",
            "posting_disposition": "generic_alias_cannot_post_without_a_product_specific_conversion_snapshot",
            "files": {str(units_path.relative_to(source_root)): sha256(units_path)},
        }

    for queue_exception_id, evidence_ids in AMBIGUOUS_RELATIONSHIP_EVIDENCE.items():
        supporting = [result[evidence_id] for evidence_id in evidence_ids]
        result[queue_exception_id] = {
            "source_key": f"ambiguous_relationship:{queue_exception_id}",
            "relationship": "the formerly ambiguous staging relationship is uniquely established by linked checksum-verified evidence",
            "operational_exception_id": queue_exception_id,
            "supporting_evidence_ids": list(evidence_ids),
            "supporting_reconciliations": supporting,
            "posting_disposition": "relationship_resolved_historical_posting_remains_disabled",
        }

    for queue_exception_id, evidence_ids in JOURNAL_BLUEPRINT_GROSS_COST_EVIDENCE.items():
        supporting = [result[evidence_id] for evidence_id in evidence_ids]
        evidence = supporting[0]
        result[queue_exception_id] = {
            "source_key": f"journal_blueprint:{evidence['source_key']}",
            "relationship": "complete source lines and gross header support a balanced purchase-cost journal without a synthetic input-VAT claim",
            "operational_exception_id": queue_exception_id,
            "supporting_evidence_ids": list(evidence_ids),
            "debit_account_treatment": "inventory_or_purchase_cost_gross",
            "credit_account_treatment": "supplier_payable_gross",
            "input_vat_claim_aed": "0.00",
            "posting_disposition": "blueprint_classified_historical_posting_remains_disabled",
            "files": evidence["files"],
        }

    frozen_products = {row["SKU"]: row for row in rows(products_path)}
    frozen_stock = rows(stock_path)
    for queue_exception_id, (sku, location, expected_quantity, expected_unit, expected_cost) in NEGATIVE_STOCK_QUARANTINE_EVIDENCE.items():
        matches = [row for row in frozen_stock if row["SKU"] == sku and row["Location"] == location]
        require(len(matches) == 1, f"{sku}: negative stock location row is not unique")
        row = matches[0]
        product = frozen_products.get(sku)
        require(product is not None and quantity(row["Available Stock"]) == Decimal(expected_quantity)
                and row["Unit"] == expected_unit and first_money(product["Unit Purchase Price"]) == Decimal(expected_cost),
                f"{sku}: negative stock quarantine evidence differs")
        result[queue_exception_id] = {
            "source_key": f"negative_stock:{sku}:{location}",
            "relationship": "the preserved source stock row is negative and is therefore retained only as a controlled quarantine adjustment",
            "sku": sku, "location": location, "quantity_base_quarantined": expected_quantity,
            "canonical_uom": expected_unit.casefold(), "unit_cost": expected_cost,
            "availability_enabled": False,
            "posting_disposition": "negative_source_balance_quarantined_not_available_not_posted",
            "files": {str(stock_path.relative_to(source_root)): sha256(stock_path),
                      str(products_path.relative_to(source_root)): sha256(products_path)},
        }

    for queue_exception_id, evidence_ids in UOM_CONVERSION_GROUP_EVIDENCE.items():
        supporting = [result[evidence_id] for evidence_id in evidence_ids]
        result[queue_exception_id] = {
            "source_key": f"uom_conversion_group:{queue_exception_id}",
            "relationship": "each affected movement has a checksum-verified product-specific conversion or identity factor; no global carton factor is used",
            "operational_exception_id": queue_exception_id,
            "supporting_evidence_ids": list(evidence_ids),
            "conversion_policy": "entered_quantity_times_product_specific_factor_to_base_snapshot",
            "posting_disposition": "conversion_reconciled_historical_posting_remains_disabled",
        }

    for queue_exception_id, sku in ZERO_QUANTITY_LOCATIONLESS_STOCK_EVIDENCE.items():
        matches = [row for row in frozen_stock if row["SKU"] == sku and not row["Location"]
                   and quantity(row["Available Stock"]) == Decimal("0")]
        require(len(matches) == 1, f"{sku}: expected one locationless zero-quantity source row")
        result[queue_exception_id] = {
            "source_key": f"locationless_zero_stock:{sku}",
            "relationship": "the locationless source row has zero quantity and therefore creates no operational stock balance",
            "sku": sku, "quantity_base": "0.00", "location": None,
            "availability_enabled": False,
            "posting_disposition": "zero_quantity_locationless_row_excluded_from_stock_posting",
            "files": {str(stock_path.relative_to(source_root)): sha256(stock_path)},
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve only checksum-proven earlier-snapshot drift exceptions")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    evidence = build_resolution_evidence(args.source_root)
    output = {"mode": "apply" if args.apply else "dry-run", "batch_key": BATCH_KEY,
              "proven_exception_ids": sorted(evidence), "evidence": evidence,
              "source_mutation": False, "posting_enabled": False}
    if args.apply:
        url = os.getenv("ASAS_OPERATIONAL_DATABASE_URL", "").strip()
        if not url:
            raise SystemExit("ASAS_OPERATIONAL_DATABASE_URL is required for --apply")
        engine = make_operational_engine(url)
        with Session(engine) as session:
            output["resolutions"] = [resolve_promotion_exception(
                session, batch_key=BATCH_KEY, source_exception_id=exception_id, actor=ACTOR,
                resolution_code=resolution_code(exception_id), evidence=evidence[exception_id],
            ) for exception_id in sorted(evidence)]
            session.commit()
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
