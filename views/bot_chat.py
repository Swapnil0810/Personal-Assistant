from __future__ import annotations

import streamlit as st

from core import bot

EXAMPLES = [
    "Add 12,000 to Home Essential, HDFC, rent for October",
    "Spent 4500 yesterday on Extra from SBI: wedding gift",
    "Change the amount of my last wedding entry to 5000",
    "Delete the entry about movie tickets",
    "How much did I spend on wedding from 1 Sep to 30 Sep?",
    "Compare my Extra spending this month vs last month",
    "Show all SIP entries this year",
]


def render():
    st.title("🤖 Finance Bot")
    st.caption("Add, edit, delete and query entries in plain English. Powered by Gemini Flash (free tier).")

    msgs = st.session_state.setdefault("chat", [])
    with st.sidebar:
        with st.expander("Try asking"):
            for e in EXAMPLES:
                st.markdown(f"- {e}")
        if st.button("Clear chat"):
            st.session_state["chat"] = []
            st.rerun()

    for m in msgs:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    prompt = st.chat_input("e.g. Add ₹2,500 Extra, ICICI, dinner with friends")
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"), st.spinner("Working..."):
            reply = bot.chat(msgs, prompt)
            if bot.ERRORS:
                reply += "\n\n**Technical details**\n```\n" + "\n".join(bot.ERRORS) + "\n```"
            st.markdown(reply)
        msgs += [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
