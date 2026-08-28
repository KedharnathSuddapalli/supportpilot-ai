"""
Thin Streamlit UI (bonus deliverable) - a non-technical TAM or support
agent could use this directly, without knowing it's calling an LLM
pipeline underneath.

Run with:
    streamlit run ui/app.py

Calls src.triage / src.account_brief directly (no need for uvicorn to be
running separately) - same underlying pipeline as the FastAPI endpoints.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.accounts_data import load_accounts
from src.account_brief import generate_account_brief
from src.triage import triage_ticket

st.set_page_config(page_title="Support & TAM Assistant", page_icon="🎫", layout="wide")

st.title("🎫 Support & TAM Assistant")
st.caption("Ticket triage and QBR account briefs, powered by the same pipeline as the API.")

tab_triage, tab_brief = st.tabs(["Ticket Triage", "Account Brief"])


# --- Tab 1: Ticket Triage --------------------------------------------------

with tab_triage:
    st.subheader("Classify an incoming support ticket")

    col_in, col_out = st.columns([1, 1])

    with col_in:
        subject = st.text_input("Subject", placeholder="e.g. SSO configuration not working for new users")
        body = st.text_area(
            "Body", height=220,
            placeholder="Paste the full ticket text here...",
        )
        run_triage = st.button("Triage ticket", type="primary", use_container_width=True)

    with col_out:
        if run_triage:
            if not body.strip():
                st.warning("Please enter a ticket body.")
            else:
                with st.spinner("Classifying..."):
                    try:
                        result = triage_ticket({"subject": subject, "body": body})
                    except RuntimeError as e:
                        st.error(f"Could not reach the LLM: {e}")
                        result = None
                    except Exception as e:
                        st.error(f"Unexpected error: {type(e).__name__}: {e}")
                        result = None

                if result:
                    urgency_colors = {"P1": "🔴", "P2": "🟠", "P3": "🟡", "P4": "🟢"}
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Urgency", f"{urgency_colors.get(result.urgency_tier, '')} {result.urgency_tier}")
                    m2.metric("Category", result.issue_category)
                    m3.metric("Team", result.recommended_team)

                    st.markdown(f"**Product area:** {result.product_area}")
                    st.markdown(f"**Reasoning:** {result.reasoning}")

                    if result.matched_kb_doc:
                        with st.expander(f"📚 Matched KB doc: {result.matched_kb_doc.doc_path} "
                                          f"(score {result.matched_kb_doc.score:.2f})"):
                            st.markdown(f"*{result.matched_kb_doc.section}*")
                            st.text(result.matched_kb_doc.snippet)
                    else:
                        st.caption("No confident knowledge-base match found.")

                    st.markdown("**Draft first response:**")
                    st.text_area("draft_response", value=result.draft_response, height=160,
                                 label_visibility="collapsed")


# --- Tab 2: Account Brief ---------------------------------------------------

with tab_brief:
    st.subheader("Generate a QBR-ready account brief")

    accounts = load_accounts()
    options = {f"{a['account_id']} — {a['company']} ({a['health_status']})": a["account_id"] for a in accounts}

    col_a, col_b = st.columns([2, 1])
    with col_a:
        choice = st.selectbox("Account", list(options.keys()))
    with col_b:
        force_refresh = st.checkbox("Force refresh (bypass cache)", value=False)

    if st.button("Generate brief", type="primary"):
        account_id = options[choice]
        with st.spinner("Generating brief..."):
            try:
                brief = generate_account_brief(account_id, force_refresh=force_refresh)
            except ValueError as e:
                st.error(str(e))
                brief = None
            except RuntimeError as e:
                st.error(f"Could not reach the LLM: {e}")
                brief = None

        if brief:
            cache_badge = "⚡ cached (instant, guaranteed identical)" if brief.cache_hit else "🆕 freshly generated"
            st.caption(cache_badge)

            st.markdown(f"### {brief.company}")
            st.markdown("#### Executive Summary")
            st.write(brief.executive_summary)

            st.markdown("#### Open Risks & Flagged Issues")
            if brief.open_risks:
                for rf in brief.open_risks:
                    severity_icon = {"High": "🔴", "Medium": "🟠", "Low": "🟡"}.get(rf.severity, "")
                    with st.expander(f"{severity_icon} [{rf.severity}] {rf.risk_type} — ticket {rf.ticket_id}"):
                        st.markdown(f"> {rf.quote}")
                        st.caption(rf.reason)
            else:
                st.caption("No ticket-level risk signals identified in the last 90 days.")

            if brief.account_level_notes:
                st.markdown("#### Account-level Escalation Notes")
                for note in brief.account_level_notes:
                    st.markdown(f"- {note}")

            st.markdown("#### Recommended Talking Points")
            for tp in brief.recommended_talking_points:
                st.markdown(f"- {tp}")

            with st.expander("Metadata"):
                st.json({
                    "prompt_version": brief.prompt_version,
                    "model": brief.model,
                    "generated_at": brief.generated_at,
                    "cache_hit": brief.cache_hit,
                })
