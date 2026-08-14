"""
money_model.py  -- the transparent "what does a failure cost?" model.
=====================================================================

Kept in its own small file ON PURPOSE: the whole point is that a reviewer (or the
founder on the call) can read these assumptions in ten seconds and swap in real
numbers. No hidden magic. All figures are ILLUSTRATIVE, not Pretty Good AI's real data.

The logic maps a graded call to a plain-English failure + a dollar estimate:
  - An uncontained routine call    -> staff has to handle it (staff-time cost).
  - A failed booking / rule break  -> a lost or wrong provider slot.
  - A lost new-patient conversion  -> their highest-value workflow (first visit + lifetime value).
  - A safety / PHI failure         -> flagged as CRITICAL, unpriced liability (we don't fake a lawsuit number).
"""

# --- Editable assumptions (shown verbatim in BUSINESS_IMPACT.md) ---------------
ASSUMPTIONS = {
    "staff_cost_per_uncontained_call": "$8  (~15 min of front-desk time at ~$32/hr, loaded)",
    "value_per_booked_visit": "$150  (one filled provider slot)",
    "value_per_new_patient": "$1,200  (first visit + downstream lifetime value)",
    "note": "Illustrative figures only. Replace with PGA's real numbers and the model updates.",
}

# Numeric versions of the above
STAFF_COST_PER_CALL = 8
VALUE_PER_VISIT = 150
VALUE_PER_NEW_PATIENT = 1200

_BOOKING_SCENARIOS = {"schedule_basic", "reschedule", "weekend_rule", "provider_rule"}


def estimate_call_cost(call, r):
    """
    Returns a dict: {"failure": str|None, "dollars": int, "safety": bool}
    for one graded call. failure=None means no priced leak on this call.
    """
    scenario = call.get("scenario", "")

    # 1) Safety / PHI failures: Critical, but we do NOT invent a liability dollar figure.
    if r.get("safety_ok") is False:
        return {"failure": "SAFETY/PHI failure (Critical, unpriced liability)", "dollars": 0, "safety": True}

    # 2) Lost new-patient conversion (highest-value workflow)
    if scenario == "new_patient" and not (r.get("task_completed") and r.get("contained")):
        return {"failure": "Lost new-patient conversion", "dollars": VALUE_PER_NEW_PATIENT, "safety": False}

    # 3) Failed booking or a rule violation that risks a bad/lost slot
    if scenario in _BOOKING_SCENARIOS and (not r.get("task_completed") or r.get("rule_conformance_ok") is False):
        return {"failure": "Failed booking / rule violation (lost or wrong slot)", "dollars": VALUE_PER_VISIT, "safety": False}

    # 4) Any other routine call the agent failed to contain
    if r.get("contained") is False:
        return {"failure": "Uncontained routine call (staff time)", "dollars": STAFF_COST_PER_CALL, "safety": False}

    return {"failure": None, "dollars": 0, "safety": False}


def summarize_money(graded):
    """
    graded = list of (call, rubric).
    Returns {"rows": [...priced leaks...], "total": int, "safety_flags": [...]}.
    """
    rows, safety_flags, total = [], [], 0
    for call, r in graded:
        est = estimate_call_cost(call, r)
        if est["safety"]:
            safety_flags.append(call["scenario"])
        if est["failure"] and est["dollars"] > 0:
            rows.append({"scenario": call["scenario"], "failure": est["failure"], "dollars": est["dollars"]})
            total += est["dollars"]
    return {"rows": rows, "total": total, "safety_flags": safety_flags}
