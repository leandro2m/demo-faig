import base64
import os

import requests
import streamlit as st
from strands import Agent

from fortiaigate_model import FortiAIGateModel
from vulnerable_mcp import VULNERABLE_MCP_SSE_URL, build_tool_executor, build_vulnerable_mcp_client

FAIG_BASE_URL = os.environ["FAIG_URL"].rstrip("/")
FAIG_PATH = os.environ.get("FAIG_PATH", "/v1/chat-support")
if not FAIG_PATH.startswith("/"):
    FAIG_PATH = f"/{FAIG_PATH}"
FAIG_URL = f"{FAIG_BASE_URL}{FAIG_PATH}"
FAIG_API_KEY = os.environ["FAIG_API_KEY"]
FAIG_MODEL = os.environ.get("FAIG_MODEL", "openai.gpt-oss-120b-1:0")
FAIG_VERIFY_TLS = os.environ.get("FAIG_VERIFY_TLS", "false").lower() == "true"

st.set_page_config(page_title="FortiAIGate Chat Demo", page_icon="assets/icon.png")

_icon_b64 = base64.b64encode(open("assets/icon.png", "rb").read()).decode()
st.markdown(
    f"""
    <div style="display:flex; align-items:center; gap:16px; margin-bottom:0.25rem;">
        <img src="data:image/png;base64,{_icon_b64}" width="56" height="56" style="display:block;"/>
        <h1 style="margin:0; padding:0; line-height:1;">FortiAIGate Chat Demo</h1>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption(f"Strands Agent routed through FortiAIGate → model: `{FAIG_MODEL}`")


def build_agent(vuln_mcp_enabled: bool) -> Agent:
    old_client = st.session_state.get("mcp_client")
    if old_client is not None:
        old_client.stop(None, None, None)
        st.session_state.mcp_client = None

    tools = []
    tool_executor = None
    if vuln_mcp_enabled:
        client = build_vulnerable_mcp_client()
        client.start()
        st.session_state.mcp_client = client
        tools = client.list_tools_sync()
        tool_executor = build_tool_executor(client)

    return Agent(
        model=FortiAIGateModel(
            url=FAIG_URL,
            api_key=FAIG_API_KEY,
            model_id=FAIG_MODEL,
            verify_tls=FAIG_VERIFY_TLS,
            tool_executor=tool_executor,
        ),
        tools=tools,
        system_prompt="You are a helpful assistant.",
        callback_handler=None,
    )


def on_toggle_vuln_mcp():
    st.session_state.messages = []
    st.session_state.agent = build_agent(st.session_state.vuln_mcp_enabled)


if "messages" not in st.session_state:
    st.session_state.messages = []
if "vuln_mcp_enabled" not in st.session_state:
    st.session_state.vuln_mcp_enabled = False
if "agent" not in st.session_state:
    st.session_state.agent = build_agent(st.session_state.vuln_mcp_enabled)

with st.sidebar:
    st.subheader("Connection")
    st.text(f"Endpoint: {FAIG_URL}")
    st.text(f"Model: {FAIG_MODEL}")
    if st.button("Reset conversation"):
        st.session_state.messages = []
        st.session_state.agent = build_agent(st.session_state.vuln_mcp_enabled)
        st.rerun()

    st.divider()
    st.subheader("⚠️ Vulnerable tool demo")
    st.checkbox(
        "Enable poisoned MCP tool source",
        key="vuln_mcp_enabled",
        on_change=on_toggle_vuln_mcp,
        help=(
            f"Connects to a known-malicious demo MCP server ({VULNERABLE_MCP_SSE_URL}) whose tool "
            "descriptions embed hidden instructions (e.g. exfiltrate secrets). For demoing MCP tool "
            "poisoning only — don't paste real credentials into this chat while it's on."
        ),
    )
    if st.session_state.vuln_mcp_enabled:
        st.warning(
            "This agent's tool list now includes hidden adversarial instructions from an untrusted "
            "MCP server on every turn. Everything from here is part of the vulnerability demo.",
            icon="⚠️",
        )


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask something..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Waiting for FortiAIGate..."):
            try:
                result = st.session_state.agent(prompt)
                reply = str(result)
            except requests.RequestException as exc:
                reply = f"⚠️ Request to FortiAIGate failed: {exc}"
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
