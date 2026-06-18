"""
Customer-specific validation rules.
In production this would be per-tenant config; here it's one fictional customer
hardcoded for the assignment demo.
"""

CUSTOMER_RULES = {
    "customer_id": "acme_imports",
    "customer_name": "Acme Imports Ltd",
    "expected_consignee_name": "Acme Imports Ltd",
    "approved_hs_codes": ["8517.62", "8517.70"],
    "allowed_incoterms": ["FOB", "CIF"],
    "expected_port_of_discharge": "Mumbai (INNSA)",
    # Fields with no fixed rule to violate — presence-only checks
    "no_fixed_rule_fields": ["invoice_number", "gross_weight", "description_of_goods", "port_of_loading"],
}

# Confidence threshold below which a field is forced to "uncertain"
# regardless of whether its value happens to match the rule.
LOW_CONFIDENCE_THRESHOLD = 0.6
